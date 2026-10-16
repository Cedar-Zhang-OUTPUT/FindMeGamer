from pathlib import Path
import subprocess
import json
import os
import sys
import importlib.util
import shutil

import pytest
from sqlalchemy import text
from test_send_pacing_postgres import pg_sending
from test_email_sending import preview


def deployment_tool(name):
    path = ROOT / "deploy/agent-services" / (name + ".py")
    assert path.exists(), f"{name} deployment safety tool is missing"
    spec = importlib.util.spec_from_file_location("deploy_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tool_environment(monkeypatch, app):
    monkeypatch.setenv("FMG_AGENT_DATABASE_URL", app.state.settings.database_url)
    monkeypatch.setenv("FMG_AGENT_SMTP_FROM", "publisher@example.com")


@pytest.mark.postgres
def test_cutover_refuses_inflight_send(pg_sending, monkeypatch):
    app, client, owner = pg_sending
    pid = preview(client, owner).json()["data"]["id"]
    tool = deployment_tool("mail_runtime")
    tool_environment(monkeypatch, app)
    assert tool.main(["hold"]) == 0
    with app.state.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO email_sends (id, token_id, preview_id, idempotency_key, state, created_at, updated_at) VALUES ('inflight', :token, :preview, 'inflight', 'sending', now(), now())"
            ),
            {"token": owner.id, "preview": pid},
        )
    assert tool.main(["check-cutover"]) == 1
    with app.state.engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT state FROM email_sends WHERE id='inflight'"))
            == "sending"
        )


@pytest.mark.postgres
def test_release_refuses_unmapped_identity(pg_sending, monkeypatch):
    app, client, owner = pg_sending
    preview(client, owner)
    tool = deployment_tool("mail_runtime")
    tool_environment(monkeypatch, app)
    assert tool.main(["hold"]) == 0
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE email_previews SET mailbox_id=NULL"))
    assert tool.main(["release"]) == 1
    with app.state.engine.connect() as conn:
        assert conn.execute(
            text("SELECT dispatch_enabled, send_enabled FROM mail_runtime")
        ).one() == (False, False)
        assert (
            conn.scalar(
                text("SELECT count(*) FROM email_previews WHERE mailbox_id IS NULL")
            )
            == 1
        )


@pytest.mark.postgres
def test_rollback_refuses_legacy_worker_with_second_mailbox(pg_sending, monkeypatch):
    app, client, owner = pg_sending
    tool = deployment_tool("mail_runtime")
    tool_environment(monkeypatch, app)
    assert tool.main(["hold"]) == 0
    with app.state.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO mailbox_identities (id,sender) VALUES ('second','second@example.com')"
            )
        )
    assert tool.main(["check-legacy-rollback"]) == 1
    with app.state.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM mailbox_identities")) == 1


@pytest.mark.postgres
def test_maintenance_keeps_read_only_status_available(pg_sending, monkeypatch, capsys):
    from test_email_sending import send
    from fmg_agent.outreach import process_recipient
    from fmg_agent.email.retries import process_retry

    app, client, owner = pg_sending
    pid = preview(client, owner).json()["data"]["id"]
    tool = deployment_tool("mail_runtime")
    tool_environment(monkeypatch, app)
    assert tool.main(["hold"]) == 0
    capsys.readouterr()
    assert tool.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["send_enabled"] is False
    app.state.smtp_transport = lambda *args: pytest.fail("maintenance reached provider")
    assert (
        send(client, owner, pid).json()["error"]["code"] == "mail_service_maintenance"
    )
    assert client.get("/v1/health").status_code == 200


def test_queue_audit_unknown_type_blocks():
    tool = deployment_tool("queue_cutover")
    raw = json.dumps(
        {
            "headers": {"task": "unrecognized.task", "id": "x"},
            "body": "W1siaWQiXSwge30sIHt9XQ==",
            "properties": {},
        }
    )
    report = tool.decode_message(raw)
    assert report["recognized"] is False
    assert report["task"] == "unrecognized.task"


