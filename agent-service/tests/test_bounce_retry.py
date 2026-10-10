"""Confirmed DSNs may authorize one durable resend; acceptance is not delivery."""

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
from sqlalchemy import select, func

from test_email_sending import sending, headers
from test_bounce_safety import accepted, dsn, start
from test_outreach import create


def test_rollout_migration_preserves_existing_sender_hold(tmp_path):
    from test_migrations import migrate
    from sqlalchemy import create_engine, text

    url = f"sqlite:///{tmp_path / 'rollout.sqlite'}"
    assert migrate(url, revision="0010_bounce_safety").returncode == 0
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO email_sender_safety (sender, reason, paused_at) "
                "VALUES ('publisher@example.com', 'outbound_spam_blocked', '2026-10-10 10:00:00')"
            )
        )
    migrated = migrate(url)
    assert migrated.returncode == 0, migrated.stderr
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT reason, paused_at, retry_enabled_at FROM email_sender_safety")
        ).one()
        assert row.reason == "outbound_spam_blocked"
        assert str(row.paused_at).startswith("2026-10-10 10:00:00")
        assert row.retry_enabled_at is not None
        assert connection.scalar(text("SELECT count(*) FROM email_bounce_retries")) == 0
    engine.dispose()


def retry_row(app, sid):
    from fmg_agent.email.models import EmailBounceRetry

    with app.state.sessions() as session:
        return session.get(EmailBounceRetry, sid)


def advance(monkeypatch, when):
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    monkeypatch.setattr("fmg_agent.email.retries.utcnow", lambda: when)


def test_first_bounce_waits_30_seconds_and_resends_exact_snapshot_once(
    sending, monkeypatch
):
    # Catches early dispatch, altered payloads, and duplicate dispatcher delivery.
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.models import EmailPreview, EmailSend
    from fmg_agent.email.retries import pending_retries, process_retry
    from fmg_agent.email.safety import status

    app, client, owner, _, _ = sending
    sid = accepted(app, client, owner, "first")
    before = datetime.now(timezone.utc)
    assert ingest(app.state.sessions, "junk", "1", 1, dsn(sid, "one")) == "bounce"
    row = retry_row(app, sid)
    due = row.due_at.replace(tzinfo=timezone.utc)
    assert (
        before + timedelta(seconds=30)
        <= due
        <= datetime.now(timezone.utc) + timedelta(seconds=30)
    )
    assert pending_retries(app.state.sessions) == []
    delivered = []

    def transport(config, message, send_id):
        delivered.append((message, send_id))
        return {"state": "sent"}

    advance(monkeypatch, due - timedelta(seconds=1))
    process_retry(app.state.sessions, sid, app.state.settings, transport)
    assert delivered == []
    advance(monkeypatch, due)
    assert pending_retries(app.state.sessions) == [sid]
    process_retry(app.state.sessions, sid, app.state.settings, transport)
    process_retry(app.state.sessions, sid, app.state.settings, transport)
    with app.state.sessions() as session:
        original = session.get(EmailSend, sid)
        original_message = session.get(EmailPreview, original.preview_id).message
        assert len(delivered) == 1 and delivered[0][0] == original_message
        assert delivered[0][1] != sid
        assert session.scalar(select(func.count()).select_from(EmailSend)) == 2
        assert status(session, "publisher@example.com")["state"] == "ready"
    assert retry_row(app, sid).state == "sent"
    assert pending_retries(app.state.sessions) == []
    # The first receipt remains immutable; retry details are additionally queryable.
    receipt = client.get("/v1/email/sends/" + sid, headers=headers(owner)).json()[
        "data"
    ]
    assert receipt["state"] == "sent"
    assert receipt["bounce_retry"]["send_id"] == delivered[0][1]
    assert receipt["bounce_retry"]["state"] == "sent"
    assert ingest(app.state.sessions, "inbox", "1", 2, dsn(sid, "one")) == "duplicate"
    ingest(app.state.sessions, "junk", "1", 3, dsn(sid, "another-original-notice"))
    assert retry_row(app, sid).due_at == row.due_at
    assert pending_retries(app.state.sessions) == []


