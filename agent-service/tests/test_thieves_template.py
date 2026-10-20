from base64 import b64decode
import hashlib

import pytest

from fmg_agent.email.templates import (
    check_mailbox_template,
    get_template,
    list_templates,
    render_template,
)
from fmg_agent.errors import ApiError
from fmg_agent.mailboxes import MailboxProfile
from test_email_sending import headers, sending


def personalization():
    return {
        "creator_name": "Alex",
        "channel_name": "Alex Plays",
        "reference_work": "Liar's Bar",
        "specific_observation": "Your focus on multiplayer bluffing fits this party game.",
    }


def test_thieves_render_preserves_pitch_and_complete_observation():
    rendered = render_template(get_template("thieves-outreach", "2"), personalization())
    assert rendered["subject"] == (
        "Demo Invitation: No rest for Thieves- A Loot-Splitting Party Game"
    )
    assert rendered["text"] == (
        "Hi Alex,\n\n"
        "I'm Michael from the team behind No Rest for Thieves, a four-player party game.\n\n"
        "I've been following Alex Plays, and I especially enjoyed your video on Liar's Bar. "
        "Your focus on multiplayer bluffing fits this party game. "
        "I think our game could be a fun fit for your channel!\n\n"
        "I'd love to invite you to try our demo, which is now available on Steam:\n\n"
        "Steam: https://store.steampowered.com/app/5124600/No_Rest_for_Thieves/\n\n"
        "About the Game\n\n"
        "No Rest for Thieves is a first-person party game for four players, inspired by "
        "the multiplayer trickery of Liar's Bar and the action mechanics of Party Animal.\n\n"
        "After a successful heist, split the loot—or steal your friends' shares! "
        "But beware: fall asleep, and you'll lose your money!\n\n"
        "Use crazy gadgets to stay awake and put your rivals to sleep. "
        "Whoever ends up with the most valuable loot wins!\n\n"
        "A Note from the Developers\n\n"
        "This is an early demo focused on our core gameplay mechanics, we are currently "
        "looking for honest feedback, not sponsored coverage or a guaranteed video. "
        "We'd love to hear what you think!\n\n"
        "If you decide to create any content, we'd love to know your planned release date "
        "and check out your video or stream once it's live.\n\n"
        "Thanks for your time, and hope you enjoy the demo!\n\n"
        "Best regards,\n\nMichael\nNo Rest for Thieves Team"
    )
    assert rendered["format"] == "signature_image"


def test_thieves_footer_is_last_and_mime_embeds_original_jpeg():
    # Missing/wrong image bytes, MIME type, CID or placement must break this test.
    from fmg_agent.email.mime import build_message

    rendered = render_template(get_template("thieves-outreach"), personalization())
    html = rendered["html"]
    assert html.index("Michael") < html.index('src="cid:thieves-game-banner"')
    assert html.count("<img ") == 1
    assert 'width="600"' in html and "max-width:100%;height:auto" in html
    assert html.endswith("</body></html>")
    assert "ontology-play-signature" not in html
    raw = b64decode(rendered["footer_jpeg_base64"], validate=True)
    assert (
        hashlib.sha256(raw).hexdigest()
        == "bf98277e4e89529f67fead5c6e53abaa2c9a467fdda90b9cba5f5d5a4fad264f"
    )
    mail = build_message(
        dict(
            rendered,
            **{"from": "norestforthieves@ontologyplay.com", "to": "test@example.com"},
        ),
        "test-no-send",
    )
    images = [part for part in mail.walk() if part.get_content_maintype() == "image"]
    assert len(images) == 1
    assert images[0].get_content_type() == "image/jpeg"
    assert images[0]["Content-ID"] == "<thieves-game-banner>"
    assert images[0].get_content_disposition() == "inline"
    assert images[0].get_payload(decode=True) == raw
    assert (
        mail.get_body(preferencelist=("plain",)).get_content().strip()
        == rendered["text"]
    )


def test_frozen_thieves_v1_plain_text_still_builds_without_image():
    from fmg_agent.email.mime import build_message

    frozen = {
        "format": "plain_text",
        "text": "Previously approved Michael pitch",
        "subject": "Previously approved subject",
        "from": "norestforthieves@ontologyplay.com",
        "to": "test@example.com",
    }
    mail = build_message(frozen, "old-preview-no-send")
    assert mail.get_content_type() == "text/plain"
    assert mail.get_content().strip() == frozen["text"]


def test_thieves_old_version_requires_new_preview_not_silent_rewrite():
    with pytest.raises(ApiError) as error:
        get_template("thieves-outreach", "1")
    assert error.value.code == "template_version_changed"


@pytest.mark.parametrize("field", list(personalization()))
def test_thieves_requires_each_personalization_field(field):
    values = personalization()
    del values[field]
    with pytest.raises(ApiError) as error:
        render_template(get_template("thieves-outreach", "2"), values)
    assert error.value.code == "template_variables_invalid"


