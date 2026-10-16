"""Confirmed nonexistent addresses are excluded, not sender-reputation failures."""

from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy import func, select

from test_email_sending import sending, headers, send
from test_email_templates import variables
from test_bounce_safety import accepted, configure_second_sender, dsn
from test_bounce_retry import advance, retry_row
from test_send_pacing_postgres import pg_sending


@pytest.fixture(params=["sending", "pg_sending"])
def mailbox(request):
    fixture = request.getfixturevalue(request.param)
    app, client, owner = fixture[:3]
    app.state.settings.email_send_interval_seconds = 0
    from fmg_agent.mailboxes import MailboxRegistry

    app.state.mailboxes = MailboxRegistry.load(app.state.settings)
    return app, client, owner


def retried(app, client, owner, monkeypatch, key):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry

    original = accepted(app, client, owner, key)
    ingest(
        app.state.sessions,
        "junk",
        "1",
        1,
        dsn(original, key + "-initial"),
        mailbox_id="ontologyplay",
    )
    advance(monkeypatch, retry_row(app, original).due_at)
    ids = []
    process_retry(
        app.state.sessions,
        original,
        app.state.settings,
        lambda cfg, msg, sid: ids.append(sid) or {"state": "sent"},
    )
    assert len(ids) == 1
    return original, ids[0]


@pytest.mark.parametrize("status", ["5.1.1", "5.1.3"])
def test_three_nonexistent_retry_addresses_do_not_pause_sender(
    mailbox, monkeypatch, status
):
    # Missing exclusion used to trip the global sender hold on the third address.
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.safety import status as sender_status

    app, client, owner = mailbox
    for i in range(3):
        original, child = retried(app, client, owner, monkeypatch, f"invalid-{i}")
        ingest(
            app.state.sessions,
            "inbox",
            "1",
            10 + i,
            dsn(
                child,
                f"invalid-final-{i}",
                status,
                "The email account that you tried to reach does not exist.",
            ),
            mailbox_id="ontologyplay",
        )
        assert retry_row(app, original).state == "failed"
    with app.state.sessions() as session:
        assert sender_status(session, "publisher@example.com")["state"] == "ready"


def test_mixed_failures_count_only_deliverable_addresses(mailbox, monkeypatch):
    from fmg_agent.email.inbox import ingest, EmailReply
    from fmg_agent.email.safety import status

    app, client, owner = mailbox
    for i, code in enumerate(["5.1.1", "5.1.3", "5.7.26", "5.7.520", "5.7.520"]):
        _, child = retried(app, client, owner, monkeypatch, f"mixed-{i}")
        ingest(
            app.state.sessions,
            "junk",
            "1",
            10 + i,
            dsn(
                child,
                f"mixed-final-{i}",
                code,
                (
                    "Mailbox nonexistent"
                    if i < 2
                    else "550 Authentication or spam rejection"
                ),
            ),
            mailbox_id="ontologyplay",
        )
        if i == 1:
            # Historical 5.1.3 records were classified as delivery_failure.
            with app.state.sessions() as session:
                reply = session.scalar(
                    select(EmailReply).where(EmailReply.send_id == child)
                )
                reply.diagnostics = {
                    **reply.diagnostics,
                    "category": "delivery_failure",
                }
                session.commit()
        with app.state.sessions() as session:
            assert status(session, "publisher@example.com")["state"] == (
                "paused" if i == 4 else "ready"
            )


def test_late_invalid_notice_cancels_queued_retry_without_transport(
    mailbox, monkeypatch
):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry, pending_retries
    from fmg_agent.email.models import EmailSend

    app, client, owner = mailbox
    original = accepted(app, client, owner, "late-invalid")
    ingest(
        app.state.sessions,
        "junk",
        "1",
        1,
        dsn(original, "initial-spam"),
        mailbox_id="ontologyplay",
    )
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        2,
        dsn(original, "late-invalid", "5.1.1", "550 no mailbox"),
        mailbox_id="ontologyplay",
    )
    advance(monkeypatch, retry_row(app, original).due_at)
    calls = []
    process_retry(
        app.state.sessions,
        original,
        app.state.settings,
        lambda *args: calls.append(args[-1]) or {"state": "sent"},
    )
    assert calls == []
    row = retry_row(app, original)
    assert row.state == "cancelled" and row.cancel_reason == "email_recipient_invalid"
    assert pending_retries(app.state.sessions) == []
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EmailSend)) == 1


