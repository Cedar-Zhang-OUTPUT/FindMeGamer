from app.outreach.evidence import choose_recorded_work


def work(key, relation, recorded=True):
    return {
        "id": key,
        "relation": relation,
        "source_url": "https://example.com/" + key,
        "evidence_excerpt": "Recorded scene" if recorded else None,
        "verification_notes": "Operator checked source" if recorded else None,
    }


def test_current_game_recording_precedes_reference_and_selected_related_content():
    related = work("related", "related_content")
    reference = work("reference", "reference_game")
    current = work("current", "current_game")
    assert choose_recorded_work([related, reference, current]) == current


def test_metadata_only_current_game_does_not_displace_verified_reference():
    reference = work("reference", "reference_game")
    assert (
        choose_recorded_work(
            [
                work("current", "current_game", False),
                work("related", "related_content"),
                reference,
            ]
        )
        == reference
    )


def test_related_recorded_content_is_last_resort_and_missing_source_is_not_evidence():
    related = work("related", "related_content")
    invalid = work("current", "current_game") | {"source_url": None}
    assert choose_recorded_work([invalid, related]) == related
    assert choose_recorded_work([invalid]) is None


def test_same_tier_preserves_explicit_operator_order():
    first, second = work("first", "current_game"), work("second", "current_game")
    assert choose_recorded_work([first, second]) == first
