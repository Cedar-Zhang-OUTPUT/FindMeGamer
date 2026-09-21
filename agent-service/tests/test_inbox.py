from email.message import EmailMessage
from email import policy
from email.parser import BytesParser
from test_email_sending import sending, headers
from test_email_templates import variables
from test_smtp_delivery import smtp_server, configuration


def sent_task(sending):
    app, client, owner, _, _ = sending
    task = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "inbox-test"),
        json={
            "name": "Inbox test",
            "template_id": "game-outreach",
            "template_version": "4",
            "recipients": [
                {"creator_id": n, "to": n + "@example.com", "variables": variables()}
                for n in ("alice", "bob")
            ],
        },
    ).json()["data"]
    client.post(
        "/v1/outreach/tasks/" + task["id"] + "/start",
        headers=headers(owner),
        json={"confirm": True, "revision": task["revision"]},
    )
    from fmg_agent.outreach import pending, process_recipient

    for rid in pending(app.state.sessions):
        process_recipient(
            app.state.sessions,
            rid,
            app.state.settings,
            lambda *a: {"state": "sent", "code": None},
        )
    return task


def test_plain_text_fallback_and_no_response_endpoint(sending, tmp_path, smtp_server):
    from fmg_agent.email.templates import get_template, render_template
    from fmg_agent.email.smtp import deliver

    m = render_template(get_template("game-outreach"), variables())
    assert m["format"] == "signature_image" and "choice=yes" not in m["text"]
    m.update({"from": "publisher@example.com", "to": "alice@example.com"})
    assert deliver(configuration(tmp_path, smtp_server), m, "test")["state"] == "sent"
    parsed = BytesParser(policy=policy.default).parsebytes(smtp_server.messages[0])
    assert parsed.is_multipart()
    assert m["text"] in parsed.get_body(preferencelist=("plain",)).get_content().replace("\r\n", "\n")
    app, client, owner, _, _ = sending
    task = sent_task(sending)
    assert "Yes:" not in task["recipients"][0]["message"]["text"]
    assert client.get("/v1/outreach/respond/old?choice=yes").status_code == 404


def test_real_replies_isolated_deduplicated_and_auto_excluded(sending):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.models import EmailSend, EmailPreview
    from sqlalchemy import select

    app, client, owner, other, _ = sending
    task = sent_task(sending)
    with app.state.sessions() as session:
        pairs = session.execute(
            select(EmailSend, EmailPreview).join(EmailPreview)
        ).all()
        send, preview = next(
            (s, p) for s, p in pairs if p.message["to"] == "alice@example.com"
        )
    original = f'<fmg-{send.id}@{preview.message["from"].split("@")[1]}>'
    mail = EmailMessage()
    mail["From"] = "Alice <alice@example.com>"
    mail["To"] = preview.message["from"]
    mail["Message-ID"] = "<reply-1@example.com>"
    mail["In-Reply-To"] = original
    mail["Subject"] = "Re: Game"
    mail.set_content("Please send more information.")
    assert ingest(app.state.sessions, "box", "1", 1, mail.as_bytes()) == "human"
    assert ingest(app.state.sessions, "box", "1", 1, mail.as_bytes()) == "duplicate"
    assert ingest(app.state.sessions, "box", "1", 2, mail.as_bytes()) == "duplicate"
    mail.replace_header("Message-ID", "<auto-1@example.com>")
    mail["Auto-Submitted"] = "auto-replied"
    assert ingest(app.state.sessions, "box", "1", 3, mail.as_bytes()) == "automatic"
    result = client.get(
        "/v1/outreach/tasks/" + task["id"], headers=headers(owner)
    ).json()["data"]
    alice = next(r for r in result["recipients"] if r["creator_id"] == "alice")
    bob = next(r for r in result["recipients"] if r["creator_id"] == "bob")
    assert alice["reply_state"] == "replied" and len(alice["replies"]) == 2
    assert bob["reply_state"] == "no_reply" and bob["replies"] == []
    assert result["stats"]["reply_rate"] == 0.5 and "yes" not in result["stats"]
    assert (
        client.get(
            "/v1/outreach/tasks/" + task["id"], headers=headers(other)
        ).status_code
        == 404
    )


def test_unrelated_or_wrong_sender_not_assigned(sending):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.models import EmailSend, EmailPreview
    from sqlalchemy import select

    app, _, _, _, _ = sending
    sent_task(sending)
    with app.state.sessions() as session:
        send, preview = session.execute(
            select(EmailSend, EmailPreview).join(EmailPreview)
        ).first()
    mail = EmailMessage()
    mail["From"] = "stranger@example.com"
    mail["In-Reply-To"] = f'<fmg-{send.id}@{preview.message["from"].split("@")[1]}>'
    mail.set_content("Unrelated private message")
    assert ingest(app.state.sessions, "box", "1", 1, mail.as_bytes()) == "unmatched"