def test_only_three_distinct_retry_failures_pause_and_never_retry_the_retry(
    sending, monkeypatch
):
    # Catches counting initial bounces, copies, or retry transport acceptance as failures.
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry, pending_retries
    from fmg_agent.email.models import EmailSend, EmailBounceRetry
    from fmg_agent.email.safety import status
    from fmg_agent.outreach import pending

    app, client, owner, other, _ = sending
    tasks = [
        create(app, client, token, token.id).json()["data"] for token in (owner, other)
    ]
    for task, token in zip(tasks, (owner, other)):
        assert start(client, token, task).status_code == 200
    ids = [accepted(app, client, owner, f"initial-{i}") for i in range(3)]
    for i, sid in enumerate(ids):
        ingest(app.state.sessions, "junk", "1", i, dsn(sid, f"initial-{i}"))
    with app.state.sessions() as session:
        assert status(session, "publisher@example.com")["state"] == "ready"
    assert len(pending(app.state.sessions)) == 4
    retry_ids = []
    for i, sid in enumerate(ids):
        advance(monkeypatch, retry_row(app, sid).due_at)
        process_retry(
            app.state.sessions,
            sid,
            app.state.settings,
            lambda cfg, msg, rid: retry_ids.append(rid) or {"state": "sent"},
        )
        with app.state.sessions() as session:
            assert status(session, "publisher@example.com")["state"] == "ready"
        ingest(
            app.state.sessions, "junk", "1", i + 10, dsn(retry_ids[-1], f"retry-{i}")
        )
        if i < 2:
            with app.state.sessions() as session:
                assert status(session, "publisher@example.com")["state"] == "ready"
        # Distinct notifications for one retried email do not increase the threshold.
        ingest(
            app.state.sessions, "inbox", "1", i + 20, dsn(retry_ids[-1], f"copy-{i}")
        )
    with app.state.sessions() as session:
        assert (
            status(session, "publisher@example.com")["reason"]
            == "outbound_spam_blocked"
        )
        assert session.scalar(select(func.count()).select_from(EmailBounceRetry)) == 3
        assert session.scalar(select(func.count()).select_from(EmailSend)) == 6
    assert pending_retries(app.state.sessions) == []
    assert pending(app.state.sessions) == []
    for task, token in zip(tasks, (owner, other)):
        data = client.get(
            "/v1/outreach/tasks/" + task["id"], headers=headers(token)
        ).json()["data"]
        assert data["state"] == "blocked" and data["stats"]["pending"] == 2


@pytest.mark.parametrize(
    "outcome",
    [
        {"state": "unknown", "code": "graph_confirmation_lost"},
        {"state": "failed", "code": "smtp_request_rejected"},
        {"state": "failed", "code": "graph_rate_limited"},
    ],
)
def test_retry_outcomes_preserve_unknown_and_provider_limit(
    sending, monkeypatch, outcome
):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry, pending_retries
    from fmg_agent.email.safety import status

    app, client, owner, _, _ = sending
    calls = []
    for i in range(3):
        sid = accepted(app, client, owner, f"outcome-{i}")
        ingest(app.state.sessions, "junk", "1", i, dsn(sid, f"outcome-{i}"))
        advance(monkeypatch, retry_row(app, sid).due_at)
        process_retry(
            app.state.sessions,
            sid,
            app.state.settings,
            lambda *args: calls.append(args[-1]) or outcome,
        )
        process_retry(
            app.state.sessions,
            sid,
            app.state.settings,
            lambda *args: pytest.fail("must not retry a retry"),
        )
        if outcome["code"] == "graph_rate_limited":
            break
    with app.state.sessions() as session:
        state = status(session, "publisher@example.com")
    if outcome["state"] == "unknown":
        assert state["state"] == "ready"
        assert retry_row(app, sid).failed_at is None
    elif outcome["code"] == "graph_rate_limited":
        assert state["reason"] == "provider_rate_limited" and len(calls) == 1
    else:
        assert state["reason"] == "outbound_spam_blocked" and len(calls) == 3
    assert pending_retries(app.state.sessions) == []


def test_invalid_old_and_human_replies_do_not_resend(sending, monkeypatch):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.models import EmailSend
    from fmg_agent.email.retries import process_retry, pending_retries
    from fmg_agent.email.safety import SenderSafety

    app, client, owner, _, _ = sending
    invalid = accepted(app, client, owner, "invalid")
    ingest(
        app.state.sessions,
        "junk",
        "1",
        1,
        dsn(invalid, "invalid", "5.1.1", "550 no mailbox"),
    )
    assert retry_row(app, invalid) is None
    old = accepted(app, client, owner, "old")
    with app.state.sessions() as session:
        safety = session.get(SenderSafety, "publisher@example.com")
        session.get(EmailSend, old).created_at = safety.retry_enabled_at - timedelta(
            days=1
        )
        session.commit()
    ingest(app.state.sessions, "junk", "1", 2, dsn(old, "old"))
    assert retry_row(app, old) is None
    sid = accepted(app, client, owner, "human")
    ingest(app.state.sessions, "junk", "1", 3, dsn(sid, "human-bounce"))
    reply = EmailMessage()
    reply["From"] = "creator-human@example.com"
    reply["In-Reply-To"] = f"<fmg-{sid}@example.com>"
    reply["Message-ID"] = "<human@example.com>"
    reply.set_content("Received your invitation, thanks.")
    assert ingest(app.state.sessions, "inbox", "1", 4, reply.as_bytes()) == "human"
    advance(monkeypatch, retry_row(app, sid).due_at)
    process_retry(
        app.state.sessions,
        sid,
        app.state.settings,
        lambda *args: pytest.fail("must not resend after a human reply"),
    )
    assert retry_row(app, sid).state == "cancelled"
    assert pending_retries(app.state.sessions) == []


