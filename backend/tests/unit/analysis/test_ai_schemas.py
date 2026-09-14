import json

import pytest
from pydantic import ValidationError

from app.schemas.ai_creator import (
    AudienceInference,
    bind_creator_contacts,
    CreatorContactEvidence,
    CreatorBrief,
    CreatorMetadataAnalysis,
    CreatorSynthesis,
    CreatorVisualAnalysis,
    MAX_CREATOR_BRIEF_JSON_BYTES,
)
from app.schemas.ai_game import (
    GameBrief,
    GameExtraction,
    GameSynthesis,
    GameVisualAnalysis,
    MAX_GAME_BRIEF_JSON_BYTES,
    MAX_SCREENING_PROMPT_OVERHEAD_BYTES,
)


def evidence(
    kind: str = "source_fact",
    source_type: str | None = None,
    reference: str | None = None,
) -> list[dict[str, str]]:
    resolved_source = source_type or (
        "steam_field" if kind == "source_fact" else "visual_asset"
    )
    resolved_reference = reference or (
        "steam:about_the_game" if kind == "source_fact" else "screenshot:0"
    )
    return [
        {
            "kind": kind,
            "source_type": resolved_source,
            "reference": resolved_reference,
            "observation": "The supplied source directly supports this claim.",
        }
    ]


def text_claim(
    value: str = "A precise evidence-backed statement.",
    *,
    claim_evidence: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "status": "available",
        "value": value,
        "evidence": claim_evidence or evidence(),
        "confidence": "high",
    }


def list_claim(
    *values: str,
    claim_evidence: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "status": "available",
        "values": list(values or ("Strategy",)),
        "evidence": claim_evidence or evidence(),
        "confidence": "medium",
    }


def unavailable() -> dict[str, str]:
    return {"status": "unavailable", "reason": "The supplied evidence is silent."}


def compact_evidence(
    kind: str = "source_fact",
    source_type: str | None = None,
    reference: str | None = None,
) -> list[dict[str, str]]:
    resolved_source = source_type or (
        "steam_field" if kind == "source_fact" else "video_id"
    )
    resolved_reference = reference or (
        "steam:about_the_game" if kind == "source_fact" else "video:video-1"
    )
    return [
        {
            "kind": kind,
            "source_type": resolved_source,
            "reference": resolved_reference,
        }
    ]


def compact_text_claim(
    value: str = "A compact evidence-backed summary.",
    *,
    claim_evidence: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "status": "available",
        "value": value,
        "evidence": claim_evidence or compact_evidence(),
        "confidence": "high",
    }


def compact_list_claim(
    *values: str,
    claim_evidence: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "status": "available",
        "values": list(values or ("Strategy",)),
        "evidence": claim_evidence or compact_evidence(),
        "confidence": "medium",
    }


def compact_inference_claim(value: str = "English-speaking strategy viewers") -> dict:
    return {
        "status": "available",
        "value": value,
        "provenance": "ai_inference",
        "evidence": compact_evidence("ai_inference"),
        "confidence": "low",
    }


def creator_text_claim(value: str = "A creator metadata statement.") -> dict:
    return text_claim(
        value,
        claim_evidence=evidence("source_fact", "video_id", "video:video-1"),
    )


def creator_list_claim(*values: str) -> dict:
    return list_claim(
        *values,
        claim_evidence=evidence("source_fact", "video_id", "video:video-1"),
    )


def creator_compact_text_claim(value: str = "A compact creator summary.") -> dict:
    return compact_text_claim(
        value,
        claim_evidence=compact_evidence("source_fact", "video_id", "video:video-1"),
    )


def creator_compact_list_claim(*values: str) -> dict:
    return compact_list_claim(
        *values,
        claim_evidence=compact_evidence("source_fact", "video_id", "video:video-1"),
    )


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
        "positioning_premise": compact_text_claim(),
        "core_gameplay_loop": compact_text_claim(),
        "genres": compact_list_claim("Strategy"),
        "themes": compact_list_claim("Exploration"),
        "tone": compact_list_claim("Reflective"),
        "visual_identity": compact_text_claim(),
        "target_audience": compact_list_claim("Strategy players"),
        "key_selling_points": compact_list_claim("Branching decisions"),
        "content_hooks": compact_list_claim("Challenge runs"),
        "comparable_games": unavailable(),
        "suitable_creator_types": compact_list_claim("Strategy essayists"),
        "promotion_risks": compact_list_claim("Spoiler sensitivity"),
    }


