"""Normal prose must survive reduction and publication without truncation."""

import pytest
from pydantic import ValidationError

from app.analysis.creator_map_reduce import merge_creator_synthesis
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_creator_map_reduce import (
    CreatorPresentationReduction,
    CreatorBriefSynthesis,
    CreatorVideoBatchDigest,
)
from .test_creator_map_reduce import (
    _presentation_reduction_payload,
    _brief_payload,
    _validated_stages,
    _batch_payload,
)


@pytest.mark.parametrize("length", [322, 800, 2000])
def test_normal_reducer_narrative_survives_final_merge(length):
    payload = _presentation_reduction_payload()
    payload["production_quality"]["value"] = "x" * length
    payload["style"]["values"] = ["s" * 400]
    payload["pacing"]["evidence"][0]["observation"] = "o" * 800
    presentation = CreatorPresentationReduction.model_validate(payload)
    content, _, performance, commercial, brief = _validated_stages()
    result = merge_creator_synthesis(
        content_format=content,
        presentation=presentation,
        performance_audience=performance,
        commercial_safety=commercial,
        brief=brief,
    )
    assert result.production_quality.value == "x" * length
    assert result.style.values == ("s" * 400,)
    assert result.pacing.evidence[0].observation == "o" * 800


def test_brief_normal_prose_is_preserved():
    payload = _brief_payload()
    payload["creator_brief"]["positioning"]["value"] = "x" * 800
    payload["creator_brief"]["formats"]["values"] = ["f" * 400]
    result = CreatorBriefSynthesis.model_validate(payload)
    assert result.model_dump(mode="json") == payload


def test_brief_still_has_aggregate_guard():
    payload = _brief_payload()["creator_brief"]
    for field in ("positioning", "style_and_pacing", "performance_context"):
        payload[field]["value"] = "x" * 3000
    with pytest.raises(ValidationError, match="serialization budget"):
        CreatorBrief.model_validate(payload)


def test_map_normal_narrative_and_unavailable_reasons_are_not_tiny():
    payload = _batch_payload()
    payload["content_format"]["representative_video_context"]["values"] = ["v" * 400]
    payload["presentation"]["style_and_pacing"]["value"] = "s" * 800
    payload["presentation"]["production_signals"] = {
        "status": "unavailable",
        "reason": "r" * 800,
    }
    assert (
        CreatorVideoBatchDigest.model_validate(payload).model_dump(mode="json")
        == payload
    )


def test_map_aggregate_guard_remains_even_when_each_field_is_valid():
    payload = _batch_payload()
    for dimension in (
        "content_format",
        "presentation",
        "performance_audience",
        "commercial_safety",
    ):
        for claim in payload[dimension].values():
            claim["evidence"][0]["observation"] = "x" * 3000
    with pytest.raises(ValidationError, match="serialization budget"):
        CreatorVideoBatchDigest.model_validate(payload)


@pytest.mark.parametrize("value", ["", " ", 42, ["text"]])
def test_normal_prose_relaxation_keeps_type_and_nonblank_checks(value):
    payload = _presentation_reduction_payload()
    payload["production_quality"]["value"] = value
    with pytest.raises(ValidationError):
        CreatorPresentationReduction.model_validate(payload)