@pytest.mark.parametrize(
    "damage", ["missing", "stale", "role", "queue", "concurrency", "process", "schema"]
)
def test_role_probe_refuses_invalid_evidence(tmp_path, monkeypatch, damage):
    import time
    from fmg_agent import role_health
    from fmg_agent.config import Settings

    monkeypatch.setenv("FMG_AGENT_ROLE_HEALTH_DIR", str(tmp_path))
    settings = Settings(database_url="sqlite:///probe-only")
    record = role_health.record(settings, "mail", "alpha")
    path = role_health.path_for(settings, "mail", "alpha")
    if damage == "missing":
        path.unlink()
    else:
        record.update(
            {
                "stale": {"time": time.time() - 1000},
                "role": {"role": "enrichment"},
                "queue": {"queue": "fmg_mail.beta"},
                "concurrency": {"concurrency": 4},
                "process": {"pid": 99999999},
                "schema": {"schema": "old"},
            }[damage]
        )
        path.write_text(json.dumps(record))
    with pytest.raises((ValueError, OSError)):
        role_health.probe(settings, "mail", "alpha")


@pytest.mark.postgres
def test_held_monitor_is_locally_ready_without_upstream(
    pg_sending, monkeypatch, tmp_path
):
    from threading import Event, Thread
    from fmg_agent.email import monitor
    from fmg_agent import role_health
    from fmg_agent.mail_runtime import set_runtime
    from mailbox_runtime_fixture import until

    app, *_ = pg_sending
    monkeypatch.setenv("FMG_AGENT_ROLE_HEALTH_DIR", str(tmp_path))
    set_runtime(app.state.sessions, dispatch_enabled=False, send_enabled=False)
    monkeypatch.setattr(
        monitor,
        "sync_once",
        lambda *a, **k: pytest.fail("held monitor contacted upstream"),
    )
    stop = Event()
    thread = Thread(
        target=monitor.monitor_mailbox, args=(app.state.settings, "ontologyplay", stop)
    )
    thread.start()
    try:
        path = role_health.path_for(app.state.settings, "monitor", "ontologyplay")
        until(path.exists, 5)
        assert (
            role_health.probe(app.state.settings, "monitor", "ontologyplay")["mode"]
            == "held-local"
        )
    finally:
        stop.set()
        thread.join(5)
    with pytest.raises((ValueError, OSError)):
        role_health.probe(app.state.settings, "monitor", "ontologyplay")


@pytest.mark.postgres
def test_safety_paused_mailbox_still_monitors(pg_sending, monkeypatch):
    from threading import Event
    from fmg_agent.email import monitor, safety

    app, *_ = pg_sending
    with app.state.sessions() as session:
        safety.trip(session, "publisher@example.com", "bounce_retry_failures")
        session.commit()
    stop, scanned = Event(), []

    def sync(*args, **kwargs):
        scanned.append(kwargs["mailbox_id"])
        stop.set()
        return {"state": "active"}

    monkeypatch.setattr(monitor, "sync_once", sync)
    monitor.monitor_mailbox(app.state.settings, "ontologyplay", stop)
    assert scanned == ["ontologyplay"]


@pytest.fixture
def cutover_broker():
    import redis
    from uuid import uuid4

    url = os.environ["FMG_AGENT_TEST_REDIS_URL"]
    broker = redis.Redis.from_url(url)
    assert broker.connection_pool.connection_kwargs["host"] == "127.0.0.1"
    assert broker.connection_pool.connection_kwargs["db"] == 14
    prefix = "cutover_" + uuid4().hex + ":"
    yield broker, prefix
    keys = list(broker.scan_iter(match=prefix + "*"))
    if keys:
        broker.delete(*keys)


def legacy_message(task, identifier):
    import base64

    return json.dumps(
        {
            "headers": {"task": task, "id": identifier},
            "body": base64.b64encode(
                json.dumps([[identifier], {}, {}]).encode()
            ).decode(),
            "properties": {},
        }
    ).encode()


@pytest.mark.postgres
def test_queue_unknown_audit_is_read_only_and_migrate_nonzero(
    pg_sending, cutover_broker, tmp_path, monkeypatch
):
    app, *_ = pg_sending
    broker, prefix = cutover_broker
    tool = deployment_tool("queue_cutover")
    tool_environment(monkeypatch, app)
    monkeypatch.setenv("FMG_AGENT_BROKER_URL", os.environ["FMG_AGENT_TEST_REDIS_URL"])
    raw = legacy_message("unexpected.task", "keep-me")
    broker.lpush(prefix + "fmg_agent", raw)
    manifest = tmp_path / "audit.json"
    assert tool.main(["audit", "--prefix", prefix, "--manifest", str(manifest)]) == 1
    assert json.loads(manifest.read_text())["unknown"] == 1
    assert (
        tool.main(
            ["migrate", "--prefix", prefix, "--manifest", str(manifest), "--confirm"]
        )
        == 1
    )
    assert broker.lrange(prefix + "fmg_agent", 0, -1) == [raw]


