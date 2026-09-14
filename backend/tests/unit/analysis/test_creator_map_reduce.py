from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.analysis.creator_map_reduce import merge_creator_synthesis
from app.analysis.prompts.common import MAX_PROMPT_BYTES, parse_prompt_payload
from app.analysis.prompts.creator_map_reduce import (
    CREATOR_BRIEF_PROMPT_VERSION,
    CREATOR_COMMERCIAL_SAFETY_PROMPT_VERSION,
    CREATOR_CONTENT_FORMAT_PROMPT_VERSION,
    CREATOR_PERFORMANCE_AUDIENCE_PROMPT_VERSION,
    CREATOR_PRESENTATION_PROMPT_VERSION,
    CREATOR_VIDEO_BATCH_PROMPT_VERSION,
    build_creator_brief_bundle,
    build_creator_commercial_safety_bundle,
    build_creator_content_format_bundle,
    build_creator_performance_audience_bundle,
    build_creator_presentation_bundle,
    build_creator_video_batch_bundle,
    creator_video_batch_count,
)
from app.schemas.ai_creator import (
    CreatorSynthesis,
    CreatorVisualAnalysis,
    bind_creator_contacts,
)
from app.schemas.ai_creator_map_reduce import (
    MAX_CREATOR_VIDEO_BATCH_DIGEST_JSON_BYTES,
    CreatorBriefSynthesis,
    CreatorCommercialSafetyReduction,
    CreatorContentFormatReduction,
    CreatorPerformanceAudienceReduction,
    CreatorPresentationReduction,
    CreatorVideoBatchDigest,
)
from app.schemas.ai_game import validate_stage_evidence

from .test_ai_schemas import (
    contact_evidence,
    creator_synthesis_payload,
    unavailable,
)
from .test_prompts import sample_creator_source, unavailable_creator_visual


def _evidence(
    reference: str = "video:video-1",
    *,
    source_type: str = "video_id",
    kind: str = "source_fact",
) -> list[dict[str, str]]:
    return [
        {
            "kind": kind,
            "source_type": source_type,
            "reference": reference,
            "observation": "The supplied evidence supports this bounded signal.",
        }
    ]


def _text_claim(
    value: str = "A concise evidence-backed signal.",
    *,
    reference: str = "video:video-1",
    source_type: str = "video_id",
    kind: str = "source_fact",
) -> dict[str, object]:
    return {
        "status": "available",
        "value": value,
        "evidence": _evidence(reference, source_type=source_type, kind=kind),
        "confidence": "medium",
    }


def _list_claim(
    *values: str,
    reference: str = "video:video-1",
    source_type: str = "video_id",
    kind: str = "source_fact",
) -> dict[str, object]:
    return {
        "status": "available",
        "values": list(values or ("Strategy",)),
        "evidence": _evidence(reference, source_type=source_type, kind=kind),
        "confidence": "medium",
    }


def _batch_payload() -> dict[str, object]:
    return {
        "english_language_check": True,
        "content_format": {
            "content_focus": _list_claim("Strategy guides"),
            "primary_games": _list_claim("Game A"),
            "genres": _list_claim("Strategy"),
            "formats": _list_claim("Long-form guide"),
            "format_tendencies": _text_claim(),
            "representative_video_context": _list_claim("A tactical guide"),
        },
        "presentation": {
            "style_and_pacing": _text_claim(),
            "production_signals": _text_claim(),
        },
        "performance_audience": {
            "recent_performance": _text_claim(),
            "engagement": _text_claim(),
            "publishing_cadence": _text_claim(),
            "audience_signals": _list_claim("English titles"),
        },
        "commercial_safety": {
            "sponsorship_signals": _list_claim("Disclosed integrations"),
            "brand_safety_signals": _list_claim("No metadata warning signal"),
            "collaboration_risks": _list_claim("Irregular cadence"),
        },
    }


def _reducer_evidence(field: str, dimension: str) -> dict[str, object]:
    return {
        "reference": f"batch:0:{dimension}.{field}",
        "source_type": "intermediate_output",
        "kind": "ai_inference",
    }


def _reducer_text(field: str, dimension: str) -> dict[str, object]:
    return _text_claim(
        reference=str(_reducer_evidence(field, dimension)["reference"]),
        source_type="intermediate_output",
        kind="ai_inference",
    )


