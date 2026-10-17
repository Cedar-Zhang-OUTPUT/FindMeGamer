"""Opt-in local image, CLI, migration and backup/restore rehearsal. No upstream calls."""

import json
import importlib.util
import os
from pathlib import Path
import subprocess
import time
import uuid
import urllib.request
import warnings

import pytest
import redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.postgres
def test_local_release_image_and_restore(tmp_path):
    image = os.environ.get("FMG_AGENT_TEST_IMAGE")
    if not image:
        pytest.skip(
            "Opt in with FMG_AGENT_TEST_IMAGE naming a locally built test image"
        )
    url = os.environ["FMG_AGENT_TEST_DATABASE_URL"]
    engine = create_engine(url)
    assert engine.url.host == "127.0.0.1"
    assert engine.url.database == "find_me_gamer_agent_test"
    broker_url = os.environ.get(
        "FMG_AGENT_TEST_REDIS_URL", "redis://127.0.0.1:55440/14"
    )
    broker_options = redis.ConnectionPool.from_url(broker_url).connection_kwargs
    assert broker_options["host"] == "127.0.0.1"
    assert broker_options["db"] == 14
    suffix = uuid.uuid4().hex
    schema = "release_test_" + suffix
    api, worker = "fmg-release-api-" + suffix, "fmg-release-worker-" + suffix
    dispatcher = "fmg-release-dispatch-" + suffix
    mail = "fmg-release-mail-" + suffix
    monitor = "fmg-release-monitor-" + suffix
    db_container = os.environ.get(
        "FMG_AGENT_TEST_POSTGRES_CONTAINER", "fmg-agent-tests-postgres-1"
    )
    network = os.environ.get("FMG_AGENT_TEST_NETWORK", "fmg-agent-tests_default")
    owned_containers = [api, worker, dispatcher, mail, monitor]

    def run(*args, **kwargs):
        # Name transient containers too, so a timed-out Docker client cannot
        # leave an untracked migration/admin process behind.
        if args[:2] == ("docker", "run") and "--rm" in args:
            name = "fmg-release-task-" + uuid.uuid4().hex
            owned_containers.append(name)
            args = (*args[:2], "--name", name, *args[2:])
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            timeout=kwargs.pop("timeout", 120),
            **kwargs,
        )

    env = [
        "-e",
        "FMG_AGENT_DATABASE_URL=postgresql+psycopg://fmg_agent_test:local-test-only@postgres:5432/find_me_gamer_agent_test",
        "-e",
        f"PGOPTIONS=-c search_path={schema}",
        "-e",
        "FMG_AGENT_BROKER_URL=redis://redis:6379/14",
        "-e",
        "FMG_AGENT_SMTP_FROM=release-test@example.com",
    ]
    for key, value in {
        "SMTP_HOST": "smtp.virtual.invalid",
        "SMTP_USERNAME": "offline-test",
        "SMTP_PASSWORD": "offline-test-only",
        "IMAP_HOST": "imap.virtual.invalid",
        "IMAP_USERNAME": "offline-test",
        "IMAP_PASSWORD": "offline-test-only",
    }.items():
        env.extend(["-e", f"FMG_AGENT_{key}={value}"])
    common = ["docker", "run", "--pull=never", "--network", network, *env]
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        for _ in range(2):
            run(*common, "--rm", image, "python", "-m", "alembic", "upgrade", "head")
        token = json.loads(
            run(
                *common,
                "--rm",
                image,
                "python",
                "-m",
                "fmg_agent.admin",
                "token",
                "create",
                "--label",
                "release-test",
                "--scope",
                "read",
                "--scope",
                "email:send",
            ).stdout
        )
        run(*common, "-d", "--name", api, "-p", "127.0.0.1::8000", image)
        run(
            *common,
            "--rm",
            image,
            "python",
            "-c",
            "from fmg_agent.config import Settings; from fmg_agent.db import database; "
            "from fmg_agent.mail_runtime import check_readiness,set_runtime; "
            "settings=Settings(); engine,sessions=database(settings); "
            "check_readiness(settings,sessions); "
            "set_runtime(sessions,dispatch_enabled=False,send_enabled=False); engine.dispose()",
        )
        run(
            *common,
            "-d",
            "--name",
            worker,
            image,
            "python",
            "-m",
            "fmg_agent.worker",
            "--role",
            "enrichment",
        )
        run(
            *common,
            "-d",
            "--name",
            dispatcher,
            image,
            "python",
            "-m",
            "fmg_agent.dispatch",
        )
        run(
            *common,
            "-d",
            "--name",
            mail,
            image,
            "python",
            "-m",
            "fmg_agent.worker",
            "--role",
            "mail",
            "--mailbox",
            "ontologyplay",
        )
        run(
            *common,
            "-d",
            "--name",
            monitor,
            image,
            "python",
            "-m",
            "fmg_agent.email.monitor",
        )
        spec = importlib.util.spec_from_file_location(
            "release_deployment_tool", ROOT / "deploy/agent-services/mail_runtime.py"
        )
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        roles = [
            (api, "api", None, None, None),
            (worker, "enrichment", None, "fmg_enrichment", 4),
            (mail, "mail", "ontologyplay", "fmg_mail.ontologyplay", 2),
            (dispatcher, "dispatch", None, None, None),
            (monitor, "monitor", "ontologyplay", None, None),
        ]
        with (
            engine.connect() as connection,
            Session(bind=connection) as session,
            redis.Redis.from_url(broker_url, socket_timeout=5) as broker,
        ):
            session.execute(text(f'SET search_path TO "{schema}"'))
            with tool.deployment_challenge(session, broker) as challenge:
                for container, role, mailbox, queue, concurrency in roles:
                    deadline = time.monotonic() + 45
                    command = [
                        "docker",
                        "exec",
                        container,
                        "python",
                        "-m",
                        "fmg_agent.role_health",
                        role,
                        "--challenge",
                        json.dumps(challenge),
                    ]
                    if mailbox:
                        command.extend(["--mailbox", mailbox])
                    while True:
                        try:
                            evidence = json.loads(run(*command, timeout=15).stdout)
                            break
                        except subprocess.CalledProcessError:
                            if time.monotonic() >= deadline:
                                raise
                            time.sleep(0.25)
                    assert evidence["role"] == role
                    assert evidence["target_proof"] == challenge["nonce"]
                    if role != "api":
                        assert evidence["schema"] == "0013_mail_runtime"
                        assert evidence["mailbox"] == mailbox
                        assert evidence["queue"] == queue
                        assert evidence["concurrency"] == concurrency
                        assert evidence["pid"] > 0
                        assert evidence["process_start"].isdigit()
                        assert evidence["mode"] == (
                            "held-local" if role == "monitor" else "local-ready"
                        )
                assert session.execute(
                    text("SELECT dispatch_enabled, send_enabled FROM mail_runtime")
                ).one() == (False, False)
            assert broker.get(challenge["redis_key"]) is None
        # API has no role-ready file: separately prove its container PID is live
        # and uses Linux /proc start-time evidence, alongside its target proof.
        api_process = json.loads(
            run(
                "docker",
                "exec",
                api,
                "python",
                "-c",
                "import json,os; from pathlib import Path; "
                "from fmg_agent.role_health import process_start; "
                "assert Path('/proc/1/stat').is_file(); os.kill(1,0); "
                "print(json.dumps({'pid':1,'process_start':process_start(1)}))",
            ).stdout
        )
        assert api_process["pid"] == 1
        assert api_process["process_start"].isdigit()
        # Close the two roles capable of mail I/O before opening either gate.
        run("docker", "stop", "-t", "10", monitor, mail)
        for container in (monitor, mail):
            assert (
                run(
                    "docker", "inspect", "--format", "{{.State.ExitCode}}", container
                ).stdout.strip()
                == b"0"
            )
        run(
            *common,
            "--rm",
            image,
            "python",
            "-c",
            "from fmg_agent.config import Settings; from fmg_agent.db import database; "
            "from fmg_agent.mail_runtime import set_runtime; "
            "engine,sessions=database(Settings()); "
            "set_runtime(sessions,dispatch_enabled=True,send_enabled=True); engine.dispose()",
        )
        port = (
            run("docker", "port", api, "8000/tcp")
            .stdout.decode()
            .strip()
            .split(":")[-1]
        )
        server = f"http://127.0.0.1:{port}"
        for attempt in range(40):
            try:
                with urllib.request.urlopen(
                    server + "/v1/health", timeout=1
                ) as response:
                    assert response.status == 200
                break
            except OSError:
                if attempt == 39:
                    raise
                time.sleep(0.25)
        config = tmp_path / "cli.json"
        config.write_text(json.dumps({"server": server, "token": token["token"]}))
        config.chmod(0o600)
        smoke = run(
            "sh",
            str(ROOT / "deploy/agent-services/smoke.sh"),
            server,
            env=dict(os.environ, FMG_CONFIG=str(config), FMG_BIN=str(ROOT / "cli/fmg")),
        )
        assert b"configuration smoke passed" in smoke.stdout
        # A private URL is rejected locally: proves actual queue processing without
        # a paid provider call or any public-site request.
        create_job = (
            "from fmg_agent.config import Settings; from fmg_agent.db import database; "
            "from fmg_agent.email.jobs import JobStore; "
            "engine,sessions=database(Settings()); "
            f'JobStore(sessions).create({token["id"]!r},"release-worker-test",{{"url":"http://127.0.0.1/private"}})'
        )
        run(*common, "--rm", image, "python", "-c", create_job)
        for attempt in range(80):
            with engine.connect() as conn:
                state = conn.scalar(text(f'SELECT state FROM "{schema}".email_jobs'))
            if state == "failed":
                break
            time.sleep(0.25)
        assert state == "failed"
        assert (
            run("docker", "inspect", "--format", "{{.Config.User}}", api).stdout.strip()
            == b"agent"
        )
        run("docker", "stop", "-t", "5", api, worker, dispatcher)
        dump = run(
            "docker",
            "exec",
            db_container,
            "pg_dump",
            "-U",
            "fmg_agent_test",
            "-d",
            "find_me_gamer_agent_test",
            "-Fc",
            "--no-owner",
            "--no-acl",
            "--schema",
            schema,
        ).stdout
        assert dump.startswith(b"PGDMP")
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        run(
            "docker",
            "exec",
            "-i",
            db_container,
            "pg_restore",
            "-U",
            "fmg_agent_test",
            "-d",
            "find_me_gamer_agent_test",
            "--no-owner",
            "--no-acl",
            input=dump,
        )
        with engine.connect() as conn:
            assert (
                conn.scalar(text(f'SELECT count(*) FROM "{schema}".access_tokens')) == 1
            )
            assert conn.scalar(text(f'SELECT count(*) FROM "{schema}".email_jobs')) == 1
            assert (
                conn.scalar(text(f'SELECT version_num FROM "{schema}".alembic_version'))
                == "0013_mail_runtime"
            )
    finally:
        try:
            for name in owned_containers:
                try:
                    cleanup = subprocess.run(
                        ["docker", "rm", "-f", name], capture_output=True, timeout=30
                    )
                    if (
                        cleanup.returncode
                        and b"No such container" not in cleanup.stderr
                    ):
                        warnings.warn(
                            f"Could not clean up owned container {name}: "
                            f"{cleanup.stderr.decode(errors='replace')}"
                        )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    # Continue attempting cleanup of all resources we own.
                    warnings.warn(f"Could not clean up owned container {name}: {exc}")
        finally:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            finally:
                engine.dispose()
