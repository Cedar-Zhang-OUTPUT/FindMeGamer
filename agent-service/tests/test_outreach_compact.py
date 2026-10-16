"""Task polling must not duplicate binary assets or change frozen send payloads."""

from sqlalchemy import select

from test_email_sending import headers, sending
from test_liminal_fixed_copy import personalization
from test_send_pacing_postgres import pg_sending
import pytest


def configure_liminal(app):
    from fmg_agent.mailboxes import MailboxRegistry

    app.state.settings.smtp_from = "OntologyPlay@hotmail.com"
    app.state.mailboxes = MailboxRegistry.load(app.state.settings)


@pytest.mark.postgres
def test_postgres_summary_extracts_only_sender_and_keeps_counts(pg_sending):
    app, client, owner = pg_sending
    configure_liminal(app)
    task = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "pg-summary"),
        json={
            "name": "Postgres summary",
            "template_id": "liminal-outreach",
            "template_version": "7",
            "recipients": [
                {
                    "creator_id": "one",
                    "to": "one@example.com",
                    "variables": personalization(),
                }
            ],
        },
    ).json()["data"]
    response = client.get(
        "/v1/outreach/tasks/" + task["id"] + "?summary=true", headers=headers(owner)
    )
    assert response.status_code == 200 and len(response.content) < 4096
    data = response.json()["data"]
    assert data["stats"]["pending"] == 1 and data["stats"]["sent"] == 0
    assert data["sender_safety"]["state"] == "ready"
    assert "recipients" not in data and "template" not in data


def test_summary_excludes_drafts_and_reply_bodies_and_enforces_ownership(sending):
    """A send prerequisite must not download frozen images/drafts or long replies."""
    from sqlalchemy import event, func
    from fmg_agent.email.models import EmailSend

    app, client, owner, other, read = sending
    configure_liminal(app)
    task = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "summary-only"),
        json={
            "name": "Summary",
            "template_id": "liminal-outreach",
            "template_version": "7",
            "recipients": [
                {
                    "creator_id": "one",
                    "to": "one@example.com",
                    "variables": personalization(),
                },
                {
                    "creator_id": "two",
                    "to": "two@example.com",
                    "variables": personalization(),
                },
            ],
        },
    ).json()["data"]
    path = "/v1/outreach/tasks/" + task["id"] + "?summary=true"
    queries = []

    def record(conn, cursor, statement, params, context, many):
        queries.append(statement)

    event.listen(app.state.engine, "before_cursor_execute", record)
    try:
        response = client.get(path, headers=headers(owner))
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record)
    assert response.status_code == 200
    data = response.json()["data"]
    assert "recipients" not in data and "template" not in data
    assert len(response.content) < 4096
    assert data["revision"] == task["revision"]
    assert data["state"] == "awaiting_approval"
    assert data["stats"]["pending"] == 2 and data["stats"]["sent"] == 0
    assert data["sender_safety"]["state"] == "ready"
    assert "monitoring" in data
    import re

    assert not any(
        re.search(r"(?:SELECT\s+|,\s*)email_previews\.message(?:,|\s+AS)", q)
        for q in queries
    )
    assert client.get(path, headers=headers(other)).status_code == 404
    assert client.get(path, headers=headers(read)).status_code == 403
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EmailSend)) == 0


