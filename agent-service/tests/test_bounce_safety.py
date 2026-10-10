from email import policy
from email.parser import BytesParser

from pydantic import SecretStr
from sqlalchemy import select

from test_email_sending import sending, headers, preview, send
from test_outreach import create


def start(client, owner, task):
    return client.post(
        "/v1/outreach/tasks/" + task["id"] + "/start",
        headers=headers(owner),
        json={"confirm": True, "revision": task["revision"]},
    )


def dsn(
    send_id,
    identity,
    status="5.7.520",
    diagnostic="550 5.7.520 Message blocked because it contains content identified as spam. AS(4810)",
    action="failed",
):
    return (
        f"From: postmaster@outlook.com\r\nMessage-ID: <{identity}@outlook.com>\r\n"
        'Content-Type: multipart/report; report-type=delivery-status; boundary="dsn"\r\n\r\n'
        "--dsn\r\nContent-Type: text/plain\r\n\r\nDelivery notification\r\n"
        "--dsn\r\nContent-Type: message/delivery-status\r\n\r\nReporting-MTA: dns; outlook.com\r\n\r\n"
        f"Action: {action}\r\nStatus: {status}\r\nDiagnostic-Code: smtp;{diagnostic}\r\n\r\n"
        "--dsn\r\nContent-Type: message/rfc822\r\n\r\n"
        f"Message-ID: <fmg-{send_id}@example.com>\r\n\r\n--dsn--\r\n"
    ).encode()


def accepted(app, client, owner, key, to=None):
    from test_email_templates import variables

    app.state.smtp_transport = lambda *args: {"state": "sent", "code": None}
    pid = client.post(
        "/v1/email/previews",
        headers=headers(owner),
        json={
            "template_id": "game-outreach",
            "template_version": "5",
            "variables": variables(),
            "to": to or f"creator-{key}@example.com",
        },
    ).json()["data"]["id"]
    return send(client, owner, pid, key=key).json()["data"]["id"]


def test_three_distinct_retry_bounces_pause_sender_and_keep_receipts(
    sending, monkeypatch
):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.outreach import pending, process_recipient
    from fmg_agent.email.models import EmailSend
    from fmg_agent.email.retries import process_retry
    from test_bounce_retry import retry_row, advance

    app, client, owner, other, _ = sending
    task = create(app, client, owner).json()["data"]
    other_task = create(app, client, other, "other").json()["data"]
    assert start(client, owner, task).status_code == 200
    assert start(client, other, other_task).status_code == 200
    queued = pending(app.state.sessions)
    ids = [accepted(app, client, owner, str(i)) for i in range(3)]
    for i, sid in enumerate(ids[:2]):
        assert ingest(app.state.sessions, "junk", "1", i, dsn(sid, str(i))) == "bounce"
    # Duplicate notices for the same original send must not trip the threshold.
    ingest(app.state.sessions, "junk", "1", 8, dsn(ids[0], "another-notice"))
    assert len(pending(app.state.sessions)) == 4
    ingest(app.state.sessions, "junk", "1", 9, dsn(ids[2], "third"))
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
        ingest(
            app.state.sessions, "junk", "1", i + 10, dsn(retry_ids[-1], f"retry-{i}")
        )
    assert pending(app.state.sessions) == []
    for item, token in ((task, owner), (other_task, other)):
        result = client.get(
            "/v1/outreach/tasks/" + item["id"], headers=headers(token)
        ).json()["data"]
        assert result["state"] == "blocked"
        assert result["stats"]["pending"] == 2
        assert result["sender_safety"]["reason"] == "outbound_spam_blocked"
        assert (
            start(client, token, item).json()["error"]["code"] == "email_sender_paused"
        )
    # Already queued workers cannot reach the transport; direct sends cannot bypass it.
    for rid in queued:
        process_recipient(
            app.state.sessions,
            rid,
            app.state.settings,
            lambda *args: (_ for _ in ()).throw(AssertionError("must not send")),
        )
    pid = preview(client, owner).json()["data"]["id"]
    assert (
        send(client, owner, pid, key="blocked").json()["error"]["code"]
        == "email_sender_paused"
    )
    with app.state.sessions() as session:
        assert len(session.scalars(select(EmailSend)).all()) == 6
    assert (
        client.get("/v1/email/sends/" + ids[0], headers=headers(owner)).json()["data"][
            "state"
        ]
        == "sent"
    )