def test_sync_cursor_read_only_and_recovery(sending):
    from fmg_agent.email.inbox import (
        sync_once,
        InboxCursor,
        mailbox_key,
        monitoring_status,
    )
    from fmg_agent.email.models import EmailSend, EmailPreview
    from pydantic import SecretStr
    from sqlalchemy import select
    import imaplib

    app, client, owner, _, _ = sending
    task = sent_task(sending)
    with app.state.sessions() as session:
        send, preview = session.execute(
            select(EmailSend, EmailPreview).join(EmailPreview)
        ).first()
    message = EmailMessage()
    message["From"] = preview.message["to"]
    message["Message-ID"] = "<sync@example.com>"
    message["In-Reply-To"] = f"<fmg-{send.id}@example.com>"
    message["Subject"] = "Hello"
    message.set_content("Interested in more details.")
    raw = message.as_bytes(policy=policy.SMTP)
    header, body = raw.split(b"\r\n\r\n", 1)
    cfg = app.state.settings.model_copy(
        update={
            "imap_host": "imap.example.com",
            "imap_username": "publisher@example.com",
            "imap_password": SecretStr("private-secret"),
        }
    )

    class Mailbox:
        validity = "1"
        fail = False

        def __init__(self, *args, **kw):
            self.requests = []

        def login(self, *args):
            if self.fail:
                raise imaplib.IMAP4.error("private-secret")

        def select(self, folder, readonly):
            assert readonly is True
            return "OK", [b"1"]

        def response(self, key):
            return key, [self.validity.encode()]

        def uid(self, command, *args):
            self.requests.append((command, args))
            if command == "search":
                return "OK", [b"1"]
            assert "BODY.PEEK[" in args[1] and "BODY.PEEK[]" not in args[1]
            value = header if "[HEADER]" in args[1] else body
            return "OK", [(b"fetch", value)]

        def logout(self):
            pass

    box = Mailbox()
    assert sync_once(app.state.sessions, cfg, lambda *a, **k: box)["processed"] == 1
    assert monitoring_status(app.state.sessions, cfg)["state"] == "active"
    assert sync_once(app.state.sessions, cfg, lambda *a, **k: box)["processed"] == 0
    box.fail = True
    assert (
        sync_once(app.state.sessions, cfg, lambda *a, **k: box)["error"]
        == "imap_auth_or_protocol_error"
    )
    assert "private-secret" not in str(monitoring_status(app.state.sessions, cfg))
    box.fail = False
    box.validity = "2"
    assert sync_once(app.state.sessions, cfg, lambda *a, **k: box)["processed"] == 1
    result = client.get(
        "/v1/outreach/tasks/" + task["id"], headers=headers(owner)
    ).json()["data"]
    assert result["stats"]["replied"] == 1
    assert sum(len(r["replies"]) for r in result["recipients"]) == 1
    with app.state.sessions() as session:
        assert session.get(InboxCursor, mailbox_key(cfg)).uidvalidity == "2"


def test_mime_fetch_excludes_attachment_payload_and_html_is_text():
    from fmg_agent.email.inbox import read_reply

    headers = b'From: a@example.com\r\nContent-Type: multipart/mixed; boundary="x"\r\n'
    sections = {
        "1.MIME": b"Content-Type: text/plain; charset=utf-8\r\n",
        "1": b"Hello from creator",
        "2.MIME": b'Content-Type: application/pdf\r\nContent-Disposition: attachment; filename="huge.pdf"\r\n',
    }
    calls = []

    class Mailbox:
        def uid(self, command, uid, query):
            section = query.split("[")[1].split("]")[0]
            calls.append(section)
            return "OK", (
                [(b"part", sections[section])] if section in sections else [b"NIL"]
            )

    message = BytesParser(policy=policy.default).parsebytes(
        read_reply(Mailbox(), 1, headers)
    )
    assert message.get_body(("plain",)).get_content() == "Hello from creator"
    assert "2" not in calls and "TEXT" not in calls


def test_bounce_is_not_human_reply(sending):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.models import EmailSend, EmailPreview
    from sqlalchemy import select

    app, client, owner, _, _ = sending
    task = sent_task(sending)
    with app.state.sessions() as session:
        send, preview = session.execute(
            select(EmailSend, EmailPreview).join(EmailPreview)
        ).first()
    raw = (
        f'From: mailer-daemon@example.com\r\nMessage-ID: <bounce@example.com>\r\nContent-Type: multipart/report; boundary="dsn"\r\n\r\n'
        f"--dsn\r\nContent-Type: text/plain\r\n\r\nDelivery failed\r\n"
        f"--dsn\r\nContent-Type: message/delivery-status\r\n\r\nAction: failed\r\n\r\n"
        f"--dsn\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-ID: <fmg-{send.id}@example.com>\r\n\r\n--dsn--\r\n"
    ).encode()
    assert ingest(app.state.sessions, "box", "1", 1, raw) == "bounce"
    result = client.get(
        "/v1/outreach/tasks/" + task["id"], headers=headers(owner)
    ).json()["data"]
    assert result["stats"]["bounced"] == 1 and result["stats"]["reply_rate"] == 0
