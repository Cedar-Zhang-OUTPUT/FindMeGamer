from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text

from test_email_sending import sending, preview, send
from test_send_pacing_postgres import pg_sending


def test_send_gate_blocks_api_and_worker(sending):
    from fmg_agent.mail_runtime import set_runtime
    from fmg_agent.outreach import process_recipient, OutreachTask
    from test_queue_isolation import seed_batches

    app, client, owner, _, _ = sending
    ids = seed_batches(app, client, owner)
    calls = []
    transport = lambda *args: calls.append(args) or {"state": "sent"}
    app.state.smtp_transport = transport
    from test_mailbox_delivery import draft

    pid = draft(client, owner, "alpha")
    set_runtime(app.state.sessions, dispatch_enabled=False, send_enabled=False)
    response = send(client, owner, pid)
    assert response.json()["error"]["code"] == "mail_service_maintenance"
    for rid in ids:
        result = process_recipient(
            app.state.sessions,
            rid,
            app.state.settings,
            transport,
            registry=app.state.mailboxes,
            expected_mailbox_id=ids[rid],
        )
        assert result == {
            "code": "mail_service_maintenance",
            "transport_attempted": False,
        }
    assert calls == []
    with app.state.sessions() as session:
        assert session.get(OutreachTask, "alpha").state == "sending"
        assert session.get(OutreachTask, "beta").revision == "r"
        assert session.scalar(text("SELECT count(*) FROM email_sends")) == 0


def test_missing_runtime_defaults_closed(sending):
    app, client, owner, _, _ = sending
    with app.state.sessions() as session:
        session.execute(text("DELETE FROM mail_runtime"))
        session.commit()
    pid = preview(client, owner).json()["data"]["id"]
    app.state.smtp_transport = lambda *args: pytest.fail("closed gate called transport")
    assert (
        send(client, owner, pid).json()["error"]["code"] == "mail_service_maintenance"
    )


def test_hold_preserves_due_retry(sending, monkeypatch):
    from fmg_agent.mail_runtime import set_runtime
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry
    from test_bounce_safety import accepted, dsn
    from test_bounce_retry import retry_row, advance

    app, client, owner, _, _ = sending
    sid = accepted(app, client, owner, "gate-retry")
    ingest(
        app.state.sessions, "junk", "1", 1, dsn(sid, "gate"), mailbox_id="ontologyplay"
    )
    retry = retry_row(app, sid)
    advance(monkeypatch, retry.due_at)
    set_runtime(app.state.sessions, dispatch_enabled=False, send_enabled=False)
    result = process_retry(
        app.state.sessions,
        sid,
        app.state.settings,
        lambda *args: pytest.fail("maintenance retry reached transport"),
        expected_mailbox_id="ontologyplay",
    )
    assert result == {"code": "mail_service_maintenance", "transport_attempted": False}
    assert retry_row(app, sid).state == "queued"
    with app.state.sessions() as session:
        assert session.scalar(text("SELECT count(*) FROM email_sends")) == 1


def test_runtime_migration_starts_closed(tmp_path):
    from test_migrations import migrate
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path / 'runtime.sqlite'}"
    result = migrate(url)
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT id, dispatch_enabled, send_enabled FROM mail_runtime")
        ).all() == [(1, 0, 0)]
    engine.dispose()


