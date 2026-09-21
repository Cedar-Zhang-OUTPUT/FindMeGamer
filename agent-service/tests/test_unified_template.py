from pathlib import Path
import pytest
from fmg_agent.email.templates import get_template, list_templates, render_template
from fmg_agent.errors import ApiError


def unified_values(game="It Takes Two"):
    return dict(creator_name="Alex", channel_name="Example Channel",
                reference_work="A Way Out", specific_observation="Your co-op coverage could make this a relevant fit.",
                game_name=game, game_tagline="a cooperative adventure",
                game_summary="A story-driven adventure for two players.",
                gameplay_summary="Players coordinate complementary abilities to progress.",
                availability_statement="See the current availability on the linked store page.",
                game_url="https://store.steampowered.com/app/1426210/")


def test_catalog_has_one_cross_game_template():
    assert [t["id"] for t in list_templates()] == ["game-outreach"]


@pytest.mark.parametrize("game", ["It Takes Two", "GTA VI"])
def test_unified_copy_uses_only_current_game_facts(game):
    rendered = render_template(get_template("game-outreach", "4"), unified_values(game))
    assert rendered["subject"].startswith("Internal Test — Thought you might enjoy " + game)
    assert game in rendered["text"]
    for stale in ("LIMINAL", "Dispatch", "PARANORMASIGHT", "Demo:", "demo is now available", "I liked how you"):
        assert stale not in rendered["text"]
    assert "enjoyed your content on A Way Out. Your co-op coverage" in rendered["text"]
    assert rendered["format"] == "signature_image"


def test_legacy_template_cannot_silently_generate_different_copy():
    with pytest.raises(ApiError):
        get_template("liminal-outreach", "4")
    with pytest.raises(ApiError):
        get_template("game-outreach", "3")


def test_skill_full_copy_matches_server_template():
    root = Path(__file__).resolve().parents[2]
    template = get_template("game-outreach")
    for skill in ("fmg-api", "fmg-research"):
        document = (root / "skills" / skill / "references" / "email-template.md").read_text()
        assert template["subject"] in document
        assert template["text"] in document