def _reducer_list(field: str, dimension: str) -> dict[str, object]:
    return _list_claim(
        reference=str(_reducer_evidence(field, dimension)["reference"]),
        source_type="intermediate_output",
        kind="ai_inference",
    )


def _content_reduction_payload() -> dict[str, object]:
    payload = creator_synthesis_payload()
    fields = CreatorContentFormatReduction.model_fields.keys()
    return {name: payload[name] for name in fields}


def _presentation_reduction_payload() -> dict[str, object]:
    payload = creator_synthesis_payload()
    fields = CreatorPresentationReduction.model_fields.keys()
    return {name: payload[name] for name in fields}


def _performance_reduction_payload() -> dict[str, object]:
    payload = creator_synthesis_payload()
    fields = CreatorPerformanceAudienceReduction.model_fields.keys()
    return {name: payload[name] for name in fields}


def _commercial_reduction_payload() -> dict[str, object]:
    payload = creator_synthesis_payload()
    fields = CreatorCommercialSafetyReduction.model_fields.keys()
    return {name: payload[name] for name in fields}


def _brief_payload() -> dict[str, object]:
    synthesis = creator_synthesis_payload()
    return {
        "english_language_check": True,
        "public_email": synthesis["public_email"],
        "linked_site": synthesis["linked_site"],
        "social_links": synthesis["social_links"],
        "creator_brief": synthesis["creator_brief"],
    }


def _validated_stages():
    return (
        CreatorContentFormatReduction.model_validate(_content_reduction_payload()),
        CreatorPresentationReduction.model_validate(_presentation_reduction_payload()),
        CreatorPerformanceAudienceReduction.model_validate(
            _performance_reduction_payload()
        ),
        CreatorCommercialSafetyReduction.model_validate(
            _commercial_reduction_payload()
        ),
        CreatorBriefSynthesis.model_validate(_brief_payload()),
    )


def test_map_reduce_schemas_are_strict_frozen_and_bounded() -> None:
    batch = CreatorVideoBatchDigest.model_validate(_batch_payload())
    assert (
        len(batch.model_dump_json().encode("utf-8"))
        <= MAX_CREATOR_VIDEO_BATCH_DIGEST_JSON_BYTES
    )
    with pytest.raises(ValidationError):
        CreatorVideoBatchDigest.model_validate({**_batch_payload(), "score": 0.9})
    with pytest.raises(ValidationError):
        batch.content_format = batch.content_format

    oversized = _batch_payload()
    oversized["presentation"]["style_and_pacing"]["value"] = "x" * 4001
    with pytest.raises(ValidationError):
        CreatorVideoBatchDigest.model_validate(oversized)

    assert CreatorVideoBatchDigest.deepseek_max_tokens == 6_144
    assert CreatorContentFormatReduction.deepseek_max_tokens == 4_096
    assert CreatorPresentationReduction.deepseek_max_tokens == 2_048
    assert CreatorPerformanceAudienceReduction.deepseek_max_tokens == 3_072
    assert CreatorCommercialSafetyReduction.deepseek_max_tokens == 2_048
    assert CreatorBriefSynthesis.deepseek_max_tokens == 3_072


def test_map_reduce_claims_accept_up_to_three_evidence_references() -> None:
    payload = _batch_payload()
    primary_games = payload["content_format"]["primary_games"]
    primary_games["evidence"] = [
        {
            "kind": "source_fact",
            "source_type": "video_id",
            "reference": f"video:video-{index}",
            "observation": f"Video {index} supports this bounded signal.",
        }
        for index in range(1, 4)
    ]

    CreatorVideoBatchDigest.model_validate(payload)

    primary_games["evidence"].append(
        {
            "kind": "source_fact",
            "source_type": "video_id",
            "reference": "video:video-4",
            "observation": "Video 4 exceeds the bounded evidence allowance.",
        }
    )
    with pytest.raises(ValidationError):
        CreatorVideoBatchDigest.model_validate(payload)


