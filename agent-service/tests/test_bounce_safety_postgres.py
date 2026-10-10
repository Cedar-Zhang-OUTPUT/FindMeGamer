"""Migrated PostgreSQL circuit-breaker checks; simulated delivery only."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from test_send_pacing_postgres import pg_sending
from test_bounce_safety import accepted, dsn, start
from test_email_sending import preview, send, headers
from test_outreach import create


@pytest.mark.postgres
def test_concurrent_retry_bounces_persist_hold_and_block_queued_sends(
    pg_sending, monkeypatch
):
    from fmg_agent.email.inbox import ingest, EmailReply
    from fmg_agent.email.safety import status
    from fmg_agent.outreach import pending, process_recipient
    from fmg_agent.email.retries import process_retry
    from test_bounce_retry import retry_row, advance

    app, client, owner = pg_sending
    app.state.settings.email_send_interval_seconds = 0
    task = create(app, client, owner).json()["data"]
    assert start(client, owner, task).status_code == 200
    queued = pending(app.state.sessions)
    ids = [accepted(app, client, owner, str(i)) for i in range(3)]
    retry_ids = []
    for i, sid in enumerate(ids):
        ingest(app.state.sessions, "junk", "1", i, dsn(sid, f"initial-{i}"))
        advance(monkeypatch, retry_row(app, sid).due_at)
        process_retry(
            app.state.sessions,
            sid,
            app.state.settings,
            lambda cfg, msg, rid: retry_ids.append(rid) or {"state": "sent"},
        )
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda i: ingest(
                    app.state.sessions, "junk", "1", i + 10, dsn(retry_ids[i], str(i))
                ),
                range(3),
            )
        )
    assert results == ["bounce"] * 3
    with app.state.sessions() as session:
        assert len(session.scalars(select(EmailReply)).all()) == 6
        assert status(session, "publisher@example.com")["state"] == "paused"
    assert pending(app.state.sessions) == []
    for rid in queued:
        process_recipient(
            app.state.sessions,
            rid,
            app.state.settings,
            lambda *a: (_ for _ in ()).throw(AssertionError("must not send")),
        )
    target = preview(client, owner).json()["data"]["id"]
    assert (
        send(client, owner, target, key="blocked").json()["error"]["code"]
        == "email_sender_paused"
    )
    # The original idempotent receipt remains readable despite the persisted hold.
    assert (
        client.get("/v1/email/sends/" + ids[0], headers=headers(owner)).status_code
        == 200
    )


@pytest.mark.postgres
def test_concurrent_notice_and_retry_workers_make_one_child_and_one_send(
    pg_sending, monkeypatch
):
    from fmg_agent.email.inbox import ingest, EmailReply
    from fmg_agent.email.models import EmailSend, EmailBounceRetry
    from fmg_agent.email.retries import process_retry
    from test_bounce_retry import retry_row, advance
    from threading import Event

    app, client, owner = pg_sending
    app.state.settings.email_send_interval_seconds = 0
    sid = accepted(app, client, owner, "concurrent")
    with ThreadPoolExecutor(max_workers=4) as pool:
        notices = list(
            pool.map(
                lambda i: ingest(
                    app.state.sessions, "junk", "1", i, dsn(sid, f"notice-{i}")
                ),
                range(4),
            )
        )
    assert notices == ["bounce"] * 4
    with app.state.sessions() as session:
        assert len(session.scalars(select(EmailReply)).all()) == 4
        assert len(session.scalars(select(EmailBounceRetry)).all()) == 1
    advance(monkeypatch, retry_row(app, sid).due_at)
    entered, release = Event(), Event()
    delivered = []

    def transport(config, message, send_id):
        delivered.append(send_id)
        entered.set()
        assert release.wait(10)
        return {"state": "sent"}

    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(
            process_retry, app.state.sessions, sid, app.state.settings, transport
        )
        assert entered.wait(5)
        others = [
            pool.submit(
                process_retry, app.state.sessions, sid, app.state.settings, transport
            )
            for _ in range(3)
        ]
        for future in others:
            future.result(timeout=5)
        release.set()
        first.result(timeout=5)
    assert len(delivered) == 1
    with app.state.sessions() as session:
        assert len(session.scalars(select(EmailSend)).all()) == 2
    assert retry_row(app, sid).state == "sent"