def test_thieves_fixed_copy_cannot_be_overridden_by_extra_variables():
    with pytest.raises(ApiError) as error:
        render_template(
            get_template("thieves-outreach", "2"),
            dict(personalization(), game_name="Unapproved Game"),
        )
    assert error.value.code == "template_variables_invalid"


@pytest.mark.parametrize(
    "mailbox,sender,allowed",
    [
        ("ontologyplay", "ontologyplay@hotmail.com", ["thieves-outreach"]),
        ("second", "other@example.com", ["thieves-outreach"]),
        ("other", "norestforthieves@ontologyplay.com", ["thieves-outreach"]),
        ("second", "norestforthieves@ontologyplay.com", []),
    ],
)
def test_thieves_cannot_be_sent_by_wrong_mailbox_even_with_allowlist(
    mailbox, sender, allowed
):
    profile = MailboxProfile(id=mailbox, smtp_from=sender, allowed_templates=allowed)
    with pytest.raises(ApiError) as error:
        check_mailbox_template(profile, "thieves-outreach")
    assert error.value.code == "mailbox_template_not_allowed"


def test_thieves_second_mailbox_binding_and_catalog_coexist():
    profile = MailboxProfile(
        id="second",
        smtp_from="NoRestForThieves@OntologyPlay.com",
        allowed_templates=["thieves-outreach"],
    )
    check_mailbox_template(profile, "thieves-outreach")
    catalog = {row["id"]: row for row in list_templates()}
    assert catalog["thieves-outreach"]["version"] == "2"
    assert catalog["liminal-outreach"]["version"] == "7"
    assert catalog["game-outreach"]["version"] == "5"


def test_thieves_api_discovers_and_freezes_second_sender_without_sending(sending):
    from fmg_agent.mailboxes import MailboxRegistry
    from fmg_agent.email.models import EmailSend
    from sqlalchemy import select, func

    app, client, owner, _, reader = sending
    app.state.mailboxes = MailboxRegistry(
        app.state.settings,
        [
            MailboxProfile(
                id="second",
                smtp_from="norestforthieves@ontologyplay.com",
                display_name="No Rest for Thieves Team",
                allowed_templates=["thieves-outreach"],
            )
        ],
        legacy=False,
    )
    definition = client.get(
        "/v1/email/templates/thieves-outreach", headers=headers(reader)
    )
    assert definition.status_code == 200
    assert set(definition.json()["data"]["variables"]) == set(personalization())
    created = client.post(
        "/v1/email/previews",
        headers=headers(owner),
        json={
            "mailbox_id": "second",
            "template_id": "thieves-outreach",
            "template_version": "2",
            "to": "creator@example.com",
            "variables": personalization(),
        },
    )
    assert created.status_code == 201
    frozen = created.json()["data"]
    assert frozen["mailbox_id"] == "second"
    assert frozen["message"]["from"] == "norestforthieves@ontologyplay.com"
    assert frozen["message"]["from_name"] == "No Rest for Thieves Team"
    assert frozen["message"]["text"].endswith("Michael\nNo Rest for Thieves Team")
    assert frozen["message"]["footer_jpeg_base64"]
    assert 'src="cid:thieves-game-banner"' in frozen["message"]["html"]
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EmailSend)) == 0


def test_thieves_batch_omits_repeated_jpeg_but_individual_preview_keeps_it(sending):
    # Adding images must not grow a 50-recipient status response by ~13 MB.
    from fmg_agent.mailboxes import MailboxRegistry

    app, client, owner, _, _ = sending
    app.state.mailboxes = MailboxRegistry(
        app.state.settings,
        [
            MailboxProfile(
                id="second",
                smtp_from="norestforthieves@ontologyplay.com",
                display_name="No Rest for Thieves Team",
                allowed_templates=["thieves-outreach"],
            )
        ],
        legacy=False,
    )
    created = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "thieves-footer-compact"),
        json={
            "name": "Fifty image drafts",
            "mailbox_id": "second",
            "template_id": "thieves-outreach",
            "template_version": "2",
            "recipients": [
                {
                    "creator_id": f"creator-{i}",
                    "to": f"creator-{i}@example.com",
                    "variables": personalization(),
                }
                for i in range(50)
            ],
        },
    )
    assert created.status_code == 201
    assert len(created.content) < 1024 * 1024
    task = created.json()["data"]
    queried = client.get("/v1/outreach/tasks/" + task["id"], headers=headers(owner))
    assert queried.status_code == 200 and len(queried.content) < 1024 * 1024
    for recipient in queried.json()["data"]["recipients"]:
        assert "footer_jpeg_base64" not in recipient["message"]
        assert "cid:thieves-game-banner" in recipient["message"]["html"]
    full = client.get(
        "/v1/email/previews/" + task["recipients"][0]["preview_id"],
        headers=headers(owner),
    )
    assert full.status_code == 200
    raw = b64decode(full.json()["data"]["message"]["footer_jpeg_base64"])
    assert (
        hashlib.sha256(raw).hexdigest()
        == "bf98277e4e89529f67fead5c6e53abaa2c9a467fdda90b9cba5f5d5a4fad264f"
    )
