from uuid import uuid4

from app.schemas.profiles import GameProfileDetail


def test_profile_response_schema_sanitizes_json_without_route_helpers() -> None:
    detail = GameProfileDetail(
        id=uuid4(),
        name="Schema Boundary",
        steam_app_id="schema-boundary",
        canonical_url="https://store.steampowered.com/app/schema-boundary",
        favorite=False,
        current_facts={
            "name": "Schema Boundary",
            "api_secret": "never-return-secret",
        },
        brief={"summary": "Public", "hidden_rank": 1},
        source_status={"steam": {"status": "current"}},
        last_analyzed_at=None,
        next_analysis_at=None,
        analysis={"match_result": {"score": 0.99, "reasons": ["Fit"]}},
        model_metadata={"analysis_model": "test-model"},
        prompt_metadata={"version": "game-v1", "id_token": "never-return-token"},
    )

    assert detail.current_facts == {"name": "Schema Boundary"}
    assert detail.brief == {"summary": "Public"}
    assert detail.analysis == {"match_result": {"reasons": ["Fit"]}}
    assert detail.prompt_metadata == {"version": "game-v1"}
