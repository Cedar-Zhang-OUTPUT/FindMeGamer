"""Reply integration: owned incoming mail -> immutable draft -> one send -> history."""

from email.message import EmailMessage
from email import policy
from email.parser import BytesParser
from hashlib import sha256

import pytest
from sqlalchemy import select

from test_email_sending import sending, headers, send
from test_inbox import sent_task
from test_sent_copy import archive_env, smtp_server
from test_send_pacing_postgres import pg_sending
from fmg_agent.email.inbox import EmailReply, ingest
from fmg_agent.email.models import EmailPreview, EmailSend


def incoming(
    app,
    *,
    send_id=None,
    message_id="<creator-reply@example.com>",
    reply_to="manager@example.net",
):
    with app.state.sessions() as session:
        query = select(EmailSend, EmailPreview).join(EmailPreview)
        if send_id:
            query = query.where(EmailSend.id == send_id)
        else:
            query = query.where(
                EmailPreview.message["to"].as_string() == "alice@example.com"
            )
        source, preview = session.execute(query).first()
        parent = f'<fmg-{source.id}@{preview.message["from"].split("@")[1]}>'
        mailbox = preview.mailbox_id
    mail = EmailMessage()
    mail["From"] = "Alice <alice@example.com>"
    mail["To"] = preview.message["from"]
    if message_id:
        mail["Message-ID"] = message_id
    mail["In-Reply-To"] = parent
    mail["References"] = "<root@example.com> " + parent
    mail["Subject"] = "Re: Demo invitation"
    if reply_to:
        mail["Reply-To"] = reply_to
    mail.set_content("Yes please, can I have four keys?")
    assert (
        ingest(app.state.sessions, "box", "1", 3, mail.as_bytes(), mailbox_id=mailbox)
        == "human"
    )
    with app.state.sessions() as session:
        row = session.scalar(select(EmailReply).where(EmailReply.send_id == source.id))
        return row.id, parent, mail.as_bytes()


def draft(client, owner, reply_id, **changes):
    payload = {
        "reply_id": reply_id,
        "mailbox_id": "ontologyplay",
        "text": "Here is the approved reply.",
        "text_confirmed": True,
    }
    payload.update(changes)
    return client.post("/v1/email/reply-previews", headers=headers(owner), json=payload)


def test_reply_round_trip_and_key_reconciliation(sending):
    app, client, owner, other, _ = sending
    task = sent_task(sending)
    rid, parent, _ = incoming(app)
    result = draft(client, owner, rid)
    assert result.status_code == 201, result.text
    preview = result.json()["data"]
    assert preview["send_ready"] is True
    m = preview["message"]
    assert m["to"] == "alice@example.com"
    assert m["subject"] == "Re: Demo invitation"
    assert m["in_reply_to"] == "<creator-reply@example.com>"
    assert m["references"] == [
        "<root@example.com>",
        parent,
        "<creator-reply@example.com>",
    ]
    assert m["reply_context"]["task_id"] == task["id"]
    assert m["reply_context"]["creator_id"] == "alice"
    assert m["reply_context"]["reply_to_differs"] is True
    assert m["reply_context"]["reply_to"] == ["manager@example.net"]
    captured = []

    def transport(cfg, message, sid):
        from fmg_agent.email.mime import build_message

        captured.append(build_message(message, sid).as_bytes(policy=policy.SMTP))
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    receipt = send(client, owner, preview["id"], key="reply-key").json()["data"]
    assert receipt["state"] == "sent" and receipt["reply_id"] == rid
    wire = BytesParser(policy=policy.default).parsebytes(captured[0])
    assert str(wire["In-Reply-To"]) == m["in_reply_to"]
    assert str(wire["Message-ID"]) == receipt["message_id"]
    assert wire.get_content().strip() == m["text"]
    lookup = client.get(
        "/v1/email/receipts",
        params={"idempotency_key": "reply-key"},
        headers=headers(owner),
    )
    assert lookup.json()["data"]["id"] == receipt["id"]
    assert (
        send(client, owner, preview["id"], key="reply-key").json()["data"]["id"]
        == receipt["id"]
    )
    assert send(client, owner, preview["id"], key="changed-key").status_code == 409
    assert len(captured) == 1
    assert (
        client.get(
            "/v1/email/receipts",
            params={"idempotency_key": "reply-key"},
            headers=headers(other),
        ).status_code
        == 404
    )
    assert (
        client.get(f"/v1/email/replies/{rid}", headers=headers(other)).status_code
        == 404
    )
    assert draft(client, other, rid).status_code == 404
    h = client.get(
        "/v1/email/reply-history",
        params={"task_id": task["id"], "creator_id": "alice"},
        headers=headers(owner),
    ).json()["data"]
    assert len(h["items"]) == 1 and h["next_cursor"] is None
    assert "four keys" in h["items"][0]["message"]["reply_context"]["original_body"]
    assert (
        client.get(
            "/v1/email/reply-history",
            params={"task_id": task["id"]},
            headers=headers(other),
        ).status_code
        == 404
    )
    view = client.get(
        f'/v1/outreach/tasks/{task["id"]}', headers=headers(owner)
    ).json()["data"]
    assert view["outgoing_reply_count"] == 1
    # Follow-up to our reply inherits the original creator/task, not a new campaign.
    next_id, _, _ = incoming(
        app, send_id=receipt["id"], message_id="<second-reply@example.com>"
    )
    second = draft(client, owner, next_id).json()["data"]
    assert second["message"]["reply_context"]["task_id"] == task["id"]
    assert second["message"]["reply_context"]["creator_id"] == "alice"
    assert (
        draft(client, owner, rid, recipient_mode="reply_to").json()["data"]["message"][
            "to"
        ]
        == "manager@example.net"
    )