def test_presentation_style_accepts_bounded_descriptive_values() -> None:
    payload = _presentation_reduction_payload()
    payload["style"]["values"] = ["s" * 512]

    CreatorPresentationReduction.model_validate(payload)

    payload["style"]["values"] = ["s" * 513]
    with pytest.raises(ValidationError):
        CreatorPresentationReduction.model_validate(payload)


def test_reducer_fields_are_mutually_exclusive_and_cover_final_synthesis() -> None:
    reducer_types = (
        CreatorContentFormatReduction,
        CreatorPresentationReduction,
        CreatorPerformanceAudienceReduction,
        CreatorCommercialSafetyReduction,
    )
    field_sets = [
        set(item.model_fields) - {"english_language_check"} for item in reducer_types
    ]
    for index, fields in enumerate(field_sets):
        assert all(fields.isdisjoint(other) for other in field_sets[index + 1 :])
    expected = set(CreatorSynthesis.model_fields) - {
        "english_language_check",
        "creator_brief",
        "public_email",
        "linked_site",
        "social_links",
    }
    assert set().union(*field_sets) == expected


def test_video_batch_builder_caps_at_ten_and_never_serializes_raw_envelopes() -> None:
    prototype = sample_creator_source(canary="never-serialize-raw").videos[0]
    videos = tuple(
        prototype.model_copy(
            update={
                "id": f"video-{index}",
                "title": f"Video title {index}",
                "raw": {"authorization": "never-serialize-raw"},
            }
        )
        for index in range(23)
    )
    source = sample_creator_source(canary="never-serialize-raw").model_copy(
        update={"videos": videos}
    )
    before = deepcopy(source)

    assert creator_video_batch_count(source) == 3
    first = build_creator_video_batch_bundle(source, batch_index=0)
    last = build_creator_video_batch_bundle(source, batch_index=2)
    first_payload = parse_prompt_payload(first.messages)
    last_payload = parse_prompt_payload(last.messages)

    assert [item["id"] for item in first_payload["video_batch"]] == [
        f"video-{index}" for index in range(10)
    ]
    assert [item["id"] for item in last_payload["video_batch"]] == [
        "video-20",
        "video-21",
        "video-22",
    ]
    assert "never-serialize-raw" not in "".join(
        message.content for message in first.messages
    )
    assert tuple(entry.reference for entry in first.evidence_catalog.entries)[
        -10:
    ] == tuple(f"video:video-{index}" for index in range(10))
    assert source == before
    assert (
        sum(len(message.content.encode("utf-8")) for message in first.messages)
        <= MAX_PROMPT_BYTES
    )
    with pytest.raises(ValueError, match="batch_index"):
        build_creator_video_batch_bundle(source, batch_index=3)


def test_video_batch_builder_supports_channel_only_creator() -> None:
    source = sample_creator_source().model_copy(update={"videos": ()})

    assert creator_video_batch_count(source) == 1
    bundle = build_creator_video_batch_bundle(source, batch_index=0)
    payload = parse_prompt_payload(bundle.messages)

    assert payload["video_batch"] == []
    assert any(
        entry.reference == "channel:title" for entry in bundle.evidence_catalog.entries
    )


def test_dimension_prompts_are_small_validated_intermediate_only_inputs() -> None:
    digest = CreatorVideoBatchDigest.model_validate(_batch_payload())
    visual = unavailable_creator_visual()
    builders = (
        build_creator_content_format_bundle((digest,)),
        build_creator_presentation_bundle((digest,), visual=visual),
        build_creator_performance_audience_bundle((digest,)),
        build_creator_commercial_safety_bundle((digest,)),
    )
    expected_keys = (
        "validated_content_format_batches",
        "validated_presentation_batches",
        "validated_performance_audience_batches",
        "validated_commercial_safety_batches",
    )
    for bundle, expected_key in zip(builders, expected_keys, strict=True):
        payload = parse_prompt_payload(bundle.messages)
        assert expected_key in payload
        assert "youtube_source" not in payload
        assert "video_batch" not in payload
        assert (
            sum(len(item.content.encode("utf-8")) for item in bundle.messages)
            <= MAX_PROMPT_BYTES
        )


