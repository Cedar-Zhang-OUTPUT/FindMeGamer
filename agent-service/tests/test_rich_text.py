from email import policy
from email.parser import BytesParser

from fmg_agent.email.formatting import format_body
from fmg_agent.email.mime import build_message
from test_email_sending import sending, headers, send
from test_email_templates import variables


def test_safe_formatting_and_mime_roundtrip():
    source = "こんにちは **太字** ==**重要**== ~~old~~\n<script>alert(1)</script>"
    message = format_body({"text": source}, "markdown")
    assert "<strong>太字</strong>" in message["html"]
    assert "<strong>重要</strong></span>" in message["html"]
    assert "<script>" not in message["html"]
    assert message["text"] == "こんにちは 太字 重要 old\n<script>alert(1)</script>"
    message.update({"from": "a@example.com", "to": "b@example.com", "subject": "Test"})
    parsed = BytesParser(policy=policy.default).parsebytes(
        build_message(message, "test").as_bytes()
    )
    assert (
        parsed.get_body(preferencelist=("html",)).get_content().strip()
        == message["html"]
    )
    assert (
        parsed.get_body(preferencelist=("plain",)).get_content().strip()
        == message["text"]
    )


def test_plain_text_is_opt_in():
    message = {"text": "**literal** ==literal==", "format": "plain_text"}
    assert format_body(message) == message


def test_preview_freezes_both_formats(sending):
    app, client, owner, _, _ = sending
    values = variables()
    values["creator_name"] = "**Creator**"
    response = client.post(
        "/v1/email/previews",
        headers=headers(owner),
        json={
            "template_id": "game-outreach",
            "template_version": "5",
            "variables": values,
            "to": "creator@example.com",
            "body_format": "markdown",
        },
    )
    assert response.status_code == 201, response.text
    message = response.json()["data"]["message"]
    assert message["body_format"] == "markdown"
    assert "<strong>Creator</strong>" in message["html"]
    assert "**Creator**" not in message["text"]

    delivered = []

    def transport(config, frozen, send_id):
        delivered.append(frozen)
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    result = send(client, owner, response.json()["data"]["id"])
    assert result.status_code == 200, result.text
    assert delivered == [message]