def test_summary_tracks_retry_unknown_reply_and_sender_hold(sending, monkeypatch):
    from datetime import datetime, timezone
    from fmg_agent.email.inbox import ingest, EmailReply
    from fmg_agent.email.retries import process_retry
    from fmg_agent.email.models import EmailBounceRetry, EmailSend
    from fmg_agent.email.safety import trip
    from fmg_agent.outreach import pending, process_recipient
    from test_bounce_safety import dsn

    app, client, owner, _, _ = sending
    configure_liminal(app)
    task = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "summary-retry"),
        json={
            "name": "Retry summary",
            "template_id": "liminal-outreach",
            "template_version": "7",
            "recipients": [
                {
                    "creator_id": "one",
                    "to": "creator@example.com",
                    "variables": personalization(),
                }
            ],
        },
    ).json()["data"]
    path = "/v1/outreach/tasks/" + task["id"]
    client.post(
        path + "/start",
        headers=headers(owner),
        json={"confirm": True, "revision": task["revision"]},
    )
    process_recipient(
        app.state.sessions,
        pending(app.state.sessions)[0],
        app.state.settings,
        lambda *args: {"state": "sent"},
    )
    with app.state.sessions() as session:
        sid = session.scalar(select(EmailSend.id))
    notice = dsn(sid, "summary-dsn").replace(
        f"fmg-{sid}@example.com".encode(), f"fmg-{sid}@hotmail.com".encode()
    )
    ingest(app.state.sessions, "junk", "1", 1, notice)
    queued = client.get(path + "?summary=true", headers=headers(owner)).json()["data"]
    assert "recipients" not in queued
    assert queued["state"] == "sending"
    assert queued["stats"]["retry_queued"] == 1 and queued["stats"]["bounced"] == 1
    with app.state.sessions() as session:
        due = session.get(EmailBounceRetry, sid).due_at.replace(tzinfo=timezone.utc)
    monkeypatch.setattr("fmg_agent.email.retries.utcnow", lambda: due)
    process_retry(
        app.state.sessions,
        sid,
        app.state.settings,
        lambda *args: {"state": "unknown", "code": "graph_confirmation_lost"},
    )
    with app.state.sessions() as session:
        session.add(
            EmailReply(
                id="human-summary",
                send_id=sid,
                message_key="summary-reply",
                kind="human",
                sender="creator@example.com",
                subject="Reply",
                body="private reply " * 10000,
                received_at=datetime.now(timezone.utc).isoformat(),
                diagnostics={},
            )
        )
        trip(session, "OntologyPlay@hotmail.com", "provider_rate_limited")
        session.commit()
    queries = []
    from sqlalchemy import event

    def record(conn, cursor, statement, params, context, many):
        queries.append(statement)

    event.listen(app.state.engine, "before_cursor_execute", record)
    try:
        response = client.get(path + "?summary=true", headers=headers(owner))
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record)
    data = response.json()["data"]
    assert len(response.content) < 4096 and "private reply" not in response.text
    assert data["stats"]["unknown"] == 1 and data["stats"]["retry_unknown"] == 1
    assert data["stats"]["replied"] == 1 and data["stats"]["bounced"] == 0
    assert data["state"] == "finished_with_issues"
    assert data["sender_safety"]["reason"] == "provider_rate_limited"
    assert not any("email_replies.body" in q for q in queries)
    full = client.get(path, headers=headers(owner)).json()["data"]
    assert data["stats"] == full["stats"] and data["state"] == full["state"]
    assert any(
        m["body"].startswith("private reply") for m in full["recipients"][0]["replies"]
    )


def test_legacy_task_reads_are_compressed_without_changing_drafts(sending):
    app, client, owner, _, _ = sending
    configure_liminal(app)
    task = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "gzip-legacy"),
        json={
            "name": "Legacy compressed",
            "template_id": "liminal-outreach",
            "template_version": "7",
            "recipients": [
                {
                    "creator_id": "one",
                    "to": "one@example.com",
                    "variables": personalization(),
                }
            ],
        },
    ).json()["data"]
    path = "/v1/outreach/tasks/" + task["id"]
    plain = client.get(path, headers={**headers(owner), "Accept-Encoding": "identity"})
    compressed = client.get(path, headers={**headers(owner), "Accept-Encoding": "gzip"})
    assert compressed.headers.get("Content-Encoding") == "gzip"
    assert int(compressed.headers["Content-Length"]) < len(plain.content) * 0.7
    assert compressed.json()["data"] == plain.json()["data"]


