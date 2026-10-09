"""The approved banner must survive previews, persistence and both mail transports."""

import base64
import hashlib
import time
from email import policy
from email.parser import BytesParser

import httpx

from fmg_agent.email.mime import build_message
from fmg_agent.email.templates import get_template, render_template
from test_email_sending import headers, sending
from test_liminal_fixed_copy import FIXED_BLOCK, personalization
from test_smtp_delivery import configuration, smtp_server
from test_graph_mail import graph_settings, graph_seed


BANNER_SHA256 = "659f2546794346a25e7d670db353e573bb88e62718a0a2a27d32edae5753b7bd"


def assert_banner_mail(parsed):
    html = parsed.get_body(preferencelist=("html",)).get_content()
    assert html.index('src="cid:ontology-play-signature"') < html.index(
        'src="cid:liminal-game-banner"'
    )
    pictures = [p for p in parsed.walk() if p.get_content_type() == "image/png"]
    assert [p["Content-ID"] for p in pictures] == [
        "<ontology-play-signature>",
        "<liminal-game-banner>",
    ]
    assert all(p.get_content_disposition() == "inline" for p in pictures)
    assert (
        hashlib.sha256(pictures[1].get_payload(decode=True)).hexdigest()
        == BANNER_SHA256
    )
    assert (
        parsed.get_body(preferencelist=("plain",))
        .get_content()
        .replace("\r\n", "\n")
        .strip()
        .endswith(FIXED_BLOCK)
    )


def test_liminal_banner_follows_existing_signature_without_changing_copy():
    message = render_template(get_template("liminal-outreach"), personalization())
    assert message["text"].split("\n\n", 2)[2] == FIXED_BLOCK
    assert (
        message["subject"]
        == "Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG"
    )
    assert message["html"].index("cid:ontology-play-signature") < message["html"].index(
        "cid:liminal-game-banner"
    )
    assert (
        hashlib.sha256(
            base64.b64decode(message["footer_png_base64"], validate=True)
        ).hexdigest()
        == BANNER_SHA256
    )
    message.update({"from": "publisher@example.com", "to": "creator@example.com"})
    assert_banner_mail(
        BytesParser(policy=policy.default).parsebytes(
            build_message(message, "banner").as_bytes(policy=policy.SMTP)
        )
    )


def test_liminal_banner_is_in_smtp_delivery(tmp_path, smtp_server):
    from fmg_agent.email.smtp import deliver

    message = render_template(get_template("liminal-outreach"), personalization())
    message.update({"from": "publisher@example.com", "to": "creator@example.com"})
    assert (
        deliver(configuration(tmp_path, smtp_server), message, "banner")["state"]
        == "sent"
    )
    assert len(smtp_server.messages) == 1
    assert_banner_mail(
        BytesParser(policy=policy.default).parsebytes(smtp_server.messages[0])
    )


def test_liminal_banner_is_in_graph_payload(tmp_path):
    from fmg_agent.email.graph import deliver

    settings = graph_settings(tmp_path)
    graph_seed(settings, time.time() + 3600)
    message = render_template(get_template("liminal-outreach"), personalization())
    message.update({"from": settings.smtp_from, "to": "creator@example.com"})
    received = []

    def respond(req):
        assert req.url == "https://graph.microsoft.com/v1.0/me/sendMail"
        received.append(
            BytesParser(policy=policy.default).parsebytes(
                base64.b64decode(req.content, validate=True)
            )
        )
        return httpx.Response(202)

    assert (
        deliver(settings, message, "banner", transport=httpx.MockTransport(respond))[
            "state"
        ]
        == "sent"
    )
    assert len(received) == 1
    assert_banner_mail(received[0])


def test_old_liminal_snapshot_keeps_single_image_new_task_has_banner(
    sending, monkeypatch
):
    import fmg_agent.email.sending as store
    from fmg_agent.outreach import pending

    app, client, owner, _, _ = sending
    old = dict(get_template("liminal-outreach"))
    old.pop("footer_image", None)
    old["version"] = "6"
    with monkeypatch.context() as patch:
        patch.setattr(store, "get_template", lambda *args: old)
        response = client.post(
            "/v1/email/previews",
            headers=headers(owner),
            json={
                "template_id": "liminal-outreach",
                "template_version": "6",
                "to": "creator@example.com",
                "variables": personalization(),
            },
        )
    assert response.status_code == 201
    saved = response.json()["data"]
    assert "footer_png_base64" not in saved["message"]
    old_mime = build_message(saved["message"], "old-banner")
    assert (
        len(
            [part for part in old_mime.walk() if part.get_content_type() == "image/png"]
        )
        == 1
    )
    task = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "banner-task"),
        json={
            "name": "LIMINAL banner review",
            "template_id": "liminal-outreach",
            "template_version": "7",
            "recipients": [
                {
                    "creator_id": "youtube:creator",
                    "to": "creator@example.com",
                    "variables": personalization(),
                }
            ],
        },
    )
    assert task.status_code == 201
    assert task.json()["data"]["state"] == "awaiting_approval"
    message = task.json()["data"]["recipients"][0]["message"]
    assert (
        hashlib.sha256(base64.b64decode(message["footer_png_base64"])).hexdigest()
        == BANNER_SHA256
    )
    assert (
        client.get("/v1/email/previews/" + saved["id"], headers=headers(owner)).json()[
            "data"
        ]
        == saved
    )
    assert pending(app.state.sessions) == []


def test_generic_template_does_not_inherit_liminal_banner():
    from test_unified_template import unified_values

    message = render_template(get_template("game-outreach", "5"), unified_values())
    assert "footer_png_base64" not in message
    assert "liminal-game-banner" not in message["html"]
    message.update({"from": "publisher@example.com", "to": "creator@example.com"})
    pictures = [
        part
        for part in build_message(message, "generic").walk()
        if part.get_content_type() == "image/png"
    ]
    assert [part["Content-ID"] for part in pictures] == ["<ontology-play-signature>"]
