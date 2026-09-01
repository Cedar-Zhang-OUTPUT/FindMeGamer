import json

import pytest
from pydantic import ValidationError

from app.schemas.ai_creator import (
    AudienceInference,
    CreatorMetadataAnalysis,
    CreatorSynthesis,
    CreatorVisualAnalysis,
)
from app.schemas.ai_game import GameExtraction, GameSynthesis, GameVisualAnalysis


def evidence(kind: str = "source_fact") -> list[dict[str, str]]:
    return [
        {
            "kind": kind,
            "source_type": "steam_field" if kind == "source_fact" else "visual_asset",
            "reference": "about_the_game" if kind == "source_fact" else "screenshot:0",
            "observation": "The supplied source directly supports this claim.",
        }
    ]


def text_claim(
    value: str = "A precise evidence-backed statement.",
) -> dict[str, object]:
    return {
        "status": "available",
        "value": value,
        "evidence": evidence(),
        "confidence": "high",
    }


def list_claim(*values: str) -> dict[str, object]:
    return {
        "status": "available",
        "values": list(values or ("Strategy",)),
        "evidence": evidence(),
        "confidence": "medium",
    }


def unavailable() -> dict[str, str]:
    return {"status": "unavailable", "reason": "The supplied evidence is silent."}


def game_extraction_payload() -> dict[str, object]:
    return {
        "english_language_check": True,
        "short_summary": text_claim(),
        "core_gameplay_loop": text_claim(),
        "themes": list_claim("Exploration"),
        "tone": list_claim("Reflective"),
        "target_audience": list_claim("Strategy players"),
        "key_selling_points": list_claim("Branching decisions"),
        "content_hooks": list_claim("Challenge runs"),
        "comparable_games": unavailable(),
        "suitable_creator_types": list_claim("Strategy essayists"),
        "promotion_risks": list_claim("Spoiler sensitivity"),
    }


def game_brief_payload() -> dict[str, object]:
    return {
        "positioning_premise": text_claim(),
        "core_gameplay_loop": text_claim(),
        "genres": list_claim("Strategy"),
        "themes": list_claim("Exploration"),
        "tone": list_claim("Reflective"),
        "visual_identity": text_claim(),
        "target_audience": list_claim("Strategy players"),
        "key_selling_points": list_claim("Branching decisions"),
        "content_hooks": list_claim("Challenge runs"),
        "comparable_games": unavailable(),
        "suitable_creator_types": list_claim("Strategy essayists"),
        "promotion_risks": list_claim("Spoiler sensitivity"),
    }


def game_synthesis_payload() -> dict[str, object]:
    payload = game_extraction_payload()
    payload["visual_style"] = text_claim()
    payload["game_brief"] = game_brief_payload()
    return payload


def contact(value: str, value_type: str) -> dict[str, object]:
    return {
        "status": "available",
        "value": value,
        "value_type": value_type,
        "source_reference": "channel.description",
        "validation_state": "validated",
    }


def audience_claim(value: str) -> dict[str, object]:
    return {
        "status": "available",
        "value": value,
        "provenance": "ai_inference",
        "evidence": [
            {
                "kind": "ai_inference",
                "source_type": "video_id",
                "reference": "video-1",
                "observation": "Repeated English titles support this cautious inference.",
            }
        ],
        "confidence": "low",
    }


