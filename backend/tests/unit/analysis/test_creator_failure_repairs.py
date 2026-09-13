import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.ai_creator_map_reduce import CreatorVideoBatchDigest
from app.schemas.ai_game import (
    EvidenceCatalog,
    EvidenceCatalogEntry,
    validate_stage_evidence,
)
from .test_creator_map_reduce import _batch_payload


def test_ten_video_map_keeps_supported_lists_and_evidence_without_truncation():
    data = _batch_payload()
    data["content_format"]["genres"]["values"] = [f"Genre {i}" for i in range(10)]
    evidence = data["content_format"]["genres"]["evidence"][0]
    data["content_format"]["genres"]["evidence"] = [
        {**evidence, "reference": f"video:example-{i}"} for i in range(8)
    ]
    result = CreatorVideoBatchDigest.model_validate(data)
    assert len(result.content_format.genres.values) == 10
    assert len(result.content_format.genres.evidence) == 8
    data["content_format"]["genres"]["values"] = [f"Genre {i}" for i in range(21)]
    with pytest.raises(ValidationError):
        CreatorVideoBatchDigest.model_validate(data)


def test_catalog_binding_only_normalizes_exact_intermediate_identity():
    from app.analysis.evidence_binding import evidence_bindings, normalize_evidence_json

    catalog = EvidenceCatalog(
        entries=(
            EvidenceCatalogEntry(
                reference="creator_visual:art_style",
                source_type="intermediate_output",
                allowed_kinds=("ai_inference",),
            ),
        )
    )
    original = {
        "kind": "visual_observation",
        "source_type": "visual_asset",
        "reference": "creator_visual:art_style",
        "observation": "Only the supplied thumbnail has visible warm colors.",
    }
    raw = json.dumps({"evidence": [original]})
    assert normalize_evidence_json(raw) == raw
    with evidence_bindings(catalog):
        changed = json.loads(normalize_evidence_json(raw))["evidence"][0]
        assert changed == {
            **original,
            "kind": "ai_inference",
            "source_type": "intermediate_output",
        }
        unknown = json.dumps(
            {"evidence": [{**original, "reference": "invented:asset"}]}
        )
        assert normalize_evidence_json(unknown) == unknown
    assert normalize_evidence_json(raw) == raw


def test_repair_never_presents_a_truncated_json_fragment():
    from app.integrations.deepseek import _repair_messages, _schema_payload

    data = _batch_payload()
    # A valid >8 KiB structured response, matching the observed failed-call sizes.
    data["presentation"]["style_and_pacing"]["value"] = (
        "Public metadata supports a cautious inference. " * 65
    )
    data["presentation"]["production_signals"]["value"] = (
        "Metadata does not establish unseen video content. " * 65
    )
    raw = json.dumps(data)
    assert len(raw) > 8192
    messages = _repair_messages(
        raw, _schema_payload(CreatorVideoBatchDigest), ValueError("safe")
    )
    assert json.loads(messages[0]["content"]) == data
    huge = raw * 10
    messages = _repair_messages(
        huge, _schema_payload(CreatorVideoBatchDigest), ValueError("safe")
    )
    assert all(m["role"] != "assistant" for m in messages)
    assert "regenerate" in messages[-1]["content"].lower()


def test_reducer_gateway_normalizes_labels_but_unknown_reference_still_rejected():
    import httpx
    from app.analysis.evidence_binding import evidence_bindings
    from app.integrations.deepseek import DeepSeekGateway
    from app.schemas.ai_creator_map_reduce import CreatorPresentationReduction
    from .test_creator_map_reduce import _text_claim, _list_claim

    catalog = EvidenceCatalog(
        entries=(
            EvidenceCatalogEntry(
                reference="creator_visual:art_style",
                source_type="intermediate_output",
                allowed_kinds=("ai_inference",),
            ),
        )
    )
    output = {
        "english_language_check": True,
        "style": _list_claim(
            "Warm colors",
            reference="creator_visual:art_style",
            source_type="visual_asset",
            kind="visual_observation",
        ),
        "pacing": {"status": "unavailable", "reason": "No reliable evidence."},
        "production_quality": _text_claim(
            "Visible thumbnail palette",
            reference="creator_visual:art_style",
            source_type="intermediate_output",
            kind="source_fact",
        ),
    }
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(output)}}]}
        )

    gateway = DeepSeekGateway(
        api_key="synthetic",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with evidence_bindings(catalog):
        result = gateway.complete_structured(
            "deepseek-flash", [], CreatorPresentationReduction
        )
    validate_stage_evidence(result, catalog)
    assert len(calls) == 1
    assert result.style.values == ("Warm colors",)
    assert (
        result.style.evidence[0].observation
        == output["style"]["evidence"][0]["observation"]
    )
    invalid = result.model_dump(mode="json")
    invalid["style"]["evidence"][0]["reference"] = "invented:source"
    with pytest.raises(ValueError):
        validate_stage_evidence(
            CreatorPresentationReduction.model_validate(invalid), catalog
        )


def test_nested_audience_binding_repair_preserves_every_nonidentity_value():
    from app.analysis.creator_map_reduce_pipeline import (
        _content_format_without_bindings,
    )
    from app.schemas.ai_creator_map_reduce import CreatorPerformanceAudienceReduction
    from .test_creator_map_reduce_pipeline import _output_for, _pipeline
    from .test_creator_map_reduce import _list_claim

    data = _output_for(CreatorPerformanceAudienceReduction).model_dump(mode="json")
    claim = _list_claim(
        "Strategy",
        reference="batch:0:unknown",
        source_type="intermediate_output",
        kind="ai_inference",
    )
    claim["provenance"] = "ai_inference"
    data["audience_inference"]["interests"] = claim
    original = CreatorPerformanceAudienceReduction.model_validate(data)
    fixed = deepcopy(data)
    fixed["audience_inference"]["interests"]["evidence"][0][
        "reference"
    ] = "batch:0:performance_audience.audience_signals"
    corrected = CreatorPerformanceAudienceReduction.model_validate(fixed)
    assert _content_format_without_bindings(
        original
    ) == _content_format_without_bindings(corrected)
    changed = deepcopy(fixed)
    changed["audience_inference"]["interests"]["evidence"][0][
        "observation"
    ] = "A changed observation."
    assert _content_format_without_bindings(
        original
    ) != _content_format_without_bindings(
        CreatorPerformanceAudienceReduction.model_validate(changed)
    )

    class AI:
        def __init__(self):
            self.outputs = iter((original, corrected))

        def complete_structured(self, *args, **kwargs):
            return next(self.outputs)

    pipeline, *_ = _pipeline(ai=AI())
    catalog = EvidenceCatalog(
        entries=(
            EvidenceCatalogEntry(
                reference="batch:0:performance_audience.audience_signals",
                source_type="intermediate_output",
                allowed_kinds=("ai_inference",),
            ),
        )
    )
    result = pipeline._structured_stage(
        model="deepseek-flash",
        messages=[],
        schema=CreatorPerformanceAudienceReduction,
        catalog=catalog,
    )
    assert result == corrected
