import json
import re
from hashlib import sha256

from sqlalchemy import event, select

from test_email_sending import sending, headers
from test_email_templates import variables


def payload(mailbox_id=None):
    body = {
        "name": "Launch",
        "template_id": "game-outreach",
        "template_version": "5",
        "recipients": [
            {"creator_id": "alice", "to": "alice@example.com", "variables": variables()}
        ],
    }
    if mailbox_id is not None:
        body["mailbox_id"] = mailbox_id
    return body


def test_new_task_fingerprint_includes_mailbox(sending):
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile
    from fmg_agent.outreach import OutreachTask

    app, client, owner, _, _ = sending
    profiles = [
        MailboxProfile(
            id=identity,
            smtp_from=address,
            display_name=name,
            allowed_templates=["game-outreach"],
        )
        for identity, address, name in [
            ("one", "one@example.com", "One"),
            ("two", "two@example.com", "Two"),
        ]
    ]
    app.state.mailboxes = MailboxRegistry(app.state.settings, profiles, legacy=False)
    first = client.post(
        "/v1/outreach/tasks", headers=headers(owner), json=payload("one")
    )
    assert first.status_code == 201
    data = first.json()["data"]
    assert data["mailbox_id"] == "one"
    assert data["display_name"] == "One"
    assert data["recipients"][0]["message"]["from"] == "one@example.com"
    assert data["recipients"][0]["message"]["from_name"] == "One"
    queries = []

    def record(conn, cursor, statement, params, context, many):
        queries.append(statement)

    event.listen(app.state.engine, "before_cursor_execute", record)
    try:
        listing = client.get("/v1/outreach/tasks", headers=headers(owner)).json()[
            "data"
        ]
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record)
    assert not any(
        re.search(r"(?:SELECT\s+|,\s*)email_previews\.message(?:,|\s+AS)", query)
        for query in queries
    )
    assert listing[0]["mailbox_id"] == "one"
    assert listing[0]["sender"] == "one@example.com"
    assert listing[0]["display_name"] == "One"
    assert listing[0]["template_version"] == "5"
    assert listing[0]["sender_safety"]["state"] == "ready"
    assert (
        client.post(
            "/v1/outreach/tasks", headers=headers(owner), json=payload("two")
        ).status_code
        == 409
    )
    with app.state.sessions() as session:
        assert session.scalar(select(OutreachTask)).mailbox_id == "one"


def test_legacy_idempotency_replay_returns_original(sending):
    from fmg_agent.outreach import OutreachTask
    from fmg_agent.email.models import EmailPreview

    app, client, owner, _, _ = sending
    response = client.post("/v1/outreach/tasks", headers=headers(owner), json=payload())
    assert response.status_code == 201
    original = response.json()["data"]
    with app.state.sessions() as session:
        task = session.get(OutreachTask, original["id"])
        task.fingerprint = sha256(
            json.dumps(payload(), sort_keys=True).encode()
        ).hexdigest()
        task.mailbox_id = None
        for row in session.scalars(select(EmailPreview)):
            row.mailbox_id = None
            row.message = {
                key: value for key, value in row.message.items() if key != "from_name"
            }
        session.commit()
        from fmg_agent.email.identity import backfill_mailboxes

        backfill_mailboxes(session, app.state.mailboxes, apply=True)
        session.commit()
    # Historic fingerprints still replay after backfill and explicit selection rollout.
    from fmg_agent.mailboxes import MailboxRegistry

    app.state.mailboxes = MailboxRegistry(
        app.state.settings, app.state.mailboxes.profiles(), legacy=False
    )
    replay = client.post("/v1/outreach/tasks", headers=headers(owner), json=payload())
    assert replay.status_code == 201
    assert replay.json()["data"]["id"] == original["id"]
    assert replay.json()["data"]["revision"] == original["revision"]
    with app.state.sessions() as session:
        assert len(session.scalars(select(EmailPreview)).all()) == 1
        frozen = session.scalar(select(EmailPreview))
        assert "from_name" not in frozen.message
        assert frozen.mailbox_id == "ontologyplay"
    approval = client.post(
        "/v1/outreach/tasks/" + original["id"] + "/start",
        headers=headers(owner),
        json={"confirm": True, "revision": original["revision"]},
    )
    assert approval.status_code == 200


def test_unbackfilled_preview_cannot_send(sending):
    from test_email_sending import preview, send
    from fmg_agent.email.models import EmailPreview

    app, client, owner, _, _ = sending
    data = preview(client, owner).json()["data"]
    assert data["mailbox_id"] == "ontologyplay"
    with app.state.sessions() as session:
        session.get(EmailPreview, data["id"]).mailbox_id = None
        session.commit()
    delivered = []
    app.state.smtp_transport = lambda *args: delivered.append(args) or {
        "state": "sent",
        "code": None,
    }
    response = send(client, owner, data["id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "mailbox_backfill_required"
    assert delivered == []


def test_approval_uses_bound_mailbox_and_rejects_missing_binding(sending):
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile, MAIL_FIELDS
    from fmg_agent.outreach import OutreachTask

    app, client, owner, _, _ = sending
    profile = MailboxProfile(
        id="second",
        display_name="Second",
        allowed_templates=["game-outreach"],
        **{
            **{name: getattr(app.state.settings, name) for name in MAIL_FIELDS},
            "smtp_from": "second@example.com",
        },
    )
    app.state.mailboxes = MailboxRegistry(
        app.state.settings, [*app.state.mailboxes.profiles(), profile], legacy=False
    )
    response = client.post(
        "/v1/outreach/tasks", headers=headers(owner), json=payload("second")
    )
    task = response.json()["data"]
    path = "/v1/outreach/tasks/" + task["id"] + "/start"
    approval = {"confirm": True, "revision": task["revision"]}
    assert client.post(path, headers=headers(owner), json=approval).status_code == 200
    with app.state.sessions() as session:
        stored = session.get(OutreachTask, task["id"])
        stored.state = "awaiting_approval"
        stored.mailbox_id = None
        session.commit()
    response = client.post(path, headers=headers(owner), json=approval)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "mailbox_backfill_required"


def test_new_preview_requires_registerable_sender(sending):
    from fmg_agent.mailboxes import MailboxRegistry
    from test_email_sending import preview

    app, client, owner, _, _ = sending
    app.state.settings.smtp_from = ""
    app.state.mailboxes = MailboxRegistry.load(app.state.settings)
    response = preview(client, owner)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "mailbox_configuration_invalid"


def test_unbackfilled_historical_send_does_not_create_unbound_retry(sending):
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.models import EmailPreview, EmailBounceRetry, EmailSend
    from test_bounce_safety import accepted, dsn

    app, client, owner, _, _ = sending
    send_id = accepted(app, client, owner, "historic-unmapped")
    with app.state.sessions() as session:
        sent = session.get(EmailSend, send_id)
        session.get(EmailPreview, sent.preview_id).mailbox_id = None
        session.commit()
    ingest(
        app.state.sessions,
        "junk",
        "1",
        1,
        dsn(send_id, "unmapped-dsn"),
        mailbox_id="ontologyplay",
    )
    with app.state.sessions() as session:
        assert session.get(EmailBounceRetry, send_id) is None