def creator_synthesis_payload() -> dict[str, object]:
    return {
        "english_language_check": True,
        "content_summary": text_claim(),
        "primary_games": list_claim("Game A"),
        "genres": list_claim("Strategy"),
        "formats": list_claim("Long-form review"),
        "style": list_claim("Analytical"),
        "pacing": text_claim(),
        "production_quality": text_claim(),
        "livestream_tendency": text_claim(),
        "long_form_tendency": text_claim(),
        "short_form_tendency": text_claim(),
        "recent_performance_summary": text_claim(),
        "engagement_summary": text_claim(),
        "publishing_frequency_context": text_claim(),
        "representative_video_context": list_claim("video-1 is representative"),
        "sponsorship_patterns": list_claim("Clearly disclosed integrations"),
        "brand_safety": list_claim("No supplied metadata warning signals"),
        "suitable_game_types": list_claim("Strategy games"),
        "collaboration_risks": list_claim("Irregular cadence"),
        "audience_inference": {
            "primary_language": audience_claim("English"),
            "likely_regions": {
                "status": "available",
                "values": ["English-speaking markets"],
                "provenance": "ai_inference",
                "evidence": audience_claim("English")["evidence"],
                "confidence": "low",
            },
            "interests": {
                "status": "available",
                "values": ["Strategy games"],
                "provenance": "ai_inference",
                "evidence": audience_claim("English")["evidence"],
                "confidence": "medium",
            },
        },
        "public_email": contact("press@example.com", "email"),
        "linked_site": contact("https://creator.example/about", "url"),
        "social_links": {
            "status": "available",
            "values": [contact("https://social.example/creator", "url")],
        },
        "creator_brief": {
            "positioning": text_claim(),
            "content_focus": list_claim("Strategy games"),
            "formats": list_claim("Long-form review"),
            "style_and_pacing": text_claim(),
            "audience": text_claim(),
            "performance_context": text_claim(),
            "promotion_fit": text_claim(),
            "brand_safety": text_claim(),
            "suitable_game_types": list_claim("Strategy games"),
            "collaboration_risks": list_claim("Irregular cadence"),
        },
    }


@pytest.mark.parametrize(
    "schema,payload",
    [
        (GameExtraction, game_extraction_payload()),
        (GameSynthesis, game_synthesis_payload()),
        (CreatorSynthesis, creator_synthesis_payload()),
    ],
)
def test_stage_outputs_require_literal_english_attestation(schema, payload) -> None:
    schema.model_validate(payload)
    for invalid in (None, False, 1, "true"):
        changed = {**payload}
        if invalid is None:
            changed.pop("english_language_check")
        else:
            changed["english_language_check"] = invalid
        with pytest.raises(ValidationError):
            schema.model_validate(changed)


def test_creator_schema_requires_creator_brief() -> None:
    payload = creator_synthesis_payload()
    payload.pop("creator_brief")
    with pytest.raises(ValidationError):
        CreatorSynthesis.model_validate(payload)


def test_game_schema_requires_detailed_game_brief() -> None:
    payload = game_synthesis_payload()
    payload.pop("game_brief")
    with pytest.raises(ValidationError):
        GameSynthesis.model_validate(payload)


def test_available_claim_requires_evidence_and_unavailable_claim_rejects_value() -> (
    None
):
    payload = game_extraction_payload()
    payload["short_summary"] = {**text_claim(), "evidence": []}
    with pytest.raises(ValidationError):
        GameExtraction.model_validate(payload)

    payload["short_summary"] = {
        "status": "unavailable",
        "reason": "No evidence",
        "value": "Invented",
    }
    with pytest.raises(ValidationError):
        GameExtraction.model_validate(payload)


def test_evidence_references_reject_malformed_whitespace() -> None:
    payload = game_extraction_payload()
    claim = text_claim()
    claim["evidence"][0]["reference"] = "about_\n the_game"
    payload["short_summary"] = claim
    with pytest.raises(ValidationError):
        GameExtraction.model_validate(payload)


def test_visual_analysis_can_be_explicitly_unavailable_without_blocking_synthesis() -> (
    None
):
    visual = GameVisualAnalysis.model_validate(
        {
            "english_language_check": True,
            "status": "unavailable",
            "unavailable_reason": "Vision provider exhausted retries.",
            "visual_style": unavailable(),
            "visual_motifs": unavailable(),
            "readability": unavailable(),
            "content_hook_observations": unavailable(),
        }
    )
    synthesis = GameSynthesis.model_validate(game_synthesis_payload())
    assert visual.status == "unavailable"
    assert synthesis.game_brief.visual_identity.status == "available"


def test_available_visual_analysis_requires_visual_observation_evidence() -> None:
    payload = {
        "english_language_check": True,
        "status": "available",
        "unavailable_reason": None,
        "visual_style": text_claim(),
        "visual_motifs": list_claim("High contrast"),
        "readability": text_claim(),
        "content_hook_observations": list_claim("Readable action silhouettes"),
    }
    with pytest.raises(ValidationError):
        GameVisualAnalysis.model_validate(payload)

    for name in (
        "visual_style",
        "visual_motifs",
        "readability",
        "content_hook_observations",
    ):
        payload[name]["evidence"] = evidence("visual_observation")
    assert GameVisualAnalysis.model_validate(payload).status == "available"