def test_approved_batch_retry_visible_but_blocked_batch_never_resends(
    sending, monkeypatch
):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry
    from fmg_agent.outreach import process_recipient, OutreachTask

    app, client, owner, _, _ = sending
    task = create(app, client, owner).json()["data"]
    start(client, owner, task)
    rid = task["recipients"][0]["id"]
    ids = []
    process_recipient(
        app.state.sessions,
        rid,
        app.state.settings,
        lambda cfg, msg, sid: ids.append(sid) or {"state": "sent"},
    )
    ingest(app.state.sessions, "junk", "1", 1, dsn(ids[0], "batch"))
    data = client.get(
        "/v1/outreach/tasks/" + task["id"], headers=headers(owner)
    ).json()["data"]
    recipient = next(r for r in data["recipients"] if r["id"] == rid)
    assert recipient["bounce_retry"]["state"] == "queued"
    advance(monkeypatch, retry_row(app, ids[0]).due_at)
    with app.state.sessions() as session:
        session.get(OutreachTask, task["id"]).state = "blocked"
        session.commit()
    process_retry(
        app.state.sessions,
        ids[0],
        app.state.settings,
        lambda *args: pytest.fail("paused task must not resend"),
    )
    assert retry_row(app, ids[0]).state == "queued"
    assert start(client, owner, task).status_code == 200
    process_retry(
        app.state.sessions,
        ids[0],
        app.state.settings,
        lambda cfg, msg, sid: ids.append(sid) or {"state": "sent"},
    )
    ingest(app.state.sessions, "junk", "1", 2, dsn(ids[1], "batch-retry"))
    data = client.get(
        "/v1/outreach/tasks/" + task["id"], headers=headers(owner)
    ).json()["data"]
    recipient = next(r for r in data["recipients"] if r["id"] == rid)
    assert recipient["bounce_retry"]["state"] == "failed"
    assert recipient["reply_state"] == "bounced"
    assert len(recipient["replies"]) == 2
    assert data["stats"]["retry_failed"] == 1


def test_retry_unknown_after_restart_never_sends_again(sending, monkeypatch):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry, pending_retries
    from fmg_agent.email.models import EmailSend, EmailBounceRetry
    from fmg_agent.email.sending import SendStore

    app, client, owner, _, _ = sending
    sid = accepted(app, client, owner, "crash")
    ingest(app.state.sessions, "junk", "1", 1, dsn(sid, "crash"))
    row = retry_row(app, sid)
    with app.state.sessions() as session:
        session.add(
            EmailSend(
                token_id=owner.id,
                preview_id=row.preview_id,
                idempotency_key="bounce-retry:" + sid,
                state="sending",
                updated_at=datetime.now(timezone.utc) - timedelta(minutes=6),
            )
        )
        session.get(EmailBounceRetry, sid).state = "sending"
        session.commit()
    SendStore(app.state.sessions).recover_interrupted()
    assert retry_row(app, sid).state == "unknown"
    assert retry_row(app, sid).failed_at is None
    advance(monkeypatch, row.due_at + timedelta(days=1))
    assert pending_retries(app.state.sessions) == []
    process_retry(
        app.state.sessions,
        sid,
        app.state.settings,
        lambda *args: pytest.fail("uncertain reserved resend must not repeat"),
    )


def test_revoked_authorization_cancels_retry_without_transport(sending, monkeypatch):
    from fmg_agent.auth import revoke_token
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry

    app, client, owner, _, _ = sending
    sid = accepted(app, client, owner, "revoked")
    ingest(app.state.sessions, "junk", "1", 1, dsn(sid, "revoked"))
    advance(monkeypatch, retry_row(app, sid).due_at)
    with app.state.sessions() as session:
        revoke_token(session, owner.id)
    process_retry(
        app.state.sessions,
        sid,
        app.state.settings,
        lambda *args: pytest.fail("revoked access must not resend"),
    )
    assert retry_row(app, sid).state == "cancelled"
    assert retry_row(app, sid).cancel_reason == "bounce_retry_access_revoked"


def test_retry_respects_global_cooldown_and_dsn_during_transport(sending, monkeypatch):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry
    from fmg_agent.email.models import EmailSendGate

    app, client, owner, _, _ = sending
    app.state.settings.email_send_interval_seconds = 5
    sid = accepted(app, client, owner, "pacing")
    ingest(app.state.sessions, "junk", "1", 1, dsn(sid, "pacing"))
    advance(monkeypatch, retry_row(app, sid).due_at)
    with app.state.sessions() as session:
        session.get(EmailSendGate, "publisher@example.com").available_at = datetime.now(
            timezone.utc
        ) + timedelta(seconds=10)
        session.commit()
    process_retry(
        app.state.sessions,
        sid,
        app.state.settings,
        lambda *args: pytest.fail("retry bypassed the shared cooldown"),
    )
    assert retry_row(app, sid).state == "queued"
    with app.state.sessions() as session:
        session.get(EmailSendGate, "publisher@example.com").available_at = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
        session.commit()

    def bounced_while_sending(config, message, retry_id):
        ingest(app.state.sessions, "junk", "1", 2, dsn(retry_id, "inflight-dsn"))
        return {"state": "sent"}

    process_retry(app.state.sessions, sid, app.state.settings, bounced_while_sending)
    assert retry_row(app, sid).state == "failed"
    assert retry_row(app, sid).failed_at is not None
