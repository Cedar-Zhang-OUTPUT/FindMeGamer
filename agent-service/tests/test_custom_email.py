import pytest
from test_email_sending import sending, headers, send


def payload(**changes):
    return {
        "mailbox_id": "ontologyplay",
        "to": "creator@example.com",
        "subject": "Demo access",
        "text": "Hi **Creator**, ==your key==",
        "body_format": "markdown",
        **changes,
    }


def test_custom_preview_send_is_frozen_and_idempotent(sending):
    app, client, owner, other, _ = sending
    response = client.post("/v1/email/previews", headers=headers(owner), json=payload())
    assert response.status_code == 201, response.text
    preview = response.json()["data"]
    assert preview["send_ready"] is True
    message = preview["message"]
    assert message["to"] == "creator@example.com"
    assert message["subject"] == "Demo access"
    assert "<strong>Creator</strong>" in message["html"]
    assert "reply_context" not in message
    delivered = []

    def transport(config, frozen, send_id):
        delivered.append(frozen)
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    assert send(client, other, preview["id"]).status_code == 404
    assert send(client, owner, preview["id"], confirm=False).status_code == 422
    first = send(client, owner, preview["id"])
    assert first.status_code == 200, first.text
    assert (
        send(client, owner, preview["id"]).json()["data"]["id"]
        == first.json()["data"]["id"]
    )
    assert delivered == [message]


@pytest.mark.parametrize(
    "changes",
    [
        {"mailbox_id": None},
        {"subject": "x\r\nBcc: victim@example.com"},
        {"subject": "   "},
        {"text": "   "},
        {"variables": {"name": "X"}},
        {"template_version": "1"},
        {"template_id": "game-outreach", "template_version": "5"},
        {"to": "a@example.com,b@example.com"},
    ],
)
def test_invalid_custom_mail_rejected(sending, changes):
    _, client, owner, _, _ = sending
    assert (
        client.post(
            "/v1/email/previews", headers=headers(owner), json=payload(**changes)
        ).status_code
        == 422
    )


def test_custom_mail_honors_mailbox_hold(sending):
    from fmg_agent.email import safety

    app, client, owner, _, _ = sending
    result = client.post("/v1/email/previews", headers=headers(owner), json=payload())
    preview_id = result.json()["data"]["id"]
    with app.state.sessions() as session:
        safety.trip(session, "publisher@example.com", "manual_hold")
        session.commit()

    def transport(*args):
        pytest.fail("Paused custom mail reached transport")

    app.state.smtp_transport = transport
    assert (
        client.get("/v1/email/previews/" + preview_id, headers=headers(owner)).json()[
            "data"
        ]["send_ready"]
        is False
    )
    response = send(client, owner, preview_id)
    assert response.status_code >= 400
    assert "email_sender_paused" in response.text
