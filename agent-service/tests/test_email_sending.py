from datetime import datetime, timedelta, timezone
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from test_email_templates import variables


@pytest.fixture
def sending(tmp_path):
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token
    from fmg_agent.config import Settings
    from fmg_agent.db import Base

    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'sending.sqlite'}",
            smtp_host="smtp.example.com",
            smtp_username="user",
            smtp_password="secret-password",
            smtp_from="publisher@example.com",
        )
    )
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as session:
        owner = issue_token(session, label="owner", scopes=["email:send"])
        other = issue_token(session, label="other", scopes=["email:send"])
        read = issue_token(session, label="read", scopes=["read"])
    with TestClient(app) as client:
        yield app, client, owner, other, read


def headers(token, key="send-one"):
    return {"Authorization": f"Bearer {token.token}", "Idempotency-Key": key}


def preview(client, token):
    return client.post(
        "/v1/email/previews",
        headers=headers(token),
        json={
            "template_id": "game-outreach",
            "template_version": "3",
            "variables": variables(),
            "to": "creator@example.com",
        },
    )


def send(client, token, preview_id, key="send-one", confirm=True):
    return client.post(
        "/v1/email/sends",
        headers=headers(token, key),
        json={"preview_id": preview_id, "confirm": confirm},
    )


def test_preview_works_without_smtp_but_send_does_not(sending):
    app, client, owner, _, _ = sending
    app.state.settings.smtp_host = ""
    response = preview(client, owner)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["message"]["to"] == "creator@example.com"
    assert "New Game" in data["message"]["subject"]
    assert data["send_ready"] is False
    assert send(client, owner, data["id"]).status_code == 503


def test_missing_confirm_and_scope_or_ownership_never_send(sending):
    app, client, owner, other, read = sending

    def transport(*args):
        pytest.fail("unauthorized send reached SMTP")

    app.state.smtp_transport = transport
    assert preview(client, read).status_code == 403
    response = preview(client, owner)
    assert response.status_code == 201
    preview_id = response.json()["data"]["id"]
    assert send(client, owner, preview_id, confirm=False).status_code == 422
    assert send(client, other, preview_id).status_code == 404
    assert (
        client.get(
            f"/v1/email/previews/{preview_id}", headers=headers(other)
        ).status_code
        == 404
    )


def test_send_reuses_snapshot_and_is_idempotent_even_with_new_key(sending):
    app, client, owner, other, _ = sending
    delivered = []

    def transport(config, message, message_id):
        delivered.append(message)
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    response = preview(client, owner)
    assert response.status_code == 201
    data = response.json()["data"]
    result = send(client, owner, data["id"])
    assert result.status_code == 200
    receipt = result.json()["data"]
    assert receipt["state"] == "sent"
    assert delivered == [data["message"]]
    assert send(client, owner, data["id"]).json()["data"]["id"] == receipt["id"]
    assert send(client, owner, data["id"], key="new-key").status_code == 409
    assert len(delivered) == 1
    assert (
        client.get(
            f"/v1/email/sends/{receipt['id']}", headers=headers(other)
        ).status_code
        == 404
    )
    second = preview(client, owner).json()["data"]["id"]
    assert send(client, owner, second).status_code == 409


def test_concurrent_send_has_one_delivery_and_preserves_unknown(sending):
    app, client, owner, _, _ = sending
    from fmg_agent.email.sending import SendStore

    entered, release = Event(), Event()
    deliveries = []

    def transport(config, message, message_id):
        deliveries.append(message_id)
        entered.set()
        assert release.wait(5)
        return {"state": "unknown", "code": "smtp_confirmation_lost"}

    app.state.smtp_transport = transport
    data = preview(client, owner).json()["data"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send, client, owner, data["id"])
        assert entered.wait(5)
        second = send(client, owner, data["id"])
        assert second.status_code == 200
        assert second.json()["data"]["state"] == "sending"
        release.set()
        assert first.result().json()["data"]["state"] == "unknown"
    assert len(deliveries) == 1
    assert send(client, owner, data["id"]).json()["data"]["state"] == "unknown"
    assert len(deliveries) == 1


def test_old_sending_becomes_unknown_without_delivery(sending):
    from fmg_agent.email.models import EmailSend

    app, client, owner, _, _ = sending

    def crashed(*args):
        raise RuntimeError("simulated process error must not leak secret-password")

    app.state.smtp_transport = crashed
    data = preview(client, owner).json()["data"]
    response = send(client, owner, data["id"])
    assert response.status_code == 200
    assert response.json()["data"]["state"] == "unknown"
    assert "secret-password" not in response.text
    receipt_id = response.json()["data"]["id"]
    with app.state.sessions() as session:
        session.execute(
            update(EmailSend)
            .where(EmailSend.id == receipt_id)
            .values(
                state="sending",
                updated_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
        )
        session.commit()
    read = client.get(f"/v1/email/sends/{receipt_id}", headers=headers(owner))
    assert read.json()["data"]["state"] == "unknown"


def test_sender_changes_require_new_preview(sending):
    app, client, owner, _, _ = sending
    app.state.smtp_transport = lambda *args: pytest.fail(
        "changed sender was not previewed"
    )
    data = preview(client, owner).json()["data"]
    app.state.settings.smtp_from = "different@example.com"
    assert send(client, owner, data["id"]).status_code == 409