def test_new_preview_for_known_invalid_address_is_skipped_idempotently(mailbox):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.models import EmailSend
    from fmg_agent.email.safety import status

    app, client, owner = mailbox
    original = accepted(app, client, owner, "known-invalid", to="gone@example.com")
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        1,
        dsn(original, "invalid", "5.1.1", "550 no mailbox"),
        mailbox_id="ontologyplay",
    )
    calls = []
    app.state.smtp_transport = lambda *args: calls.append(args[-1]) or {"state": "sent"}
    pid = client.post(
        "/v1/email/previews",
        headers=headers(owner),
        json={
            "template_id": "game-outreach",
            "template_version": "5",
            "variables": variables(),
            "to": "GONE@example.com",
        },
    ).json()["data"]["id"]
    result = send(client, owner, pid, key="excluded")
    assert result.status_code == 200
    receipt = result.json()["data"]
    assert receipt["state"] == "failed" and receipt["code"] == "email_recipient_invalid"
    assert receipt["diagnostics"]["transport_attempted"] is False
    assert (
        send(client, owner, pid, key="excluded").json()["data"]["id"] == receipt["id"]
    )
    assert calls == []
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EmailSend)) == 2
        assert status(session, "publisher@example.com")["state"] == "ready"
    # The exclusion is address-specific, not a sender-wide hold.
    assert accepted(app, client, owner, "still-valid", to="valid@example.com")


def test_nonexistent_address_status_is_classified_and_delay_is_not_failure():
    from fmg_agent.email.inbox import delivery_diagnostics

    for action, expected in [
        ("failed", "invalid_recipient"),
        ("delayed", "delivery_notice"),
    ]:
        message = BytesParser(policy=policy.default).parsebytes(
            dsn(
                "00000000-0000-0000-0000-000000000001",
                action,
                "5.1.3",
                "The email account that you tried to reach does not exist.",
                action,
            )
        )
        assert delivery_diagnostics(message)["category"] == expected


def test_invalid_address_exclusion_does_not_block_other_batch_recipients(mailbox):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.outreach import pending, process_recipient
    from test_outreach import create
    from test_bounce_safety import start

    app, client, owner = mailbox
    original = accepted(app, client, owner, "invalid-alice", to="alice@example.com")
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        1,
        dsn(original, "alice-invalid", "5.1.1", "550 no mailbox"),
        mailbox_id="ontologyplay",
    )
    task = create(app, client, owner).json()["data"]
    assert start(client, owner, task).status_code == 200
    calls = []
    for rid in pending(app.state.sessions):
        process_recipient(
            app.state.sessions,
            rid,
            app.state.settings,
            lambda cfg, msg, sid: calls.append(msg["to"]) or {"state": "sent"},
        )
    assert calls == ["bob@example.com"]
    result = client.get(
        "/v1/outreach/tasks/" + task["id"] + "?summary=true", headers=headers(owner)
    ).json()["data"]
    assert result["stats"]["pending"] == 0
    assert result["stats"]["sent"] == result["stats"]["failed"] == 1
    assert result["sender_safety"]["state"] == "ready"


def test_invalid_address_exclusion_is_sender_scoped(mailbox):
    from fmg_agent.email.inbox import ingest

    app, client, owner = mailbox
    original = accepted(app, client, owner, "first-sender", to="same@example.com")
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        1,
        dsn(original, "bad-first", "5.1.1", "550 no mailbox"),
        mailbox_id="ontologyplay",
    )
    configure_second_sender(app, "other-publisher@example.com")
    assert accepted(
        app, client, owner, "other-sender", to="same@example.com", mailbox_id="second"
    )


def test_delay_notice_does_not_exclude_recipient(mailbox):
    from fmg_agent.email.inbox import ingest

    app, client, owner = mailbox
    original = accepted(app, client, owner, "delayed-first", to="slow@example.com")
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        1,
        dsn(original, "delay-only", "5.1.3", "Delivery delayed", "delayed"),
        mailbox_id="ontologyplay",
    )
    assert accepted(app, client, owner, "delayed-second", to="slow@example.com")