def test_non_spam_failures_and_delays_do_not_pause_and_have_diagnostics(sending):
    from fmg_agent.email.inbox import ingest, EmailReply

    app, client, owner, _, _ = sending
    task = create(app, client, owner).json()["data"]
    start(client, owner, task)
    sid = accepted(app, client, owner, "one")
    for i in range(3):
        assert (
            ingest(
                app.state.sessions,
                "junk",
                "1",
                i,
                dsn(sid, str(i), "5.1.1", "550 mailbox does not exist"),
            )
            == "bounce"
        )
    assert (
        ingest(
            app.state.sessions,
            "junk",
            "1",
            4,
            dsn(sid, "delay", "4.7.0", "delivery delayed", "delayed"),
        )
        == "automatic"
    )
    result = client.get(
        "/v1/outreach/tasks/" + task["id"], headers=headers(owner)
    ).json()["data"]
    assert result["state"] == "sending"
    with app.state.sessions() as session:
        row = session.scalars(
            select(EmailReply).where(EmailReply.kind == "bounce")
        ).first()
        assert row.diagnostics["category"] == "invalid_recipient"
        assert row.diagnostics["status"] == "5.1.1"


def test_sync_discovers_junk_with_independent_cursor_and_deduplicates(sending):
    from fmg_agent.email.inbox import sync_once, monitoring_status, EmailReply

    app, client, owner, _, _ = sending
    sid = accepted(app, client, owner, "one")
    raw = dsn(sid, "junk-report")
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    top = raw.split(b"\r\n\r\n", 1)[0]
    sections = {"HEADER": top}
    for i, child in enumerate(msg.iter_parts(), 1):
        data = child.as_bytes(policy=policy.SMTP)
        head, body = data.split(b"\r\n\r\n", 1)
        sections[f"{i}.MIME"] = head
        sections[f"{i}.HEADER" if i == 3 else str(i)] = body
    cfg = app.state.settings.model_copy(
        update={
            "imap_host": "imap.example.com",
            "imap_username": "publisher@example.com",
            "imap_password": SecretStr("secret"),
        }
    )

    class Mailbox:
        def login(self, *args):
            pass

        def list(self):
            return "OK", [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\Junk) "/" "Junk"',
                b'(\\Sent) "/" "Sent"',
            ]

        def select(self, folder, readonly):
            assert readonly is True
            self.folder = folder.strip('"')
            assert self.folder in {"INBOX", "Junk"}
            return "OK", [b"1"]

        def response(self, key):
            return key, [b"22" if self.folder == "Junk" else b"11"]

        def uid(self, command, *args):
            if command == "search":
                return "OK", [b"1"]
            section = args[1].split("[")[1].split("]")[0]
            assert "BODY.PEEK[" in args[1]
            return "OK", (
                [(b"fetch", sections[section])] if section in sections else [b"NIL"]
            )

        def logout(self):
            pass

    result = sync_once(app.state.sessions, cfg, lambda *a, **kw: Mailbox())
    assert result["processed"] == 2
    assert result["folders"] == ["INBOX", "Junk"]
    assert monitoring_status(app.state.sessions, cfg)["state"] == "active"
    assert (
        sync_once(app.state.sessions, cfg, lambda *a, **kw: Mailbox())["processed"] == 0
    )
    with app.state.sessions() as session:
        rows = session.scalars(select(EmailReply)).all()
        assert len(rows) == 1 and rows[0].diagnostics["category"] == "spam_blocked"


def test_graph_message_limit_pauses_sender_without_retrying(sending):
    from fmg_agent.outreach import pending, process_recipient

    app, client, owner, _, _ = sending
    task = create(app, client, owner).json()["data"]
    start(client, owner, task)
    queued = pending(app.state.sessions)
    calls = []

    def rejected(*args):
        calls.append(1)
        return {
            "state": "failed",
            "code": "graph_rate_limited",
            "diagnostics": {
                "http_status": 429,
                "provider_code": "ErrorExceededMessageLimit",
            },
        }

    for rid in queued:
        process_recipient(app.state.sessions, rid, app.state.settings, rejected)
    assert len(calls) == 1
    result = client.get(
        "/v1/outreach/tasks/" + task["id"], headers=headers(owner)
    ).json()["data"]
    assert result["state"] == "blocked"
    assert result["stats"]["failed"] == 1 and result["stats"]["pending"] == 1


