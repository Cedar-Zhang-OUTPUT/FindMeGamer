from types import SimpleNamespace
from app.discovery.evidence_priority import match_priority, ordered_items


SOURCE = {"game": {"id": "selected-game"}, "references": [{"name": "Reference Game"}]}


def test_matching_keeps_type_related_creator_without_selected_or_recorded_works():
    assert match_priority({"works": []}, SOURCE) == 2
    assert match_priority({"works": [{"game_id": "selected-game"}]}, SOURCE) == 2


def test_actual_linked_game_works_precede_reference_then_type_fit_without_viewing_claim():
    current = {
        "works": [
            {"game_id": "selected-game", "source_url": "https://example.com/current"}
        ]
    }
    reference = {
        "works": [
            {
                "work_name": "Reference Game",
                "source_url": "https://example.com/reference",
            }
        ]
    }
    assert match_priority(current, SOURCE) == 0
    assert match_priority(reference, SOURCE) == 1
    rows = [
        SimpleNamespace(snapshot={}, score=99, input_order=0),
        SimpleNamespace(snapshot=reference, score=90, input_order=1),
        SimpleNamespace(snapshot=current, score=75, input_order=2),
    ]
    assert ordered_items(rows, SOURCE) == [rows[2], rows[1], rows[0]]
    assert len(ordered_items(rows, SOURCE)) == 3


def test_unranked_current_game_remains_after_scored_type_candidate():
    pending = SimpleNamespace(
        snapshot={"match_priority": "current_game_work"}, score=None, input_order=0
    )
    scored = SimpleNamespace(snapshot={}, score=80, input_order=1)
    assert ordered_items([pending, scored], SOURCE) == [scored, pending]
