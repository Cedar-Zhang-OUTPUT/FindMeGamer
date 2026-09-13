from app.outreach.prefill import (
    metadata_observation,
    choose_prefill_work,
    work_observation,
)


def test_metadata_suggestion_names_its_actual_source_not_video_viewing():
    result = metadata_observation(
        "A quiet station", "Exploring a pixel mystery", "https://example.com/video"
    )
    assert result["evidence_kind"] == "metadata"
    assert result["source_field"] == "description"
    assert (
        "description" in result["text"]
        and "Exploring a pixel mystery" in result["text"]
    )
    assert "watched" not in result["text"]
    assert (
        metadata_observation("A title", "", "https://example.com/video")["source_field"]
        == "title"
    )


def test_prefill_prefers_game_reference_and_verified_note_without_promoting_metadata():
    other = {
        "id": "a",
        "content_title": "Other game",
        "source_url": "https://example.com/a",
    }
    related = {
        "id": "b",
        "content_title": "LIMINAL full playthrough",
        "source_url": "https://example.com/b",
    }
    assert choose_prefill_work([other, related], {"name": "LIMINAL"}, []) == related
    note = other | {
        "evidence_excerpt": "A recorded scene",
        "verification_notes": "Viewed manually",
    }
    assert choose_prefill_work([related, note], {"name": "LIMINAL"}, []) == note
    assert "viewing notes" in work_observation(note)


def test_unsafe_or_empty_source_does_not_produce_fabricated_slot_text():
    assert (
        metadata_observation("<script>bad</script>", "", "https://example.com")["text"]
        == ""
    )
    assert work_observation({}) == ""
