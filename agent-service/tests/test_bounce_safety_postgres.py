"""Migrated PostgreSQL circuit-breaker checks; simulated delivery only."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from test_send_pacing_postgres import pg_sending
from test_bounce_safety import accepted, dsn, start
from test_email_sending import preview, send, headers
from test_outreach import create


@pytest.mark.postgres
def test_concurrent_bounces_persist_hold_and_block_queued_sends(pg_sending):
    from fmg_agent.email.inbox import ingest, EmailReply
    from fmg_agent.email.safety import status
    from fmg_agent.outreach import pending, process_recipient

    app, client, owner = pg_sending
    app.state.settings.email_send_interval_seconds = 0
    task = create(app, client, owner).json()["data"]
    assert start(client, owner, task).status_code == 200
    queued = pending(app.state.sessions)
    ids = [accepted(app, client, owner, str(i)) for i in range(3)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda i: ingest(
                    app.state.sessions, "junk", "1", i, dsn(ids[i], str(i))
                ),
                range(3),
            )
        )
    assert results == ["bounce"] * 3
    with app.state.sessions() as session:
        assert len(session.scalars(select(EmailReply)).all()) == 3
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
