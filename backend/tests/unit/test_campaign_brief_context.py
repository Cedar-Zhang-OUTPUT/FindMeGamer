from app.discovery.evaluation_snapshot import game_brief, game_data
from app.discovery.planning import generate_plan
from app.schemas.discovery_plan_output import SearchPlanOutput


def test_campaign_intent_is_separate_from_facts_and_passed_to_planning():
    captured = []

    class Gateway:
        def complete_structured(self, model, messages, schema, **kwargs):
            captured.extend(messages)
            return SearchPlanOutput(
                summary="Known title.",
                rationale="Requested creator fit.",
                queries=[{"platform": "youtube", "terms": ["puzzle"]}],
            )

    snapshot = {
        "game": {"name": "Known title"},
        "campaign_brief": "Prefer puzzle reviewers; huge marketing claims are not verified.",
    }
    generate_plan(
        snapshot, {"platforms": ["youtube"]}, gateway=Gateway(), model="synthetic"
    )
    assert "Prefer puzzle reviewers" in captured[1].content
    assert "not evidence" in captured[0].content
    assert "campaign_brief" not in game_data(snapshot)["game"]
    brief = game_brief(snapshot)
    assert brief["campaign_intent"]["text"] == snapshot["campaign_brief"]
    assert brief["campaign_intent"]["is_verified_fact"] is False
