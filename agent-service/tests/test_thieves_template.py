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
    rendered = render_template(get_template("thieves-outreach", "3"), personalization())
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
    assert rendered["format"] == "plain_text"


def test_thieves_mime_is_only_plain_text_without_images():
    from fmg_agent.email.mime import build_message

    rendered = render_template(get_template("thieves-outreach"), personalization())
    assert set(rendered) == {"subject", "text", "format"}
    mail = build_message(
        dict(
            rendered,
            **{"from": "norestforthieves@ontologyplay.com", "to": "test@example.com"},
        ),
        "test-no-send",
    )
    assert mail.get_content_type() == "text/plain"
    assert not mail.is_multipart()
    assert mail.get_content().strip() == rendered["text"]


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


@pytest.mark.parametrize("version", ["1", "2"])
def test_thieves_old_version_requires_new_preview_not_silent_rewrite(version):
    with pytest.raises(ApiError) as error:
        get_template("thieves-outreach", version)
    assert error.value.code == "template_version_changed"


@pytest.mark.parametrize("field", list(personalization()))
def test_thieves_requires_each_personalization_field(field):
    values = personalization()
    del values[field]
    with pytest.raises(ApiError) as error:
        render_template(get_template("thieves-outreach", "3"), values)
    assert error.value.code == "template_variables_invalid"


def test_thieves_fixed_copy_cannot_be_overridden_by_extra_variables():
    with pytest.raises(ApiError) as error:
        render_template(
            get_template("thieves-outreach", "3"),
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
    assert catalog["thieves-outreach"]["version"] == "3"
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
            "template_version": "3",
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
    assert frozen["message"]["format"] == "plain_text"
    assert "html" not in frozen["message"]
    assert not any(key.endswith("_base64") for key in frozen["message"])
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EmailSend)) == 0


def test_thieves_batch_and_individual_preview_are_image_free(sending):
    # Both full previews and batch status must remain image-free.
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
            "name": "Fifty plain-text drafts",
            "mailbox_id": "second",
            "template_id": "thieves-outreach",
            "template_version": "3",
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
        assert "html" not in recipient["message"]
        assert recipient["message"]["format"] == "plain_text"
    full = client.get(
        "/v1/email/previews/" + task["recipients"][0]["preview_id"],
        headers=headers(owner),
    )
    assert full.status_code == 200
    message = full.json()["data"]["message"]
    assert message["format"] == "plain_text"
    assert "html" not in message
    assert not any(key.endswith("_base64") for key in message)
