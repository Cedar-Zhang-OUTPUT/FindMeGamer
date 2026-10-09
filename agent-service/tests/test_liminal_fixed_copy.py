"""The approved LIMINAL block is server-owned, not Agent-supplied game facts."""

import pytest

from fmg_agent.email.templates import get_template, render_template
from fmg_agent.errors import ApiError
from test_email_sending import headers, sending
from test_unified_template import unified_values


FIXED_BLOCK = """I’m reaching out because I’d love to invite you to try our game, LIMINAL: Within. The demo is now available on Steam, and you can download it here:

Demo: https://store.steampowered.com/app/4952700/_/

LIMINAL: Within is a mix of interactive film and retro pixel-art RPG adventure, which is a pretty unusual combination. In terms of format, it is closest to Dispatch, while its story and subject matter are closer to PARANORMASIGHT: The Seven Mysteries of Honjo. The story follows an investigation into a series of murders, unfolding through multiple characters and interconnected storylines as the player is gradually led toward the truth.

The gameplay combines cinematic storytelling with branching choices and QTEs, as well as a substantial pixel-art RPG adventure that lets you step into and explore another part of the story.

If you enjoy the game and think it would be a good fit for your audience, we’d love to see you share it on your channel in whatever format feels natural to you—whether that’s a video, a livestream, or even a short mention. There is absolutely no obligation to cover it, though; we’d simply be happy for you to try it, and any feedback would already mean a lot to us. If you have any trouble accessing the demo, just let me know.

Thanks for your time, and for the work you put into your channel.

Kind regards,

Toki Yuan
Game Producer, Ontology Play
Email: OntologyPlay@hotmail.com"""


def personalization(name="Alex"):
    return {
        "creator_name": name,
        "channel_name": "Story Channel",
        "reference_work": "PARANORMASIGHT",
        "specific_observation": "Its interwoven mystery could connect with the narrative focus of your coverage.",
    }


@pytest.mark.parametrize("name", ["Alex", "StoryChannel"])
def test_liminal_personalization_cannot_change_approved_game_block(name):
    message = render_template(
        get_template("liminal-outreach", "6"), personalization(name)
    )
    assert message["text"].startswith(f"Hi {name},\n\nI’m Toki")
    assert message["text"].split("\n\n", 2)[2] == FIXED_BLOCK
    assert (
        message["subject"]
        == "Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG"
    )
    assert message["format"] == "signature_image"
    assert "cid:ontology-play-signature" in message["html"]
    assert "YES, I'm in" not in message["text"]


@pytest.mark.parametrize(
    "field", ["game_name", "game_download_url", "game_summary", "game_url"]
)
def test_liminal_rejects_game_fact_overrides(field):
    with pytest.raises(ApiError) as error:
        render_template(
            get_template("liminal-outreach", "6"),
            {**personalization(), field: "replacement"},
        )
    assert error.value.code == "template_variables_invalid"


def test_legacy_liminal_version_is_not_reactivated():
    with pytest.raises(ApiError) as error:
        get_template("liminal-outreach", "4")
    assert error.value.code == "template_version_changed"


def test_liminal_task_preview_does_not_send_or_rewrite_generic_draft(sending):
    from fmg_agent.outreach import pending

    app, client, owner, _, _ = sending
    original = client.post(
        "/v1/email/previews",
        headers=headers(owner),
        json={
            "template_id": "game-outreach",
            "template_version": "5",
            "to": "alex@example.com",
            "variables": unified_values(),
        },
    )
    assert original.status_code == 201
    saved = original.json()["data"]
    task_response = client.post(
        "/v1/outreach/tasks",
        headers=headers(owner, "liminal-fixed-copy"),
        json={
            "name": "LIMINAL draft review",
            "template_id": "liminal-outreach",
            "template_version": "6",
            "recipients": [
                {
                    "creator_id": "youtube:alex",
                    "to": "alex@example.com",
                    "variables": personalization(),
                }
            ],
        },
    )
    assert task_response.status_code == 201
    task = task_response.json()["data"]
    assert task["state"] == "awaiting_approval"
    assert task["recipients"][0]["message"]["text"].endswith(FIXED_BLOCK)
    assert pending(app.state.sessions) == []
    reread = client.get("/v1/email/previews/" + saved["id"], headers=headers(owner))
    assert reread.status_code == 200
    assert reread.json()["data"] == saved