def test_fifty_recipient_task_responses_stay_small_and_full_previews_are_owned(sending):
    from fmg_agent.email.models import EmailPreview, EmailSend
    from fmg_agent.outreach import OutreachRecipient

    app, client, owner, other, _ = sending
    configure_liminal(app)
    payload = {
        "name": "Fifty saved image drafts",
        "template_id": "liminal-outreach",
        "template_version": "7",
        "recipients": [
            {
                "creator_id": f"creator-{i}",
                "to": f"creator-{i}@example.com",
                "variables": personalization(),
            }
            for i in range(50)
        ],
    }
    created = client.post(
        "/v1/outreach/tasks", headers=headers(owner, "compact-fifty"), json=payload
    )
    assert created.status_code == 201
    assert len(created.content) < 1024 * 1024
    task = created.json()["data"]
    path = "/v1/outreach/tasks/" + task["id"]
    replay = client.post(
        "/v1/outreach/tasks", headers=headers(owner, "compact-fifty"), json=payload
    )
    queried = client.get(path, headers=headers(owner))
    summary = client.get(path + "?summary=true", headers=headers(owner))
    assert summary.status_code == 200 and len(summary.content) < 4096
    assert summary.json()["data"]["stats"]["pending"] == 50
    assert "recipients" not in summary.json()["data"]
    started = client.post(
        path + "/start",
        headers=headers(owner),
        json={"confirm": True, "revision": task["revision"]},
    )
    for response in (created, replay, queried, started):
        assert response.status_code in (200, 201)
        assert len(response.content) < 1024 * 1024
        data = response.json()["data"]
        assert data["revision"] == task["revision"]
        assert data["stats"]["pending"] == 50
        assert len(data["recipients"]) == 50
        for recipient in data["recipients"]:
            message = recipient["message"]
            assert "signature_png_base64" not in message
            assert "footer_png_base64" not in message
            assert (
                "Demo: https://store.steampowered.com/app/4952700/_/" in message["text"]
            )
            assert "cid:liminal-game-banner" in message["html"]

    recipient = task["recipients"][0]
    preview_path = "/v1/email/previews/" + recipient["preview_id"]
    full = client.get(preview_path, headers=headers(owner))
    assert full.status_code == 200
    full_message = full.json()["data"]["message"]
    assert full_message["signature_png_base64"]
    assert full_message["footer_png_base64"]
    assert full_message["text"] == recipient["message"]["text"]
    assert full_message["subject"] == recipient["message"]["subject"]
    assert client.get(preview_path, headers=headers(other)).status_code == 404
    with app.state.sessions() as session:
        stored = session.scalars(
            select(EmailPreview)
            .join(OutreachRecipient, OutreachRecipient.preview_id == EmailPreview.id)
            .where(OutreachRecipient.task_id == task["id"])
        ).all()
        assert len(stored) == 50
        assert all(
            p.message["signature_png_base64"] and p.message["footer_png_base64"]
            for p in stored
        )
        assert session.scalars(select(EmailSend)).all() == []


def test_compact_task_query_keeps_paused_state_and_original_delivery_assets(sending):
    from fmg_agent.email.models import EmailPreview
    from fmg_agent.outreach import OutreachTask, pending, process_recipient

    app, client, owner, _, _ = sending
    configure_liminal(app)
    task = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "compact-snapshot"),
        json={
            "name": "Snapshot isolation",
            "template_id": "liminal-outreach",
            "template_version": "7",
            "recipients": [
                {
                    "creator_id": "creator",
                    "to": "creator@example.com",
                    "variables": personalization(),
                }
            ],
        },
    ).json()["data"]
    path = "/v1/outreach/tasks/" + task["id"]
    with app.state.sessions() as session:
        row = session.get(OutreachTask, task["id"])
        row.state = "blocked"
        session.commit()
        original = session.scalar(select(EmailPreview)).message
    queried = client.get(path, headers=headers(owner)).json()["data"]
    assert "footer_png_base64" not in queried["recipients"][0]["message"]
    assert queried["state"] == "blocked"
    assert queried["stats"]["pending"] == 1
    assert pending(app.state.sessions) == []

    # Explicit test-only approval exercises the real reservation/send path.
    assert (
        client.post(
            path + "/start",
            headers=headers(owner),
            json={"confirm": True, "revision": task["revision"]},
        ).status_code
        == 200
    )
    delivered = []

    def transport(config, message, message_id):
        delivered.append(message)
        return {"state": "sent", "code": None}

    for recipient_id in pending(app.state.sessions):
        process_recipient(
            app.state.sessions, recipient_id, app.state.settings, transport
        )
    assert delivered == [original]
    assert delivered[0]["signature_png_base64"]
    assert delivered[0]["footer_png_base64"]
    assert client.get(path, headers=headers(owner)).json()["data"]["stats"]["sent"] == 1