def test_old_retry_failures_do_not_trip_and_other_sender_remains_available(
    sending, monkeypatch
):
    from datetime import datetime, timedelta, timezone
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.models import EmailBounceRetry
    from fmg_agent.email.retries import process_retry
    from fmg_agent.email.safety import status
    from test_bounce_retry import retry_row, advance

    app, client, owner, _, _ = sending
    first = accepted(app, client, owner, "old")
    ingest(app.state.sessions, "junk", "1", 1, dsn(first, "old"))
    advance(monkeypatch, retry_row(app, first).due_at)
    process_retry(
        app.state.sessions,
        first,
        app.state.settings,
        lambda *args: {"state": "failed", "code": "smtp_request_rejected"},
    )
    with app.state.sessions() as session:
        row = session.get(EmailBounceRetry, first)
        row.failed_at = datetime.now(timezone.utc) - timedelta(minutes=16)
        session.commit()
    for i in range(2):
        sid = accepted(app, client, owner, f"recent-{i}")
        ingest(app.state.sessions, "junk", "1", i + 2, dsn(sid, f"recent-{i}"))
        advance(monkeypatch, retry_row(app, sid).due_at)
        process_retry(
            app.state.sessions,
            sid,
            app.state.settings,
            lambda *args: {"state": "failed", "code": "smtp_request_rejected"},
        )
    with app.state.sessions() as session:
        assert status(session, "publisher@example.com")["state"] == "ready"
    # Only an additional third recent recipient crosses the threshold.
    sid = accepted(app, client, owner, "third")
    ingest(app.state.sessions, "junk", "1", 4, dsn(sid, "third"))
    advance(monkeypatch, retry_row(app, sid).due_at)
    process_retry(
        app.state.sessions,
        sid,
        app.state.settings,
        lambda *args: {"state": "failed", "code": "smtp_request_rejected"},
    )
    app.state.settings.smtp_from = "different@example.com"
    assert accepted(app, client, owner, "other-sender")
    with app.state.sessions() as session:
        assert status(session, "PUBLISHER@example.com")["state"] == "paused"
        assert status(session, "different@example.com")["state"] == "ready"


def test_same_recipient_different_sends_does_not_inflate_spam_count(sending):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.safety import status

    app, client, owner, _, _ = sending
    for i in range(3):
        sid = accepted(app, client, owner, str(i), to="same@example.com")
        # The send key must differ even though the recipient is the same.
        ingest(app.state.sessions, "junk", "1", i, dsn(sid, f"repeat-{i}"))
    with app.state.sessions() as session:
        assert status(session, "publisher@example.com")["state"] == "ready"


def test_junk_failure_is_not_reported_as_healthy(sending):
    from fmg_agent.email.inbox import (
        sync_once,
        monitoring_status,
        InboxCursor,
        mailbox_key,
    )

    app, *_ = sending
    cfg = app.state.settings.model_copy(
        update={
            "imap_host": "imap.example.com",
            "imap_username": "publisher@example.com",
            "imap_password": SecretStr("private"),
        }
    )

    class Mailbox:
        def login(self, *args):
            pass

        def list(self):
            return "OK", [b'(\\Junk) "/" "Junk"']

        def select(self, folder, readonly):
            return ("NO" if folder == '"Junk"' else "OK"), [b"0"]

        def response(self, key):
            return key, [b"1"]

        def uid(self, *args):
            return "OK", [b""]

        def logout(self):
            pass

    assert (
        sync_once(app.state.sessions, cfg, lambda *a, **kw: Mailbox())["state"]
        == "error"
    )
    assert monitoring_status(app.state.sessions, cfg)["state"] == "error"
    with app.state.sessions() as session:
        assert session.get(InboxCursor, mailbox_key(cfg, "Junk")).last_uid == 0


def test_human_reply_with_attached_old_dsn_does_not_pause(sending):
    from email.message import EmailMessage
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.safety import status

    app, client, owner, _, _ = sending
    for i in range(3):
        sid = accepted(app, client, owner, str(i))
        reply = EmailMessage()
        reply["From"] = f"creator-{i}@example.com"
        reply["Message-ID"] = f"<human-{i}@example.com>"
        reply["In-Reply-To"] = f"<fmg-{sid}@example.com>"
        reply.set_content("Yes, interested. Attached an old delivery report.")
        report = BytesParser(policy=policy.default).parsebytes(dsn(sid, str(i)))
        reply.add_attachment(report, filename="old-dsn.eml")
        assert ingest(app.state.sessions, "inbox", "1", i, reply.as_bytes()) == "human"
    with app.state.sessions() as session:
        assert status(session, "publisher@example.com")["state"] == "ready"