@pytest.mark.parametrize(
    "change,status",
    [
        ({"text_confirmed": False}, 422),
        ({"text_confirmed": None}, 422),
        ({"mailbox_id": "second"}, 409),
        ({"to": "intruder@example.com"}, 422),
        ({"template_id": "custom-reply", "template_version": "1"}, 422),
        ({"variables": {"creator_name": "other"}}, 422),
    ],
)
def test_invalid_reply_request_never_creates_send(sending, change, status):
    app, client, owner, _, _ = sending
    sent_task(sending)
    rid, _, _ = incoming(app)
    assert draft(client, owner, rid, **change).status_code == status
    with app.state.sessions() as session:
        assert len(session.scalars(select(EmailSend)).all()) == 2


def test_missing_headers_fail_closed_and_legacy_recovered_once(sending, monkeypatch):
    app, client, owner, _, _ = sending
    sent_task(sending)
    rid, parent, raw = incoming(app)
    with app.state.sessions() as session:
        row = session.get(EmailReply, rid)
        saved = row.diagnostics["thread_headers"]
        row.diagnostics = None
        session.commit()
    from fmg_agent.errors import ApiError

    def missing(*args):
        raise ApiError(
            409, "reply_headers_unavailable", "Cannot verify original headers."
        )

    monkeypatch.setattr("fmg_agent.email.reply_headers.recover_headers", missing)
    assert (
        draft(client, owner, rid).json()["error"]["code"] == "reply_headers_unavailable"
    )
    calls = []

    def recover(cfg, reply, original):
        calls.append(original)
        assert original == parent
        return saved

    monkeypatch.setattr("fmg_agent.email.reply_headers.recover_headers", recover)
    assert draft(client, owner, rid).status_code == 201
    assert draft(client, owner, rid).status_code == 201
    assert calls == [parent]
    with app.state.sessions() as session:
        row = session.get(EmailReply, rid)
        row.diagnostics = {"thread_headers": {**saved, "message_id": None}}
        session.commit()
    assert (
        draft(client, owner, rid).json()["error"]["code"] == "reply_message_id_missing"
    )


def test_auto_reply_and_sender_pause(sending):
    app, client, owner, _, _ = sending
    sent_task(sending)
    rid, _, _ = incoming(app)
    from fmg_agent.email.safety import trip

    with app.state.sessions() as session:
        trip(session, "publisher@example.com", "spam_block")
        session.commit()
    preview = draft(client, owner, rid).json()["data"]
    assert preview["send_ready"] is False
    assert send(client, owner, preview["id"]).status_code == 409
    with app.state.sessions() as session:
        row = session.get(EmailReply, rid)
        row.kind = "bounce"
        session.commit()
    assert draft(client, owner, rid).json()["error"]["code"] == "reply_not_human"


def test_unknown_reply_stays_one_attempt(sending):
    app, client, owner, _, _ = sending
    sent_task(sending)
    rid, _, _ = incoming(app)
    p = draft(client, owner, rid).json()["data"]
    calls = []

    def transport(*args):
        calls.append(1)
        return {"state": "unknown", "code": "smtp_confirmation_lost"}

    app.state.smtp_transport = transport
    assert (
        send(client, owner, p["id"], key="unknown-key").json()["data"]["state"]
        == "unknown"
    )
    assert (
        client.get(
            "/v1/email/receipts",
            params={"idempotency_key": "unknown-key"},
            headers=headers(owner),
        ).json()["data"]["state"]
        == "unknown"
    )
    assert (
        send(client, owner, p["id"], key="unknown-key").json()["data"]["state"]
        == "unknown"
    )
    assert calls == [1]


