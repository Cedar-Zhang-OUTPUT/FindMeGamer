from app.outreach.locked_templates import render_locked


def test_game_template_uses_only_selected_facts_and_keeps_four_slots():
    from app.outreach.game_template import game_template

    spec = game_template(
        {
            "id": "game-a",
            "revision": 2,
            "name": "Quiet <Forest>",
            "website_url": "https://example.com/forest",
            "description": "Explore a peaceful forest.",
            "reference_works": [],
        },
        sender_name="Alex",
    )
    result = render_locked(
        spec["subject"],
        spec["fixed_fragments"],
        {
            "firstName": "Pat",
            "channelName": "Pat Plays",
            "reference": "Forest video",
            "observation": "explored the hidden trail.",
        },
        spec["fixed_hash"],
    )
    assert "Quiet <Forest>" in result["text"]
    assert "Quiet &lt;Forest&gt;" in result["html"]
    assert "Explore a peaceful forest." in result["text"]
    assert "https://example.com/forest" in result["text"]
    assert all(
        word not in result["text"]
        for word in (
            "LIMINAL",
            "Dispatch",
            "PARANORMASIGHT",
            "Toki",
            "Hong Kong",
            "demo is now available",
        )
    )
    assert spec["source_metadata"]["game_id"] == "game-a"
    assert spec["source_metadata"]["kind"] == "game_bound"


def test_missing_game_fields_are_not_invented_and_version_changes_with_facts():
    from app.outreach.game_template import game_template

    data = {"id": "game-b", "revision": 0, "name": "New Game", "reference_works": []}
    first = game_template(data, sender_name="Alex")
    assert "interactive film" not in "".join(first["fixed_fragments"])
    second = game_template(
        data | {"description": "A puzzle adventure.", "revision": 1}, sender_name="Alex"
    )
    assert first["fixed_hash"] != second["fixed_hash"]
    assert first == game_template(data, sender_name="Alex")