def game_synthesis_payload() -> dict[str, object]:
    payload = game_extraction_payload()
    payload["visual_style"] = text_claim()
    payload["game_brief"] = game_brief_payload()
    return payload


def contact_evidence() -> CreatorContactEvidence:
    return CreatorContactEvidence.model_validate(
        {
            "candidates": [
                {
                    "candidate_id": "contact.email.0",
                    "kind": "email",
                    "value": "press@example.com",
                    "source_type": "channel_description",
                    "source_url": "https://youtube.com/channel/UC123",
                    "validation_state": "validated",
                },
                {
                    "candidate_id": "contact.site.0",
                    "kind": "linked_site",
                    "value": "https://creator.example/about",
                    "source_type": "linked_public_page",
                    "source_url": "https://creator.example/about",
                    "validation_state": "validated",
                },
                {
                    "candidate_id": "contact.social.0",
                    "kind": "social_link",
                    "value": "https://social.example/creator",
                    "source_type": "linked_public_page",
                    "source_url": "https://creator.example/about",
                    "validation_state": "unvalidated",
                },
            ]
        }
    )


def audience_claim(value: str) -> dict[str, object]:
    return {
        "status": "available",
        "value": value,
        "provenance": "ai_inference",
        "evidence": [
            {
                "kind": "ai_inference",
                "source_type": "video_id",
                "reference": "video:video-1",
                "observation": "Repeated English titles support this cautious inference.",
            }
        ],
        "confidence": "low",
    }


def creator_synthesis_payload() -> dict[str, object]:
    return {
        "english_language_check": True,
        "content_summary": creator_text_claim(),
        "primary_games": creator_list_claim("Game A"),
        "genres": creator_list_claim("Strategy"),
        "formats": creator_list_claim("Long-form review"),
        "style": creator_list_claim("Analytical"),
        "pacing": creator_text_claim(),
        "production_quality": creator_text_claim(),
        "livestream_tendency": creator_text_claim(),
        "long_form_tendency": creator_text_claim(),
        "short_form_tendency": creator_text_claim(),
        "recent_performance_summary": creator_text_claim(),
        "engagement_summary": creator_text_claim(),
        "publishing_frequency_context": creator_text_claim(),
        "representative_video_context": creator_list_claim("video-1 is representative"),
        "sponsorship_patterns": creator_list_claim("Clearly disclosed integrations"),
        "brand_safety": creator_list_claim("No supplied metadata warning signals"),
        "suitable_game_types": creator_list_claim("Strategy games"),
        "collaboration_risks": creator_list_claim("Irregular cadence"),
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
        "public_email": {"status": "available", "candidate_id": "contact.email.0"},
        "linked_site": {"status": "available", "candidate_id": "contact.site.0"},
        "social_links": {
            "status": "available",
            "candidate_ids": ["contact.social.0"],
        },
        "creator_brief": {
            "positioning": creator_compact_text_claim(),
            "content_focus": creator_compact_list_claim("Strategy games"),
            "formats": creator_compact_list_claim("Long-form review"),
            "style_and_pacing": creator_compact_text_claim(),
            "audience": compact_inference_claim(),
            "performance_context": creator_compact_text_claim(),
            "promotion_fit": creator_compact_text_claim(),
            "brand_safety": creator_compact_text_claim(),
            "suitable_game_types": creator_compact_list_claim("Strategy games"),
            "collaboration_risks": creator_compact_list_claim("Irregular cadence"),
        },
    }


def game_visual_unavailable_payload() -> dict[str, object]:
    return {
        "english_language_check": True,
        "status": "unavailable",
        "unavailable_reason": "Vision provider exhausted retries.",
        "visual_style": unavailable(),
        "visual_motifs": unavailable(),
        "readability": unavailable(),
        "content_hook_observations": unavailable(),
    }


def creator_metadata_unavailable_payload() -> dict[str, object]:
    return {
        "english_language_check": True,
        **{
            field: unavailable()
            for field in CreatorMetadataAnalysis.model_fields
            if field != "english_language_check"
        },
    }