def test_reducer_catalog_binds_only_the_selected_dimension() -> None:
    digest = CreatorVideoBatchDigest.model_validate(_batch_payload())
    bundle = build_creator_content_format_bundle((digest,))
    references = {entry.reference for entry in bundle.evidence_catalog.entries}
    assert "batch:0:content_format.content_focus" in references
    assert not any("presentation" in reference for reference in references)

    payload = {
        "english_language_check": True,
        "content_summary": _reducer_text("content_focus", "content_format"),
        "primary_games": unavailable(),
        "genres": unavailable(),
        "formats": unavailable(),
        "livestream_tendency": unavailable(),
        "long_form_tendency": unavailable(),
        "short_form_tendency": unavailable(),
        "representative_video_context": unavailable(),
        "suitable_game_types": unavailable(),
    }
    reduction = CreatorContentFormatReduction.model_validate(payload)
    validate_stage_evidence(reduction, bundle.evidence_catalog)

    fabricated = deepcopy(payload)
    fabricated["content_summary"]["evidence"][0]["reference"] = "batch:9:fake"
    with pytest.raises(ValueError, match="not bound"):
        validate_stage_evidence(
            CreatorContentFormatReduction.model_validate(fabricated),
            bundle.evidence_catalog,
        )


def test_content_format_prompt_maps_current_citations_without_losing_batch_evidence() -> (
    None
):
    raw = _batch_payload()
    raw["content_format"]["genres"] = unavailable()
    digest = CreatorVideoBatchDigest.model_validate(raw)

    bundle = build_creator_content_format_bundle((digest, digest))
    payload = parse_prompt_payload(bundle.messages)
    rules = "\n".join(
        message.content for message in bundle.messages if message.role == "system"
    )

    assert CREATOR_CONTENT_FORMAT_PROMPT_VERSION == "creator-content-format-v3"
    assert "source_type=intermediate_output" in rules
    assert "kind=ai_inference" in rules
    assert "Do not copy nested video or channel citations" in rules
    assert "output field names" in rules
    for index, batch in enumerate(payload["validated_content_format_batches"]):
        assert batch["digest"] == digest.content_format.model_dump(mode="json")
        assert batch["citation_targets"]["content_focus"] == {
            "reference": f"batch:{index}:content_format.content_focus",
            "source_type": "intermediate_output",
            "kind": "ai_inference",
        }
        assert "genres" not in batch["citation_targets"]
        assert set(batch["citation_targets"]) == {
            entry.reference.rsplit(".", 1)[-1]
            for entry in bundle.evidence_catalog.entries
            if entry.reference.startswith(f"batch:{index}:")
        }


def test_batch_and_brief_evidence_bind_to_their_exact_stage_inputs() -> None:
    source = sample_creator_source()
    batch_bundle = build_creator_video_batch_bundle(source, batch_index=0)
    digest = CreatorVideoBatchDigest.model_validate(_batch_payload())
    validate_stage_evidence(digest, batch_bundle.evidence_catalog)

    content, presentation, performance, commercial, _ = _validated_stages()
    brief_bundle = build_creator_brief_bundle(
        content_format=content,
        presentation=presentation,
        performance_audience=performance,
        commercial_safety=commercial,
        contact_evidence=contact_evidence(),
    )
    brief_payload = _brief_payload()
    creator_brief = brief_payload["creator_brief"]
    for name in creator_brief:
        creator_brief[name] = (
            {
                "status": "unavailable",
                "reason": "No reliable public evidence.",
                "provenance": "ai_inference",
            }
            if name == "audience"
            else unavailable()
        )
    creator_brief["positioning"] = {
        "status": "available",
        "value": "A compact strategy-game creator.",
        "evidence": [
            {
                "kind": "ai_inference",
                "source_type": "intermediate_output",
                "reference": "reduction:content_format:content_summary",
            }
        ],
        "confidence": "medium",
    }
    brief = CreatorBriefSynthesis.model_validate(brief_payload)
    validate_stage_evidence(brief, brief_bundle.evidence_catalog)

    fabricated = deepcopy(brief_payload)
    fabricated["creator_brief"]["positioning"]["evidence"][0][
        "reference"
    ] = "reduction:missing:field"
    with pytest.raises(ValueError, match="not bound"):
        validate_stage_evidence(
            CreatorBriefSynthesis.model_validate(fabricated),
            brief_bundle.evidence_catalog,
        )


