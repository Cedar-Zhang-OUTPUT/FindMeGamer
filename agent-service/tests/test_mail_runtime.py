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
