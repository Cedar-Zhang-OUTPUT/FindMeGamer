def test_plan_uses_game_keywords_and_alternative_comparables():
    from app.discovery.planning import build_plan

    queries = build_plan(
        {
            "name": "New Game",
            "brief": {
                "genres": {"values": ["Horror"]},
                "comparable_games": {"values": ["Old One", "Old Two"]},
            },
        },
        "speedrun",
    )
    assert any("New Game" in q and "speedrun" in q for q in queries)
    assert any("Horror" in q for q in queries)
    assert all(not ("Old One" in q and "Old Two" in q) for q in queries)
    assert len(queries) <= 3