@pytest.mark.postgres
def test_queue_publish_then_exact_ack_restart_and_snapshot_restore(
    pg_sending, cutover_broker, tmp_path
):
    from fmg_agent.email.jobs import JobStore
    from fmg_agent.mail_runtime import set_runtime

    app, _, owner = pg_sending
    broker, prefix = cutover_broker
    tool = deployment_tool("queue_cutover")
    job = JobStore(app.state.sessions).create(
        owner.id, "cutover", {"url": "https://example.com"}
    )
    raw = legacy_message("fmg_agent.email.enrich", job["id"])
    key = prefix + "fmg_agent"
    broker.lpush(key, raw)
    with app.state.sessions() as session:
        manifest = tool.audit(broker, session, prefix=prefix)
    # Snapshot contains exact recoverable bytes, independent of the live list.
    import base64

    assert base64.b64decode(manifest["messages"][0]["raw"]) == raw
    set_runtime(app.state.sessions, dispatch_enabled=False, send_enabled=False)
    calls = []

    def interrupted(task, identifier, queue):
        calls.append((task, identifier, queue))
        raise ConnectionError("publication outcome uncertain")

    with pytest.raises(ConnectionError):
        tool.migrate(
            broker,
            app.state.sessions,
            app.state.mailboxes,
            manifest,
            interrupted,
            tmp_path / "progress",
        )
    assert broker.lrange(key, 0, -1) == [raw]

    def published(task, identifier, queue):
        assert broker.lrange(key, 0, -1) == [raw]
        calls.append((task, identifier, queue))
        broker.lpush(prefix + queue, identifier)

    result = tool.migrate(
        broker,
        app.state.sessions,
        app.state.mailboxes,
        manifest,
        published,
        tmp_path / "progress",
    )
    assert result == {"published": 1, "retained_db": 0, "already_absent": 0}
    assert calls[-1] == ("fmg_agent.email.enrich", job["id"], "fmg_enrichment")
    assert broker.llen(key) == 0
    assert (
        tool.migrate(
            broker,
            app.state.sessions,
            app.state.mailboxes,
            manifest,
            published,
            tmp_path / "progress",
        )["already_absent"]
        == 1
    )
    assert broker.llen(prefix + "fmg_enrichment") == 1
    assert JobStore(app.state.sessions).load(job["id"])["state"] == "queued"
    broker.rpush(key, base64.b64decode(manifest["messages"][0]["raw"]))
    assert broker.lrange(key, 0, -1) == [raw]


@pytest.mark.parametrize("drained", [True, False])
def test_deploy_warm_shutdown_never_force_kills_and_stays_held(tmp_path, drained):
    log = tmp_path / "calls"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import os,sys,json
from pathlib import Path
a=sys.argv[1:]
with open(os.environ['CALL_LOG'],'a') as f: f.write(json.dumps(a)+'\\n')
if 'backup' in a: print('fixture dump bytes')
if 'ps' in a and '--services' in a:
    p=Path(os.environ['STOP_STATE'])
    if not p.exists(): print('api\\nworker\\nmail-worker\\nmail-worker-second\\ndispatch\\nmonitor')
if 'ps' in a and '--quiet' in a: print('fixture-container')
if 'kill' in a and os.environ['DRAINED']=='1': Path(os.environ['STOP_STATE']).touch()
"""
    )
    docker.chmod(0o755)
    admin = binaries / "admin"
    admin.write_text(
        """#!/usr/bin/env python3