@pytest.mark.parametrize("change", ["oauth", "disabled", "template", "identity"])
def test_hold_precedes_configuration_preflight(sending, monkeypatch, tmp_path, change):
    from fmg_agent.mail_runtime import set_runtime
    from fmg_agent.mailboxes import MailboxRegistry
    from fmg_agent.outreach import process_recipient, OutreachTask, OutreachRecipient
    from fmg_agent.email.sending import SendStore
    from fmg_agent.email.retries import process_retry
    from fmg_agent.email.inbox import ingest
    from fmg_agent.errors import ApiError
    from test_queue_isolation import seed_batches
    from test_mailbox_delivery import draft
    from test_bounce_safety import dsn
    from test_bounce_retry import retry_row, advance

    app, client, owner, _, _ = sending
    seed_batches(app, client, owner)
    app.state.smtp_transport = lambda *args: {"state": "sent"}
    original = draft(client, owner, "alpha")
    sid = send(client, owner, original, key="original").json()["data"]["id"]
    ingest(
        app.state.sessions,
        "junk",
        "1",
        1,
        dsn(sid, "hold-preflight"),
        mailbox_id="alpha",
    )
    advance(monkeypatch, retry_row(app, sid).due_at)
    changes = {
        "oauth": {
            "email_transport": "microsoft_graph",
            "microsoft_client_id": "00000000-0000-0000-0000-000000000001",
            "microsoft_graph_token_store": tmp_path / "missing.json",
        },
        "disabled": {"enabled": False},
        "template": {"allowed_templates": []},
        "identity": {"smtp_from": "changed@example.com"},
    }
    profiles = list(app.state.mailboxes.profiles())
    profiles[0] = profiles[0].model_copy(update=changes[change])
    registry = MailboxRegistry(app.state.settings, profiles, legacy=False)
    app.state.mailboxes = registry
    set_runtime(app.state.sessions, dispatch_enabled=False, send_enabled=False)
    transport = lambda *args: pytest.fail("maintenance reached transport")
    app.state.smtp_transport = transport
    expected = {"code": "mail_service_maintenance", "transport_attempted": False}
    assert (
        process_recipient(
            app.state.sessions,
            "alpha-00",
            app.state.settings,
            transport,
            registry=registry,
            expected_mailbox_id="alpha",
        )
        == expected
    )
    assert (
        process_retry(
            app.state.sessions,
            sid,
            app.state.settings,
            transport,
            registry=registry,
            expected_mailbox_id="alpha",
        )
        == expected
    )
    assert retry_row(app, sid).state == "queued"
    with app.state.sessions() as session:
        assert session.get(OutreachTask, "alpha").state == "sending"
        assert session.get(OutreachTask, "alpha").revision == "r"
        pid = session.get(OutreachRecipient, "alpha-00").preview_id
        assert session.scalar(text("SELECT count(*) FROM email_sends")) == 1
    assert (
        send(client, owner, pid, key="held").json()["error"]["code"]
        == "mail_service_maintenance"
    )
    assert send(client, owner, original, key="original").json()["data"]["id"] == sid
    with pytest.raises(ApiError) as error:
        SendStore(app.state.sessions).send(
            owner.id,
            pid,
            "wrong-queue",
            app.state.settings,
            transport,
            registry=registry,
            expected_mailbox_id="beta",
        )
    assert error.value.code == "mailbox_queue_mismatch"


@pytest.mark.postgres
def test_readiness_rejects_missing_backfill(pg_sending):
    from fmg_agent.mail_runtime import check_readiness

    app, client, owner = pg_sending
    pid = preview(client, owner).json()["data"]["id"]
    check_readiness(app.state.settings, app.state.sessions)
    with app.state.sessions() as session:
        session.execute(
            text("UPDATE email_previews SET mailbox_id = NULL WHERE id = :id"),
            {"id": pid},
        )
        session.commit()
    with pytest.raises(RuntimeError, match="backfill"):
        check_readiness(app.state.settings, app.state.sessions)


@pytest.mark.postgres
def test_hold_drains_inflight_and_replay_remains_available(pg_sending):
    from fmg_agent.mail_runtime import set_runtime

    app, client, owner = pg_sending
    set_runtime(app.state.sessions, dispatch_enabled=True, send_enabled=True)
    entered, release, holding = Event(), Event(), Event()

    def transport(*args):
        entered.set()
        assert release.wait(10)
        return {"state": "sent"}

    app.state.smtp_transport = transport
    pid = preview(client, owner).json()["data"]["id"]
    other = preview(client, owner).json()["data"]["id"]

    def hold():
        holding.set()
        return set_runtime(
            app.state.sessions, dispatch_enabled=False, send_enabled=False
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(send, client, owner, pid)
        assert entered.wait(5)
        stopped = pool.submit(hold)
        assert holding.wait(5)
        try:
            assert not stopped.done()
            assert send(client, owner, pid).json()["data"]["state"] == "sending"
        finally:
            release.set()
        assert active.result().json()["data"]["state"] == "sent"
        assert stopped.result() == {"dispatch_enabled": False, "send_enabled": False}
    assert (
        send(client, owner, other, key="other").json()["error"]["code"]
        == "mail_service_maintenance"
    )
    assert send(client, owner, pid).json()["data"]["state"] == "sent"
