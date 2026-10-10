"""Task polling must not duplicate binary assets or change frozen send payloads."""

from sqlalchemy import select

from test_email_sending import headers, sending
from test_liminal_fixed_copy import personalization


def test_fifty_recipient_task_responses_stay_small_and_full_previews_are_owned(sending):
    from fmg_agent.email.models import EmailPreview, EmailSend
    from fmg_agent.outreach import OutreachRecipient

    app, client, owner, other, _ = sending
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