def test_fixed_reply_template_and_mailbox_binding(sending):
    from fmg_agent.email.templates import (
        get_template,
        render_template,
        check_mailbox_template,
    )
    from fmg_agent.email.replies import check_reply_template
    from fmg_agent.mailboxes import MailboxProfile
    from fmg_agent.errors import ApiError

    definition = get_template("thieves-demo-access-reply", "1")
    assert set(definition["variables"]) == {"creator_name"}
    text = render_template(definition, {"creator_name": "Alice"})["text"]
    assert text.startswith("Hi Alice\n")
    assert "we'll send four so you can try with your friends." in text
    assert text.endswith("The No Rest for Thieves Development Team")
    profile = MailboxProfile(
        id="second",
        smtp_from="norestforthieves@ontologyplay.com",
        allowed_reply_templates=[definition["id"]],
        allowed_templates=[definition["id"]],
    )
    check_reply_template(profile, definition["id"])
    with pytest.raises(ApiError):
        check_mailbox_template(profile, definition["id"])
    with pytest.raises(ApiError):
        check_reply_template(
            profile.model_copy(update={"id": "liminal"}), definition["id"]
        )
    with pytest.raises(ApiError):
        render_template(definition, {"creator_name": "Alice", "keys": "unauthorized"})
    with pytest.raises(ApiError):
        get_template(definition["id"], "2")


def test_legacy_imap_lookup_checks_hash_sender_and_uses_peek(sending):
    from types import SimpleNamespace
    from fmg_agent.email.reply_headers import recover_headers
    from fmg_agent.config import Settings
    from fmg_agent.errors import ApiError

    app, _, _, _, _ = sending
    sent_task(sending)
    _, parent, raw = incoming(app)
    calls = []

    class Imap:
        wrong = False

        def __init__(self, *args, **kwargs):
            assert kwargs["ssl_context"].verify_mode

        def login(self, *args):
            pass

        def list(self):
            return "OK", []

        def select(self, folder, readonly=False):
            assert readonly is True
            return "OK", []

        def uid(self, command, *args):
            calls.append((command, args))
            if command == "search":
                assert parent in args[1]
                return "OK", [b"1"]
            assert args[1] == "(BODY.PEEK[HEADER]<0.65536>)"
            content = (
                raw.replace(b"alice@example.com", b"attacker@example.com")
                if self.wrong
                else raw
            )
            return "OK", [(b"1", content)]

        def logout(self):
            pass

    cfg = Settings(
        database_url=app.state.settings.database_url,
        imap_host="imap.example.com",
        imap_username="user",
        imap_password="secret",
    )
    reply = SimpleNamespace(
        sender="alice@example.com",
        message_key=sha256(b"<creator-reply@example.com>").hexdigest(),
    )
    assert (
        recover_headers(cfg, reply, parent, connect=Imap)["message_id"]
        == "<creator-reply@example.com>"
    )
    Imap.wrong = True
    with pytest.raises(ApiError) as error:
        recover_headers(cfg, reply, parent, connect=Imap)
    assert error.value.code == "reply_headers_unavailable"
    Imap.wrong = False
    reply.message_key = "not-the-stored-message"
    with pytest.raises(ApiError):
        recover_headers(cfg, reply, parent, connect=Imap)


def test_reply_mime_sent_copy_failure_separate(archive_env):
    from test_email_sending import preview
    from fmg_agent.email.inbox import ingest

    app, client, owner, smtp, box = archive_env
    pid = preview(client, owner).json()["data"]["id"]
    original = send(client, owner, pid, key="original").json()["data"]
    mail = EmailMessage()
    mail["From"] = "creator@example.com"
    mail["To"] = "publisher@example.com"
    mail["Message-ID"] = "<archive-reply@example.com>"
    mail["In-Reply-To"] = original["message_id"]
    mail["Subject"] = "Re: Test"
    mail.set_content("Hello!")
    assert (
        ingest(
            app.state.sessions,
            "archive-box",
            "1",
            1,
            mail.as_bytes(),
            mailbox_id="ontologyplay",
        )
        == "human"
    )
    with app.state.sessions() as session:
        rid = session.scalar(select(EmailReply.id))
    reply = draft(client, owner, rid).json()["data"]
    box.mode = "reject"
    receipt = send(client, owner, reply["id"], key="reply-archive").json()["data"]
    assert receipt["state"] == "sent" and receipt["sent_copy"]["state"] == "failed"
    assert receipt["sent_at"]
    parsed = BytesParser(policy=policy.default).parsebytes(smtp.messages[-1])
    assert parsed["In-Reply-To"] == "<archive-reply@example.com>"
    assert parsed["Message-ID"] == receipt["message_id"]
    assert (
        send(client, owner, reply["id"], key="reply-archive").json()["data"]["id"]
        == receipt["id"]
    )
    assert len(smtp.messages) == 2