def test_creator_visual_analysis_rejects_content_claims_and_supports_unavailable() -> (
    None
):
    result = CreatorVisualAnalysis.model_validate(
        {
            "english_language_check": True,
            "status": "unavailable",
            "unavailable_reason": "No thumbnails were available.",
            "visual_style": unavailable(),
            "production_quality_signals": unavailable(),
            "thumbnail_patterns": unavailable(),
            "thumbnail_readability": unavailable(),
            "branding": unavailable(),
        }
    )
    assert result.status == "unavailable"
    assert "video_content" not in CreatorVisualAnalysis.model_fields
    assert "audience_demographics" not in CreatorVisualAnalysis.model_fields


def test_audience_inference_is_always_labeled_and_evidence_backed() -> None:
    payload = creator_synthesis_payload()
    audience = payload["audience_inference"]
    audience["primary_language"].pop("provenance")
    with pytest.raises(ValidationError):
        CreatorSynthesis.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("public_email", contact("not-an-email", "email")),
        ("linked_site", contact("javascript:alert(1)", "url")),
        (
            "public_email",
            {
                "status": "available",
                "value": "press@example.com",
                "value_type": "email",
                "validation_state": "validated",
            },
        ),
    ],
)
def test_contact_values_require_exact_valid_value_and_source(field, value) -> None:
    payload = creator_synthesis_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        CreatorSynthesis.model_validate(payload)


def test_creator_output_excludes_repository_owned_and_match_fields() -> None:
    forbidden = {
        "manual_contact",
        "manual_notes",
        "favorite",
        "next_analysis_at",
        "model_identifier",
        "prompt_version",
        "match_brief",
    }
    assert forbidden.isdisjoint(CreatorSynthesis.model_fields)
    with pytest.raises(ValidationError):
        CreatorSynthesis.model_validate(
            {**creator_synthesis_payload(), "manual_notes": "Do not overwrite"}
        )


def test_creator_metadata_is_metadata_only_and_complete() -> None:
    expected = {
        "primary_games",
        "genres",
        "formats",
        "style",
        "pacing",
        "livestream_tendency",
        "long_form_tendency",
        "short_form_tendency",
        "recent_performance_summary",
        "engagement_summary",
        "publishing_frequency_context",
        "sponsorship_patterns",
        "brand_safety_signals",
        "collaboration_risks",
    }
    assert expected <= CreatorMetadataAnalysis.model_fields.keys()
    assert "transcript_analysis" not in CreatorMetadataAnalysis.model_fields


def test_all_stage_schemas_are_strict_frozen_bounded_and_json_round_trip() -> None:
    result = CreatorSynthesis.model_validate(creator_synthesis_payload())
    with pytest.raises(ValidationError):
        CreatorSynthesis.model_validate({**creator_synthesis_payload(), "score": 0.9})
    with pytest.raises(ValidationError):
        result.content_summary = result.content_summary

    encoded = result.model_dump_json()
    assert CreatorSynthesis.model_validate_json(encoded) == result
    schema_text = json.dumps(CreatorSynthesis.model_json_schema(), allow_nan=False)
    assert "additionalProperties" in schema_text
    assert "Any" not in schema_text


def test_string_and_collection_bounds_reject_controls_blanks_and_duplicates() -> None:
    for bad in (" ", "\x00", "x" * 4_001):
        payload = game_extraction_payload()
        payload["short_summary"] = text_claim(bad)
        with pytest.raises(ValidationError):
            GameExtraction.model_validate(payload)

    payload = game_extraction_payload()
    payload["themes"] = list_claim("Exploration", "Exploration")
    with pytest.raises(ValidationError):
        GameExtraction.model_validate(payload)


def test_audience_inference_schema_does_not_allow_numeric_confidence() -> None:
    payload = creator_synthesis_payload()["audience_inference"]
    payload["primary_language"]["confidence"] = 0.8
    with pytest.raises(ValidationError):
        AudienceInference.model_validate(payload)
