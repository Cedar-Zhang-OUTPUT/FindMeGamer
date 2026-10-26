"""Explicit RBL rejections stop sending without spending a retry."""

from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy import select, func

from test_email_sending import sending, headers, preview, send
from test_bounce_safety import accepted, dsn, start, configure_second_sender
from test_outreach import create

RBL = (
    "571 5.7.2 From domain example.com found on one or more RBLs "
    "(abusixdblblack). Refer to https://developers.cloudflare.com/email-routing/postmaster/"
)


@pytest.mark.parametrize("status", ["5.0.0", "5.7.2"])
@pytest.mark.parametrize(
    "diagnostic",
    [RBL, "554 IP listed by Spamhaus", "554 IP blocked by Abusix (abusixip)"],
)
def test_explicit_listing_classified_even_with_generic_status(status, diagnostic):
    from fmg_agent.email.inbox import delivery_diagnostics

    result = delivery_diagnostics(
        BytesParser(policy=policy.default).parsebytes(dsn("s", "r", status, diagnostic))
    )
    assert result["category"] == "spam_blocked"
    assert result["blocklisted"] is True


@pytest.mark.parametrize(
    "status,diagnostic,action",
    [
        ("4.7.0", RBL, "delayed"),
        ("5.0.0", "550 delivery failed; read our Spamhaus documentation", "failed"),
        ("5.1.1", "550 mailbox not found", "failed"),
        ("5.2.2", "552 mailbox full", "failed"),
    ],
)
def test_non_listing_or_delay_does_not_trigger_blocklist_hold(
    status, diagnostic, action
):
    from fmg_agent.email.inbox import delivery_diagnostics

    result = delivery_diagnostics(
        BytesParser(policy=policy.default).parsebytes(
            dsn("s", "r", status, diagnostic, action)
        )
    )
    assert not result.get("blocklisted")


def test_plain_reply_with_quoted_listing_is_not_a_dsn():
    from fmg_agent.email.inbox import delivery_diagnostics

    message = BytesParser(policy=policy.default).parsebytes(
        ("From: human@example.com\r\n\r\n" + RBL).encode()
    )
    assert delivery_diagnostics(message) is None


def test_listing_immediately_holds_pending_and_direct_sends_without_retry(sending):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.models import EmailBounceRetry, EmailSend
    from fmg_agent.outreach import pending, process_recipient

    app, client, owner, _, _ = sending
    task = create(app, client, owner).json()["data"]
    start(client, owner, task)
    queued = pending(app.state.sessions, mailbox_id="ontologyplay")
    sid = accepted(app, client, owner, "blocklist")
    assert (
        ingest(
            app.state.sessions,
            "inbox",
            "1",
            1,
            dsn(sid, "listing", "5.0.0", RBL),
            mailbox_id="ontologyplay",
        )
        == "bounce"
    )
    assert pending(app.state.sessions, mailbox_id="ontologyplay") == []
    result = client.get(
        "/v1/outreach/tasks/" + task["id"], headers=headers(owner)
    ).json()["data"]
    assert result["state"] == "blocked"
    assert result["stats"]["pending"] == 2
    assert result["sender_safety"]["reason"] == "outbound_spam_blocked"
    for rid in queued:
        process_recipient(
            app.state.sessions,
            rid,
            app.state.settings,
            lambda *args: pytest.fail("must not send"),
        )
    pid = preview(client, owner).json()["data"]["id"]
    assert (
        send(client, owner, pid, key="blocked").json()["error"]["code"]
        == "email_sender_paused"
    )
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EmailBounceRetry)) == 0
        assert session.scalar(select(func.count()).select_from(EmailSend)) == 1


def test_listing_cancels_already_queued_retry(sending):
    from fmg_agent.email.inbox import ingest
    from test_bounce_retry import retry_row

    app, client, owner, _, _ = sending
    sid = accepted(app, client, owner, "queued")
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        1,
        dsn(sid, "ordinary-spam"),
        mailbox_id="ontologyplay",
    )
    assert retry_row(app, sid).state == "queued"
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        2,
        dsn(sid, "listing", "5.0.0", RBL),
        mailbox_id="ontologyplay",
    )
    assert retry_row(app, sid).state == "cancelled"
    assert retry_row(app, sid).cancel_reason == "sender_blocklisted"


def test_listing_on_retry_holds_after_one_failure(sending, monkeypatch):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry
    from fmg_agent.email.safety import status
    from test_bounce_retry import retry_row, advance

    app, client, owner, _, _ = sending
    sid = accepted(app, client, owner, "retry-listing")
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        1,
        dsn(sid, "ordinary-spam"),
        mailbox_id="ontologyplay",
    )
    advance(monkeypatch, retry_row(app, sid).due_at)
    sent = []
    process_retry(
        app.state.sessions,
        sid,
        app.state.settings,
        lambda cfg, msg, rid: sent.append(rid) or {"state": "sent"},
    )
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        2,
        dsn(sent[0], "retry-listing", "5.0.0", RBL),
        mailbox_id="ontologyplay",
    )
    assert retry_row(app, sid).state == "failed"
    with app.state.sessions() as session:
        assert status(session, "publisher@example.com")["state"] == "paused"


def test_blocklist_guard_applies_to_second_mailbox(sending):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.safety import status

    app, client, owner, _, _ = sending
    configure_second_sender(app, "second@example.com")
    sid = accepted(app, client, owner, "second", mailbox_id="second")
    ingest(
        app.state.sessions,
        "inbox",
        "1",
        1,
        dsn(sid, "listing", "5.0.0", RBL),
        mailbox_id="second",
    )
    with app.state.sessions() as session:
        assert status(session, "second@example.com")["state"] == "paused"
        assert status(session, "publisher@example.com")["state"] == "ready"