@pytest.mark.postgres
def test_two_clients_one_reply_attempt_and_unknown_receipt(pg_sending):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fmg_agent.email.identity import register_identities

    app, client, owner = pg_sending
    with app.state.sessions() as session:
        register_identities(session, app.state.mailboxes.current())
        original = EmailPreview(
            token_id=owner.id,
            mailbox_id="ontologyplay",
            template_id="game-outreach",
            template_version="5",
            message={
                "from": "publisher@example.com",
                "to": "alice@example.com",
                "subject": "Invitation",
                "text": "Hi",
                "format": "plain_text",
            },
        )
        session.add(original)
        session.flush()
        sent = EmailSend(
            token_id=owner.id,
            preview_id=original.id,
            idempotency_key="seed",
            state="sent",
        )
        session.add(sent)
        session.flush()
        incoming_reply = EmailReply(
            send_id=sent.id,
            message_key="concurrent-source",
            kind="human",
            sender="alice@example.com",
            subject="Re: Invitation",
            body="Hello",
            received_at="2026-11-03T00:00:00Z",
            diagnostics={
                "thread_headers": {
                    "message_id": "<concurrent@example.com>",
                    "references": [],
                    "reply_to": [],
                }
            },
        )
        session.add(incoming_reply)
        session.commit()
        rid = incoming_reply.id
    preview = draft(client, owner, rid).json()["data"]
    entered, release = Event(), Event()
    calls = []

    def transport(*args):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return {"state": "unknown", "code": "smtp_confirmation_lost"}

    app.state.smtp_transport = transport
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send, client, owner, preview["id"], "reply-concurrent")
        assert entered.wait(5)
        try:
            duplicate = send(client, owner, preview["id"], "reply-concurrent")
            assert duplicate.json()["data"]["state"] == "sending"
            lookup = client.get(
                "/v1/email/receipts",
                params={"idempotency_key": "reply-concurrent"},
                headers=headers(owner),
            ).json()["data"]
            assert lookup["id"] == duplicate.json()["data"]["id"]
            assert (
                send(client, owner, preview["id"], "wrong-new-key").status_code == 409
            )
        finally:
            release.set()
        assert first.result().json()["data"]["state"] == "unknown"
    assert (
        send(client, owner, preview["id"], "reply-concurrent").json()["data"]["state"]
        == "unknown"
    )
    assert calls == [1]


def test_registered_reply_template_api_frozen_and_allowlisted(sending):
    from fmg_agent.mailboxes import MailboxProfile, MailboxRegistry
    from fmg_agent.email.identity import register_identities

    app, client, owner, _, _ = sending
    profile = MailboxProfile(
        id="second",
        smtp_from="norestforthieves@ontologyplay.com",
        display_name="No Rest for Thieves",
        smtp_host="smtp.example.com",
        smtp_username="user",
        smtp_password="test-only",
        allowed_templates=["thieves-outreach"],
        allowed_reply_templates=["thieves-demo-access-reply"],
        email_send_interval_seconds=0,
    )
    app.state.mailboxes = MailboxRegistry(app.state.settings, [profile], legacy=False)
    with app.state.sessions() as session:
        register_identities(session, app.state.mailboxes.current())
        p = EmailPreview(
            token_id=owner.id,
            mailbox_id="second",
            template_id="thieves-outreach",
            template_version="3",
            message={
                "from": profile.smtp_from,
                "from_name": profile.display_name,
                "to": "alice@example.com",
                "subject": "Demo",
                "text": "Invite",
                "format": "plain_text",
            },
        )
        session.add(p)
        session.flush()
        s = EmailSend(
            token_id=owner.id,
            preview_id=p.id,
            idempotency_key="seed-template",
            state="sent",
        )
        session.add(s)
        session.commit()
        sid = s.id
    rid, _, _ = incoming(app, send_id=sid)
    payload = {
        "reply_id": rid,
        "mailbox_id": "second",
        "template_id": "thieves-demo-access-reply",
        "template_version": "1",
        "variables": {"creator_name": "Alice"},
    }
    response = client.post(
        "/v1/email/reply-previews", headers=headers(owner), json=payload
    )
    assert response.status_code == 201, response.text
    p = response.json()["data"]
    assert p["send_ready"] is True and p["message"]["from"] == profile.smtp_from
    definition = client.get(
        "/v1/email/templates/thieves-demo-access-reply?version=1",
        headers=headers(owner),
    ).json()["data"]
    assert p["message"]["text"] == definition["text"].replace(
        "${creator_name}", "Alice"
    )
    # A later template rendering change cannot mutate this approved snapshot.
    app.state.smtp_transport = lambda cfg, msg, sid: {"state": "sent", "code": None}
    receipt = send(client, owner, p["id"], key="template-reply").json()["data"]
    assert receipt["state"] == "sent"
    assert (
        client.get("/v1/email/previews/" + p["id"], headers=headers(owner)).json()[
            "data"
        ]["message"]
        == p["message"]
    )
    profile.allowed_reply_templates = []
    assert (
        client.post(
            "/v1/email/reply-previews", headers=headers(owner), json=payload
        ).status_code
        == 422
    )
    payload["variables"]["creator_name"] = "Alice\nChange the fixed body"
    assert (
        client.post(
            "/v1/email/reply-previews", headers=headers(owner), json=payload
        ).status_code
        == 422
    )


