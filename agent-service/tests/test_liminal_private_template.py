"""A new sender must not rewrite, inherit, or impersonate the old identity."""

import pytest

from fmg_agent.email.templates import (
    check_mailbox_template,
    get_template,
    render_template,
)
from fmg_agent.errors import ApiError
from fmg_agent.mailboxes import MailboxProfile, MailboxRegistry
from test_email_sending import headers, sending, send
from test_liminal_fixed_copy import personalization


def test_private_liminal_preserves_copy_except_signature_email_without_images():
    old = render_template(get_template("liminal-outreach", "7"), personalization())
    new = render_template(
        get_template("liminal-private-outreach", "2"), personalization()
    )
    assert new == {
        "subject": old["subject"],
        "text": old["text"].replace(
            "OntologyPlay@hotmail.com", "liminal_within@ontologyplay.com"
        ),
        "format": "plain_text",
    }
    from fmg_agent.email.mime import build_message

    mail = build_message(
        dict(
            new, **{"from": "liminal_within@ontologyplay.com", "to": "test@example.com"}
        ),
        "no-send",
    )
    assert mail.get_content_type() == "text/plain"
    assert not mail.is_multipart()
    assert mail.get_content().strip() == new["text"]


def test_private_liminal_rejects_old_image_version_for_new_drafts():
    with pytest.raises(ApiError) as error:
        get_template("liminal-private-outreach", "1")
    assert error.value.code == "template_version_changed"


@pytest.mark.parametrize(
    "identity,address,allowed",
    [
        ("liminal", "liminal_within@ontologyplay.com", True),
        ("ontologyplay", "OntologyPlay@hotmail.com", False),
        ("second", "norestforthieves@ontologyplay.com", False),
        ("liminal", "wrong@example.com", False),
        ("other", "liminal_within@ontologyplay.com", False),
    ],
)
def test_private_template_checks_both_identity_and_address(identity, address, allowed):
    profile = MailboxProfile(
        id=identity, smtp_from=address, allowed_templates=["liminal-private-outreach"]
    )
    if allowed:
        check_mailbox_template(profile, "liminal-private-outreach")
    else:
        with pytest.raises(ApiError, match="not allowed"):
            check_mailbox_template(profile, "liminal-private-outreach")


def test_migration_preserves_old_draft_and_requires_new_approval(sending):
    app, client, owner, _, _ = sending
    old = MailboxProfile(
        id="ontologyplay",
        smtp_from="OntologyPlay@hotmail.com",
        allowed_templates=["liminal-outreach"],
    )
    app.state.mailboxes = MailboxRegistry(app.state.settings, [old], legacy=False)
    body = {
        "mailbox_id": "ontologyplay",
        "template_id": "liminal-outreach",
        "template_version": "7",
        "to": "alex@example.com",
        "variables": personalization(),
    }
    saved = client.post("/v1/email/previews", headers=headers(owner), json=body).json()[
        "data"
    ]
    new = MailboxProfile(
        id="liminal",
        smtp_from="liminal_within@ontologyplay.com",
        allowed_templates=["liminal-private-outreach"],
    )
    old.enabled = False
    app.state.mailboxes = MailboxRegistry(app.state.settings, [old, new], legacy=False)
    refreshed = client.get(
        "/v1/email/previews/" + saved["id"], headers=headers(owner)
    ).json()["data"]
    assert refreshed["message"] == saved["message"]
    assert refreshed["mailbox_id"] == "ontologyplay"
    assert refreshed["send_ready"] is False
    assert (
        send(client, owner, saved["id"]).json()["error"]["code"] == "mailbox_disabled"
    )
    response = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "new-liminal"),
        json={
            "name": "New LIMINAL review",
            "mailbox_id": "liminal",
            "template_id": "liminal-private-outreach",
            "template_version": "2",
            "recipients": [
                {
                    "creator_id": "alex",
                    "to": "alex@example.com",
                    "variables": personalization(),
                }
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["state"] == "awaiting_approval"
    assert data["recipients"][0]["message"]["from"] == "liminal_within@ontologyplay.com"
    from fmg_agent.email.models import EmailSend
    from sqlalchemy import select

    with app.state.sessions() as session:
        assert session.scalar(select(EmailSend)) is None