def test_brief_prompt_uses_only_reduced_profiles_and_stays_bounded() -> None:
    content, presentation, performance, commercial, _ = _validated_stages()
    bundle = build_creator_brief_bundle(
        content_format=content,
        presentation=presentation,
        performance_audience=performance,
        commercial_safety=commercial,
        contact_evidence=contact_evidence(),
    )
    payload = parse_prompt_payload(bundle.messages)
    rendered = "".join(item.content for item in bundle.messages)

    assert set(payload) == {
        "contact_evidence",
        "evidence_catalog",
        "validated_reductions",
    }
    assert "youtube_source" not in rendered
    assert "video_batch" not in rendered
    assert "validated_reductions" in payload
    assert "144 characters (not words)" in rendered
    assert "at most 64 characters" in rendered
    assert payload["contact_evidence"] == contact_evidence().model_dump(mode="json")
    assert (
        sum(len(item.content.encode("utf-8")) for item in bundle.messages)
        <= MAX_PROMPT_BYTES
    )
    assert all(
        entry.source_type == "intermediate_output"
        for entry in bundle.evidence_catalog.entries
    )


def test_deterministic_merge_populates_existing_synthesis_without_regeneration() -> (
    None
):
    content, presentation, performance, commercial, brief = _validated_stages()
    synthesis = merge_creator_synthesis(
        content_format=content,
        presentation=presentation,
        performance_audience=performance,
        commercial_safety=commercial,
        brief=brief,
    )

    assert isinstance(synthesis, CreatorSynthesis)
    for name in CreatorContentFormatReduction.model_fields:
        if name != "english_language_check":
            assert getattr(synthesis, name).model_dump(mode="json") == getattr(
                content, name
            ).model_dump(mode="json")
    assert synthesis.creator_brief == brief.creator_brief
    assert synthesis.public_email.model_dump(
        mode="json"
    ) == brief.public_email.model_dump(mode="json")
    assert synthesis.audience_inference.model_dump(
        mode="json"
    ) == performance.audience_inference.model_dump(mode="json")
    bound = bind_creator_contacts(synthesis, contact_evidence())
    assert bound.public_email is not None
    assert bound.public_email.candidate_id == "contact.email.0"

    with pytest.raises(TypeError, match="validated"):
        merge_creator_synthesis(
            content_format=content.model_dump(mode="json"),
            presentation=presentation,
            performance_audience=performance,
            commercial_safety=commercial,
            brief=brief,
        )


def test_map_reduce_prompt_versions_are_stage_specific() -> None:
    versions = {
        CREATOR_VIDEO_BATCH_PROMPT_VERSION,
        CREATOR_CONTENT_FORMAT_PROMPT_VERSION,
        CREATOR_PRESENTATION_PROMPT_VERSION,
        CREATOR_PERFORMANCE_AUDIENCE_PROMPT_VERSION,
        CREATOR_COMMERCIAL_SAFETY_PROMPT_VERSION,
        CREATOR_BRIEF_PROMPT_VERSION,
    }
    assert len(versions) == 6
    assert CREATOR_BRIEF_PROMPT_VERSION == "creator-brief-v2"
    assert CREATOR_CONTENT_FORMAT_PROMPT_VERSION == "creator-content-format-v3"
    assert all(
        version.startswith("creator-") and version.endswith("-v2")
        for version in versions
        - {CREATOR_BRIEF_PROMPT_VERSION, CREATOR_CONTENT_FORMAT_PROMPT_VERSION}
    )


def test_map_and_reducers_explicitly_select_within_list_limits() -> None:
    digest = CreatorVideoBatchDigest.model_validate(_batch_payload())
    bundles = [
        build_creator_video_batch_bundle(sample_creator_source(), batch_index=0),
        build_creator_content_format_bundle([digest]),
        build_creator_presentation_bundle([digest]),
        build_creator_performance_audience_bundle([digest]),
        build_creator_commercial_safety_bundle([digest]),
    ]
    for bundle in bundles:
        rules = "\n".join(m.content for m in bundle.messages if m.role == "system")
        assert "at most 3 items" in rules
        assert "values" in rules and "evidence" in rules
        assert "strongest" in rules
        assert "Do not concatenate" in rules