def creator_visual_unavailable_payload() -> dict[str, object]:
    return {
        "english_language_check": True,
        "status": "unavailable",
        "unavailable_reason": "No thumbnails were available.",
        "visual_style": unavailable(),
        "production_quality_signals": unavailable(),
        "thumbnail_patterns": unavailable(),
        "thumbnail_readability": unavailable(),
        "branding": unavailable(),
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


@pytest.mark.parametrize(
    ("schema", "claim_fields"),
    [
        (
            GameVisualAnalysis,
            (
                "visual_style",
                "visual_motifs",
                "readability",
                "content_hook_observations",
            ),
        ),
        (
            CreatorVisualAnalysis,
            (
                "visual_style",
                "production_quality_signals",
                "thumbnail_patterns",
                "thumbnail_readability",
                "branding",
            ),
        ),
    ],
)
def test_available_visual_stage_requires_at_least_one_available_claim(
    schema, claim_fields
) -> None:
    payload = {
        "english_language_check": True,
        "status": "available",
        "unavailable_reason": None,
        **{field: unavailable() for field in claim_fields},
    }
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


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


def test_contact_evidence_is_strict_frozen_bounded_and_validated() -> None:
    evidence = contact_evidence()
    with pytest.raises(ValidationError):
        evidence.candidates = ()
    with pytest.raises(ValidationError):
        CreatorContactEvidence.model_validate(
            {
                "candidates": [
                    {
                        "candidate_id": "contact.email.0",
                        "kind": "email",
                        "value": "not-an-email",
                        "source_type": "channel_description",
                        "source_url": "https://youtube.com/channel/UC123",
                        "validation_state": "validated",
                    }
                ],
                "raw_page": {"secret": "must-not-exist"},
            }
        )


@pytest.mark.parametrize(
    "invalid_url",
    [
        "https://127.0.0.1/contact",
        "https://[::1]/contact",
        "https://localhost/contact",
        "https://sub.localhost/contact",
        "https://localhost./contact",
        "https://sub.localhost./contact",
        "https://ｌｏｃａｌｈｏｓｔ/contact",
        "https://ｓｕｂ．ｌｏｃａｌｈｏｓｔ/contact",
        "https://sub。localhost/contact",
        "https://sub.localhost。/contact",
        "https://ⓛⓞⓒⓐⓛⓗⓞⓢⓣ/contact",
        "https://127.1/contact",
        "https://2130706433/contact",
        "https://0x7f000001/contact",
        "https://0177.0.0.1/contact",
        "https://１２７.０.０.１/contact",
        "https://%31%32%37.0.0.1/contact",
        "https://%65xample.com/contact",
        "https://example.com\\@evil.example/contact",
        "https://example.com/%0a",
        "https://example.com/%80",
        "https://example.com/%2525250a",
        "https://example.com/%E2%80%AEhidden",
        "https://example.com/contact#fragment",
        "https://example.com/contact#",
        "https://224.0.0.0/contact",
        "https://224.0.0.1/contact",
        "https://239.255.255.255/contact",
        "https://8.8.8.8/contact",
        "https://[2606:4700:4700::1111]/contact",
        "https://[2001:4860:4860::8888]/contact",
        "https://[::ffff:8.8.8.8]/contact",
        "https://192.0.0.9/contact",
        "https://192.0.0.10/contact",
        "https://[2001:3::1]/contact",
        "https://192.31.196.1/contact",
        "https://192.52.193.1/contact",
        "https://192.175.48.1/contact",
        "https://[2001:4:112::1]/contact",
        "https://[ff00::]/contact",
        "https://[ff02::1]/contact",
        "https://[ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff]/contact",
    ],
)
def test_contact_evidence_rejects_non_public_or_control_urls(
    invalid_url: str,
) -> None:
    payload = contact_evidence().model_dump(mode="json")
    payload["candidates"][1]["value"] = invalid_url
    with pytest.raises(ValidationError):
        CreatorContactEvidence.model_validate(payload)


@pytest.mark.parametrize(
    "public_url",
    [
        "https://creator.example/contact?ref=channel",
        "http://social.example/creator",
        "https://例子.测试/contact",
    ],
)
def test_contact_evidence_accepts_public_http_urls(public_url: str) -> None:
    payload = contact_evidence().model_dump(mode="json")
    payload["candidates"][1]["value"] = public_url
    result = CreatorContactEvidence.model_validate(payload)
    assert result.candidates[1].value == public_url


def test_contact_evidence_rejects_duplicate_resolved_social_urls() -> None:
    payload = contact_evidence().model_dump(mode="json")
    payload["candidates"].append(
        {
            "candidate_id": "contact.social.1",
            "kind": "social_link",
            "value": "https://SOCIAL.example:443/creator",
            "source_type": "linked_public_page",
            "source_url": "https://creator.example/second-source",
            "validation_state": "validated",
        }
    )
    with pytest.raises(ValidationError, match="social URL"):
        CreatorContactEvidence.model_validate(payload)


@pytest.mark.parametrize(
    "first,second",
    [
        ("https://social.example", "https://social.example/"),
        ("https://social.example/%7Ecreator", "https://social.example/~creator"),
        ("https://social.example/a/../creator", "https://social.example/creator"),
        ("https://social.example./creator", "https://social.example/creator"),
        (
            "https://例子.测试/creator",
            "https://xn--fsqu00a.xn--0zwm56d/creator",
        ),
    ],
)
def test_contact_evidence_rejects_canonically_duplicate_social_urls(
    first: str,
    second: str,
) -> None:
    payload = contact_evidence().model_dump(mode="json")
    payload["candidates"][2]["value"] = first
    payload["candidates"].append(
        {
            "candidate_id": "contact.social.1",
            "kind": "social_link",
            "value": second,
            "source_type": "linked_public_page",
            "source_url": "https://creator.example/second-source",
            "validation_state": "validated",
        }
    )
    with pytest.raises(ValidationError, match="social URL"):
        CreatorContactEvidence.model_validate(payload)


def test_contact_binding_resolves_only_exact_pipeline_owned_candidates() -> None:
    synthesis = CreatorSynthesis.model_validate(creator_synthesis_payload())
    bound = bind_creator_contacts(synthesis, contact_evidence())
    assert bound.public_email is not None
    assert bound.public_email.value == "press@example.com"
    assert bound.public_email.source_url == "https://youtube.com/channel/UC123"
    assert bound.public_email.validation_state == "validated"
    assert bound.linked_site is not None
    assert [candidate.value for candidate in bound.social_links] == [
        "https://social.example/creator"
    ]


def test_contact_binding_rejects_fabricated_or_wrong_kind_selections() -> None:
    payload = creator_synthesis_payload()
    payload["public_email"] = {
        "status": "available",
        "candidate_id": "contact.fabricated.0",
    }
    with pytest.raises(ValueError, match="contact selection"):
        bind_creator_contacts(
            CreatorSynthesis.model_validate(payload), contact_evidence()
        )

    payload["public_email"] = {
        "status": "available",
        "candidate_id": "contact.site.0",
    }
    with pytest.raises(ValueError, match="contact selection"):
        bind_creator_contacts(
            CreatorSynthesis.model_validate(payload), contact_evidence()
        )


def test_empty_contact_evidence_forces_all_contact_outputs_unavailable() -> None:
    payload = creator_synthesis_payload()
    synthesis = CreatorSynthesis.model_validate(payload)
    with pytest.raises(ValueError, match="contact selection"):
        bind_creator_contacts(synthesis, CreatorContactEvidence(candidates=()))

    payload["public_email"] = unavailable()
    payload["linked_site"] = unavailable()
    payload["social_links"] = unavailable()
    bound = bind_creator_contacts(
        CreatorSynthesis.model_validate(payload), CreatorContactEvidence(candidates=())
    )
    assert bound.public_email is None
    assert bound.linked_site is None
    assert bound.social_links == ()


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
    cases = [
        (GameExtraction, game_extraction_payload()),
        (GameVisualAnalysis, game_visual_unavailable_payload()),
        (GameSynthesis, game_synthesis_payload()),
        (CreatorMetadataAnalysis, creator_metadata_unavailable_payload()),
        (CreatorVisualAnalysis, creator_visual_unavailable_payload()),
        (CreatorSynthesis, creator_synthesis_payload()),
    ]
    for schema, payload in cases:
        result = schema.model_validate(payload)
        with pytest.raises(ValidationError):
            schema.model_validate({**payload, "score": 0.9})
        with pytest.raises(ValidationError):
            result.english_language_check = True

        encoded = result.model_dump_json()
        assert schema.model_validate_json(encoded) == result
        schema_text = json.dumps(schema.model_json_schema(), allow_nan=False)
        assert '"additionalProperties": false' in schema_text
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


def test_creator_brief_audience_requires_compact_ai_inference_provenance() -> None:
    payload = creator_synthesis_payload()["creator_brief"]
    payload["audience"] = compact_text_claim("Strategy viewers")
    with pytest.raises(ValidationError):
        CreatorBrief.model_validate(payload)


def test_briefs_reject_full_profile_sized_claims() -> None:
    game = game_brief_payload()
    game["positioning_premise"] = compact_text_claim("x" * 4_000)
    with pytest.raises(ValidationError):
        GameBrief.model_validate(game)

    creator = creator_synthesis_payload()["creator_brief"]
    creator["positioning"] = compact_text_claim("x" * 4_001)
    with pytest.raises(ValidationError):
        CreatorBrief.model_validate(creator)


def test_creator_brief_accepts_bounded_descriptive_list_items() -> None:
    payload = creator_synthesis_payload()["creator_brief"]
    payload["collaboration_risks"]["values"] = ["r" * 512]

    CreatorBrief.model_validate(payload)

    payload["collaboration_risks"]["values"] = ["r" * 513]
    with pytest.raises(ValidationError):
        CreatorBrief.model_validate(payload)


def test_worst_case_screening_brief_budget_fits_one_game_and_100_creators() -> None:
    source_evidence = [
        {
            "kind": "source_fact",
            "source_type": "steam_field",
            "reference": f"steam:{'r' * 88}{index}",
        }
        for index in range(2)
    ]
    inference_evidence = [
        {
            "kind": "ai_inference",
            "source_type": "video_id",
            "reference": f"video:{'r' * 87}{index}",
        }
        for index in range(2)
    ]
    max_text = compact_text_claim(
        "x" * 240,
        claim_evidence=source_evidence,
    )
    max_list = compact_list_claim(
        *(f"{index}{'x' * 71}" for index in range(4)),
        claim_evidence=source_evidence,
    )
    max_audience = {
        "status": "available",
        "value": "x" * 240,
        "provenance": "ai_inference",
        "evidence": inference_evidence,
        "confidence": "high",
    }
    max_creator_text = creator_compact_text_claim("x" * 144)
    max_creator_text["evidence"] = source_evidence[:1]
    max_creator_list = creator_compact_list_claim(
        *(f"{index}{'x' * 63}" for index in range(3))
    )
    max_creator_list["evidence"] = source_evidence[:1]
    max_creator_audience = {
        **max_audience,
        "value": "x" * 144,
        "evidence": inference_evidence[:1],
    }
    game_payload = {
        field: (
            max_text
            if field in {"positioning_premise", "core_gameplay_loop", "visual_identity"}
            else max_list
        )
        for field in GameBrief.model_fields
    }
    creator_payload = {
        field: (
            max_creator_audience
            if field == "audience"
            else (
                max_creator_list
                if field
                in {
                    "content_focus",
                    "formats",
                    "suitable_game_types",
                    "collaboration_risks",
                }
                else max_creator_text
            )
        )
        for field in CreatorBrief.model_fields
    }
    game = GameBrief.model_validate(game_payload)
    creator = CreatorBrief.model_validate(creator_payload)

    game_size = len(game.model_dump_json().encode("utf-8"))
    creator_size = len(creator.model_dump_json().encode("utf-8"))
    combined_size = game_size + 100 * creator_size + MAX_SCREENING_PROMPT_OVERHEAD_BYTES

    assert game_size <= MAX_GAME_BRIEF_JSON_BYTES
    assert creator_size <= MAX_CREATOR_BRIEF_JSON_BYTES
    assert creator_size * 2 <= game_size
    assert (
        MAX_GAME_BRIEF_JSON_BYTES
        + 100 * MAX_CREATOR_BRIEF_JSON_BYTES
        + MAX_SCREENING_PROMPT_OVERHEAD_BYTES
        <= 1_000_000
    )
    assert combined_size <= 1_000_000
    grouped_message_payload_bytes = 120_000
    required_user_messages = (
        combined_size + grouped_message_payload_bytes - 1
    ) // grouped_message_payload_bytes
    assert grouped_message_payload_bytes < 131_072
    assert required_user_messages + 1 <= 100