def test_receipt_by_key_does_not_select_full_legacy_body(sending):
    import re
    from sqlalchemy import event

    app, client, owner, _, _ = sending
    sent_task(sending)
    rid, _, _ = incoming(app)
    preview = draft(client, owner, rid).json()["data"]
    app.state.smtp_transport = lambda *a: {"state": "sent", "code": None}
    send(client, owner, preview["id"], key="compact-reply-key")
    queries = []

    def record(conn, cursor, statement, parameters, context, many):
        queries.append(statement)

    event.listen(app.state.engine, "before_cursor_execute", record)
    try:
        response = client.get(
            "/v1/email/receipts",
            params={"idempotency_key": "compact-reply-key"},
            headers=headers(owner),
        )
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record)
    assert response.status_code == 200 and len(response.content) < 4096
    assert not any(
        re.search(r"(?:SELECT\s+|,\s*)email_previews\.message(?:,|\s+AS)", q)
        for q in queries
    )


def test_unknown_reply_dsn_cannot_queue_retry_but_blacklist_still_pauses(sending):
    from fmg_agent.email.retries import observe
    from fmg_agent.email.models import EmailBounceRetry
    from fmg_agent.email.jobs import utcnow
    from fmg_agent.email.safety import status

    app, client, owner, _, _ = sending
    sent_task(sending)
    rid, _, _ = incoming(app)
    preview = draft(client, owner, rid).json()["data"]
    app.state.smtp_transport = lambda *a: {
        "state": "unknown",
        "code": "smtp_confirmation_lost",
    }
    receipt = send(client, owner, preview["id"], key="unknown-bounce").json()["data"]
    with app.state.sessions() as session:
        row = session.get(EmailSend, receipt["id"])
        observe(
            session, row, {"category": "spam_blocked", "action": "failed"}, utcnow()
        )
        assert session.get(EmailBounceRetry, row.id) is None
        observe(
            session,
            row,
            {"category": "spam_blocked", "action": "failed", "blocklisted": True},
            utcnow(),
        )
        assert status(session, "publisher@example.com")["state"] == "paused"


def test_reply_history_pagination_stays_within_task_and_creator(sending):
    app, client, owner, _, _ = sending
    task = sent_task(sending)
    rid, _, _ = incoming(app)
    app.state.smtp_transport = lambda *a: {"state": "sent", "code": None}
    ids = []
    for index in range(2):
        preview = draft(client, owner, rid, text=f"Approved follow-up {index}").json()[
            "data"
        ]
        ids.append(
            send(client, owner, preview["id"], key=f"history-{index}").json()["data"][
                "id"
            ]
        )
    params = {"task_id": task["id"], "creator_id": "alice", "limit": 1}
    first = client.get(
        "/v1/email/reply-history", params=params, headers=headers(owner)
    ).json()["data"]
    assert first["items"][0]["receipt"]["id"] == ids[0]
    assert first["next_cursor"] == ids[0]
    second = client.get(
        "/v1/email/reply-history",
        params={**params, "cursor": first["next_cursor"]},
        headers=headers(owner),
    ).json()["data"]
    assert (
        second["items"][0]["receipt"]["id"] == ids[1] and second["next_cursor"] is None
    )
    wrong = client.get(
        "/v1/email/reply-history",
        params={**params, "creator_id": "bob", "cursor": ids[0]},
        headers=headers(owner),
    )
    assert wrong.status_code == 422