import os,sys,json
with open(os.environ['CALL_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
"""
    )
    admin.chmod(0o755)
    private = tmp_path / "private.env"
    private.write_text("fixture")
    private.chmod(0o600)
    result = subprocess.run(
        [
            "sh",
            str(ROOT / "deploy/agent-services/deploy.sh"),
            "--apply",
            "--proxy-writes-blocked",
            str(tmp_path / "backup"),
        ],
        env=dict(
            os.environ,
            PATH=str(binaries) + os.pathsep + os.environ["PATH"],
            CALL_LOG=str(log),
            STOP_STATE=str(tmp_path / "stopped"),
            DRAINED="1" if drained else "0",
            FMG_AGENT_DRAIN_SECONDS="0",
            FMG_AGENT_PYTHON=str(admin),
            FMG_AGENT_ENV_FILE=str(private),
            FMG_AGENT_PG_ENV_FILE=str(private),
            FMG_AGENT_MAILBOXES_HOST_FILE=str(private),
            FMG_AGENT_ADMIN_ENV_FILE=str(private),
        ),
        capture_output=True,
        text=True,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    if not drained:
        assert result.returncode == 1
        assert "no process was force-killed" in result.stderr
        assert not any(
            "up" in args or "migrate" in args or "SIGKILL" in args for args in calls
        )
        assert (tmp_path / "backup/drain-incomplete.json").exists()
        return
    assert result.returncode == 0, result.stderr
    shutdown = next(args for args in calls if "kill" in args)
    assert shutdown[-8:] == [
        "--signal",
        "SIGTERM",
        "api",
        "worker",
        "mail-worker",
        "mail-worker-second",
        "dispatch",
        "monitor",
    ]
    assert not any(
        "stop" in args or "SIGKILL" in args or "release" in args for args in calls
    )
    start = next(args for args in calls if "up" in args)
    assert start[-5:] == ["api", "worker", "mail-worker", "dispatch", "monitor"]
    assert any("readiness" in args for args in calls)
    assert ["update", "--restart=no", "fixture-container"] in calls


@pytest.mark.postgres
def test_preflight_apply_refuses_open_runtime(pg_sending, monkeypatch):
    app, client, owner = pg_sending
    pid = preview(client, owner).json()["data"]["id"]
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE email_previews SET mailbox_id=NULL"))
    tool_environment(monkeypatch, app)
    tool = deployment_tool("mailbox_preflight")
    assert tool.main(["--apply", "--quiescent"]) == 1
    with app.state.engine.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT mailbox_id FROM email_previews WHERE id=:id"), {"id": pid}
            )
            is None
        )


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.postgres
def test_held_enrichment_consumer_makes_no_paid_call(pg_sending):
    from fmg_agent.worker import create_worker
    from fmg_agent.email.jobs import JobStore
    from fmg_agent.mail_runtime import set_runtime

    app, _, owner = pg_sending
    job = JobStore(app.state.sessions).create(
        owner.id, "held-enrichment", {"url": "https://example.com"}
    )
    set_runtime(app.state.sessions, dispatch_enabled=False, send_enabled=False)
    worker = create_worker(
        app.state.settings,
        enricher_factory=lambda: pytest.fail("held worker constructed provider"),
    )
    try:
        assert worker.tasks["fmg_agent.email.enrich"].run(job["id"]) == {
            "code": "mail_service_maintenance"
        }
        assert JobStore(app.state.sessions).load(job["id"])["state"] == "queued"
    finally:
        worker.close()


@pytest.mark.postgres
def test_native_backup_restore_preserves_auth_and_frozen_history(pg_sending, tmp_path):
    from sqlalchemy import create_engine
    from fmg_agent.email.identity import _snapshot

    app, client, owner = pg_sending
    preview(client, owner)
    with app.state.sessions() as session:
        before = _snapshot(session)
        schema = session.scalar(text("SELECT current_schema()"))
        auth = session.execute(
            text("SELECT id,digest,scopes FROM access_tokens ORDER BY id")
        ).all()
    assert schema.startswith("send_pacing_")
    retained = schema + "_retained"
    base = create_engine(os.environ["FMG_AGENT_TEST_DATABASE_URL"])
    assert base.url.database == "find_me_gamer_agent_test"
    dsn = base.url.set(drivername="postgresql").render_as_string(hide_password=False)
    dump = tmp_path / "native.dump"
    pg_dump = shutil.which("pg_dump")
    assert pg_dump, "Native backup rehearsal requires PostgreSQL client tools"
    pg_restore = str(Path(pg_dump).with_name("pg_restore"))
    dumped = subprocess.run(
        [
            pg_dump,
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--schema",
            schema,
            "--file",
            str(dump),
            dsn,
        ],
        capture_output=True,
        text=True,
    )
    assert dumped.returncode == 0, dumped.stderr
    app.state.engine.dispose()
    with base.begin() as conn:
        conn.execute(text(f'ALTER SCHEMA "{schema}" RENAME TO "{retained}"'))
    try:
        restored = subprocess.run(
            [
                pg_restore,
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "--dbname",
                dsn,
                str(dump),
            ],
            capture_output=True,
            text=True,
        )
        assert restored.returncode == 0, restored.stderr
        with app.state.sessions() as session:
            assert _snapshot(session) == before
            assert (
                session.execute(
                    text("SELECT id,digest,scopes FROM access_tokens ORDER BY id")
                ).all()
                == auth
            )
    finally:
        with base.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{retained}" CASCADE'))
        base.dispose()


@pytest.mark.postgres
def test_cutover_routes_only_approved_unattempted_recipients(
    pg_sending, cutover_broker, tmp_path
):
    from fmg_agent.email.identity import _snapshot
    from fmg_agent.email.models import EmailSend
    from fmg_agent.outreach import OutreachTask, OutreachRecipient
    from test_queue_isolation import seed_batches

    app, client, owner = pg_sending
    seed_batches(app, client, owner)
    tool = deployment_tool("queue_cutover")
    with app.state.sessions() as session:
        before = _snapshot(session)
        message = {"task": "fmg_agent.outreach.send", "identifier": "alpha-00"}
        assert tool.route(session, app.state.mailboxes, message) == "fmg_mail.alpha"
        task = session.get(OutreachTask, "alpha")
        for state in ("draft", "paused", "blocked"):
            task.state = state
            session.flush()
            assert tool.route(session, app.state.mailboxes, message) is None
        task.state = "sending"
        recipient = session.get(OutreachRecipient, "alpha-00")
        session.add(
            EmailSend(
                token_id=owner.id,
                preview_id=recipient.preview_id,
                idempotency_key="unknown",
                state="unknown",
            )
        )
        session.flush()
        assert tool.route(session, app.state.mailboxes, message) is None
        session.rollback()
        assert _snapshot(session) == before


def test_release_refuses_unmigrated_legacy_queue(cutover_broker):
    tool = deployment_tool("mail_runtime")
    broker, prefix = cutover_broker
    raw = legacy_message("unknown.task", "do-not-consume")
    broker.lpush(prefix + "fmg_agent", raw)
    with pytest.raises(ValueError):
        tool.legacy_drained(broker, prefix=prefix)
    assert broker.lrange(prefix + "fmg_agent", 0, -1) == [raw]


def test_role_probe_refuses_unconfigured_enabled_mailbox(tmp_path, monkeypatch):
    from fmg_agent import role_health
    from fmg_agent.config import Settings

    monkeypatch.setenv("FMG_AGENT_ROLE_HEALTH_DIR", str(tmp_path))
    settings = Settings(
        database_url="sqlite:///probe-only", smtp_from="publisher@example.com"
    )
    role_health.record(settings, "mail", "ontologyplay")
    with pytest.raises(ValueError):
        role_health.probe(settings, "mail", "ontologyplay")


@pytest.mark.postgres
@pytest.mark.parametrize(
    "target", ["alias", "schema", "database", "redis_db", "expired"]
)
def test_role_target_challenge_proves_shared_services(
    pg_sending, cutover_broker, tmp_path, monkeypatch, target
):
    from contextlib import nullcontext
    from fmg_agent import role_health
    from pydantic import SecretStr
    from sqlalchemy.engine import make_url

    app, *_ = pg_sending
    broker, prefix = cutover_broker
    tool = deployment_tool("mail_runtime")
    monkeypatch.setenv("FMG_AGENT_ROLE_HEALTH_DIR", str(tmp_path))
    settings = app.state.settings.model_copy(
        update={"broker_url": SecretStr(os.environ["FMG_AGENT_TEST_REDIS_URL"])}
    )
    # Distinct URL spellings must succeed when both connections reach the same
    # physical test services. No credentials or configured labels prove this.
    settings = settings.model_copy(
        update={
            "database_url": settings.database_url.replace("127.0.0.1", "localhost"),
            "broker_url": SecretStr(
                settings.broker_url.get_secret_value().replace("127.0.0.1", "localhost")
            ),
        }
    )
    if target == "schema":
        settings = settings.model_copy(
            update={
                "database_url": make_url(settings.database_url)
                .set(query={"options": "-c search_path=public"})
                .render_as_string(hide_password=False)
            }
        )
    if target == "database":
        # Read-only connection to the local server's postgres maintenance DB;
        # no tables/schema/data are created there, and no production URL is used.
        settings = settings.model_copy(
            update={
                "database_url": make_url(settings.database_url)
                .set(database="postgres", query={})
                .render_as_string(hide_password=False)
            }
        )
    if target == "redis_db":
        # The probe only GETs a random key from DB 15; all fixture writes stay
        # in its owned UUID prefix in DB 14.
        settings = settings.model_copy(
            update={"broker_url": SecretStr("redis://127.0.0.1:55442/15")}
        )
    role_health.record(settings, "enrichment")
    with (
        app.state.sessions() as session,
        (
            pytest.raises(ValueError, match="cleanup")
            if target == "expired"
            else nullcontext()
        ),
    ):
        with tool.deployment_challenge(session, broker, prefix=prefix) as challenge:
            key = challenge["redis_key"]
            assert broker.ttl(key) > 0
            if target == "expired":
                broker.delete(key)
            if target == "alias":
                assert (
                    role_health.probe(settings, "enrichment", challenge=challenge)[
                        "target_proof"
                    ]
                    == challenge["nonce"]
                )
            else:
                with pytest.raises(ValueError):
                    role_health.probe(settings, "enrichment", challenge=challenge)
            cli = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fmg_agent.role_health",
                    "api",
                    "--challenge",
                    json.dumps(challenge),
                ],
                env=dict(
                    os.environ,
                    FMG_AGENT_DATABASE_URL=settings.database_url,
                    FMG_AGENT_BROKER_URL=settings.broker_url.get_secret_value(),
                ),
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert cli.returncode == (0 if target == "alias" else 1)
            if target == "alias":
                assert json.loads(cli.stdout)["target_proof"] == challenge["nonce"]
        assert not broker.exists(key)


def test_role_artifact_rejects_changed_broker(tmp_path, monkeypatch):
    from fmg_agent import role_health
    from fmg_agent.config import Settings
    from pydantic import SecretStr

    monkeypatch.setenv("FMG_AGENT_ROLE_HEALTH_DIR", str(tmp_path))
    settings = Settings(
        database_url="sqlite:///local-artifact", broker_url="redis://localhost/14"
    )
    role_health.record(settings, "enrichment")
    changed = settings.model_copy(
        update={"broker_url": SecretStr("redis://localhost/15")}
    )
    with pytest.raises(ValueError):
        role_health.probe(changed, "enrichment")


@pytest.mark.postgres
@pytest.mark.parametrize(
    "fault", [None, "database", "schema", "redis_db", "nonce", "role", "cleanup"]
)
def test_release_validates_actual_targets_before_opening_gates(
    pg_sending, cutover_broker, tmp_path, monkeypatch, fault
):
    from fmg_agent import role_health
    from fmg_agent.email.identity import _snapshot
    from pydantic import SecretStr
    from sqlalchemy.engine import make_url

    app, client, owner = pg_sending
    preview(client, owner)
    broker, _ = cutover_broker
    tool = deployment_tool("mail_runtime")
    settings = app.state.settings.model_copy(
        update={"broker_url": SecretStr(os.environ["FMG_AGENT_TEST_REDIS_URL"])}
    )
    monkeypatch.setattr(tool, "admin_settings", lambda: settings)
    monkeypatch.setenv("FMG_AGENT_ROLE_HEALTH_DIR", str(tmp_path))
    challenge_keys = []

    def compose(file, *args):
        if args[0] == "ps":
            return "api worker mail-worker dispatch monitor"
        if "-c" in args:
            return ""  # HTTP health boundary only; target probes below are real.
        role = args[args.index("fmg_agent.role_health") + 1]
        mailbox = args[args.index("--mailbox") + 1] if "--mailbox" in args else None
        challenge = json.loads(args[args.index("--challenge") + 1])
        challenge_keys.append(challenge["redis_key"])
        local = settings.model_copy(
            update={
                "database_url": settings.database_url.replace("127.0.0.1", "localhost"),
                "broker_url": SecretStr(
                    settings.broker_url.get_secret_value().replace(
                        "127.0.0.1", "localhost"
                    )
                ),
            }
        )
        if role == "enrichment":
            if fault == "database":
                local = local.model_copy(
                    update={
                        "database_url": make_url(local.database_url)
                        .set(database="postgres", query={})
                        .render_as_string(hide_password=False)
                    }
                )
            if fault == "schema":
                local = local.model_copy(
                    update={
                        "database_url": make_url(local.database_url)
                        .set(query={"options": "-c search_path=public"})
                        .render_as_string(hide_password=False)
                    }
                )
            if fault == "redis_db":
                local = local.model_copy(
                    update={"broker_url": SecretStr("redis://127.0.0.1:55442/15")}
                )
        if role == "api":
            report = {
                "role": role,
                "target_proof": role_health.target_proof(local, challenge),
            }
        else:
            role_health.record(local, role, mailbox, mode="held-local")
            report = role_health.probe(local, role, mailbox, challenge=challenge)
        if role == "enrichment" and fault in ("nonce", "role"):
            report["target_proof" if fault == "nonce" else "role"] = "mismatch"
        if role == "monitor" and fault == "cleanup":
            broker.delete(challenge["redis_key"])
        return json.dumps(report)

    monkeypatch.setattr(tool, "compose", compose)
    assert tool.main(["hold"]) == 0
    with app.state.sessions() as session:
        before = _snapshot(session)
    assert tool.main(["release"]) == (0 if fault is None else 1)
    with app.state.sessions() as session:
        assert session.execute(
            text("SELECT dispatch_enabled,send_enabled FROM mail_runtime")
        ).one() == (fault is None, fault is None)
        assert _snapshot(session) == before
    assert challenge_keys and not any(broker.exists(key) for key in challenge_keys)


@pytest.mark.postgres
def test_release_refuses_missing_roles(pg_sending, monkeypatch):
    app, client, owner = pg_sending
    preview(client, owner)
    tool = deployment_tool("mail_runtime")
    tool_environment(monkeypatch, app)
    assert tool.main(["hold"]) == 0
    monkeypatch.setattr(
        tool, "compose", lambda *args: "api\nworker\nmail-worker\ndispatch\n"
    )
    assert tool.main(["release"]) == 1
    with app.state.engine.connect() as conn:
        assert conn.execute(
            text("SELECT dispatch_enabled,send_enabled FROM mail_runtime")
        ).one() == (False, False)


@pytest.mark.postgres
def test_queue_cli_publishes_real_kombu_envelope(
    pg_sending, cutover_broker, tmp_path, monkeypatch
):
    from fmg_agent.email.jobs import JobStore

    app, _, owner = pg_sending
    broker, prefix = cutover_broker
    tool_environment(monkeypatch, app)
    monkeypatch.setenv("FMG_AGENT_BROKER_URL", os.environ["FMG_AGENT_TEST_REDIS_URL"])
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n")
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    runtime = deployment_tool("mail_runtime")
    assert runtime.main(["hold"]) == 0
    job = JobStore(app.state.sessions).create(
        owner.id, "cli-migrate", {"url": "https://example.com"}
    )
    broker.lpush(
        prefix + "fmg_agent", legacy_message("fmg_agent.email.enrich", job["id"])
    )
    tool = deployment_tool("queue_cutover")
    manifest = tmp_path / "queues.json"
    assert tool.main(["audit", "--prefix", prefix, "--manifest", str(manifest)]) == 0
    assert (
        tool.main(
            ["migrate", "--prefix", prefix, "--manifest", str(manifest), "--confirm"]
        )
        == 0
    )
    assert broker.llen(prefix + "fmg_agent") == 0
    messages = broker.lrange(prefix + "fmg_enrichment", 0, -1)
    assert len(messages) == 1
    decoded = tool.decode_message(messages[0])
    assert decoded["recognized"] is True
    assert decoded["task"] == "fmg_agent.email.enrich"
    assert decoded["identifier"] == job["id"]
    assert JobStore(app.state.sessions).load(job["id"])["state"] == "queued"


def test_deploy_requires_explicit_apply_before_docker():
    result = subprocess.run(
        ["sh", str(ROOT / "deploy/agent-services/deploy.sh")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "disabled by default" in result.stderr


def test_smoke_rejects_mismatched_cli_target_before_network(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"server": "https://old.example.com", "token": "test-only"})
    )
    result = subprocess.run(
        ["sh", str(ROOT / "deploy/agent-services/smoke.sh"), "https://new.example.com"],
        env=dict(os.environ, FMG_CONFIG=str(config)),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "exact smoke target" in result.stderr


def test_bootstrap_requires_explicit_apply():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "deploy/agent-services/bootstrap_existing.py"),
            "--source-container",
            "not-a-real-container",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "explicit --apply" in result.stderr


def test_backup_rejects_non_project_destination_before_docker():
    result = subprocess.run(
        ["sh", str(ROOT / "deploy/agent-services/backup.sh")],
        env=dict(os.environ, FMG_AGENT_BACKUP_S3="s3://other-project/backups/"),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
