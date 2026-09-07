"""Bounded citation repair never substitutes invented evidence or weaker content."""

from copy import deepcopy
import logging

import pytest

from app.analysis.creator_map_reduce_pipeline import REDUCTION_MODEL
from app.analysis.prompts.creator_map_reduce import build_creator_content_format_bundle
from app.integrations.errors import InvalidModelOutput
from app.schemas.ai_creator_map_reduce import (
    CreatorContentFormatReduction,
    CreatorVideoBatchDigest,
)
from app.schemas.ai_game import validate_stage_evidence
from .test_creator_map_reduce import _batch_payload, _reducer_text
from .test_creator_map_reduce_pipeline import (
    BRIEF_NODE_KEY,
    REDUCTION_NODE_KEYS,
    ConcurrentAI,
    _output_for,
    _pipeline,
    _twenty_video_source,
)
from app.analysis.prompts.common import parse_prompt_payload


@pytest.fixture(autouse=True)
def enabled_content_format_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    # Migration tests may disable existing loggers; caplog only restores levels.
    monkeypatch.setattr(
        logging.getLogger("app.analysis.creator_map_reduce_pipeline"), "disabled", False
    )


class EvidenceAI:
    def __init__(self, outputs):
        self.outputs = outputs
        self.messages = []

    def complete_structured(self, model, messages, schema, *, max_tokens=None):
        assert model == REDUCTION_MODEL
        assert schema is CreatorContentFormatReduction
        assert max_tokens == schema.deepseek_max_tokens
        self.messages.append(list(messages))
        return self.outputs[len(self.messages) - 1]


def _good():
    payload = _output_for(CreatorContentFormatReduction).model_dump(mode="json")
    payload["content_summary"] = _reducer_text("content_focus", "content_format")
    return CreatorContentFormatReduction.model_validate(payload)


def _bundle():
    digest = CreatorVideoBatchDigest.model_validate(_batch_payload())
    return build_creator_content_format_bundle((digest,))


def _bad_reference(output):
    raw = deepcopy(output.model_dump(mode="json"))
    # Schema-valid but not an allowed citation in this reducer's current catalog.
    raw["content_summary"]["evidence"][0][
        "reference"
    ] = "video:private-reference-canary"
    raw["content_summary"]["evidence"][0]["source_type"] = "video_id"
    return CreatorContentFormatReduction.model_validate(raw)


def _run(ai):
    pipeline, *_ = _pipeline(ai=ai)
    bundle = _bundle()
    original = list(bundle.messages)
    output = pipeline._structured_stage(
        model=REDUCTION_MODEL,
        messages=original,
        schema=CreatorContentFormatReduction,
        catalog=bundle.evidence_catalog,
    )
    assert original == list(bundle.messages)
    return output


@pytest.mark.parametrize("reason", ["unknown_reference", "source_type_mismatch"])
def test_content_format_retry_supplies_binding_feedback_and_preserves_content(
    caplog, reason
) -> None:
    good = _good()
    invalid = _bad_reference(good)
    if reason == "source_type_mismatch":
        payload = invalid.model_dump(mode="json")
        payload["content_summary"]["evidence"][0]["reference"] = (
            good.content_summary.evidence[0].reference
        )
        invalid = CreatorContentFormatReduction.model_validate(payload)
    ai = EvidenceAI([invalid, good])

    assert _run(ai) == good

    assert len(ai.messages) == 2
    second = ai.messages[1]
    assert second[: len(ai.messages[0])] == ai.messages[0]
    assert len(second) == len(ai.messages[0]) + 2
    assert second[-2].role == "assistant"
    assert second[-2].content == invalid.model_dump_json()
    assert reason in second[-1].content
    assert "Change only evidence reference, source_type, and kind" in second[-1].content
    assert "creator_content_format_evidence_rejected" in caplog.text
    assert f"reason={reason}" in caplog.text
    assert "private-reference-canary" not in caplog.text


@pytest.mark.parametrize("changed_field", ["content", "unavailable", "observation"])
def test_content_format_repair_cannot_drop_or_rewrite_supported_content(
    changed_field,
) -> None:
    original = _good()
    repaired = original.model_dump(mode="json")
    if changed_field == "content":
        repaired["content_summary"][
            "value"
        ] = "A materially different characterization."
    elif changed_field == "unavailable":
        repaired["content_summary"] = {
            "status": "unavailable",
            "reason": "Discarded the claim.",
        }
    else:
        repaired["content_summary"]["evidence"][0][
            "observation"
        ] = "Discarded the original observation."
    ai = EvidenceAI(
        [
            _bad_reference(original),
            CreatorContentFormatReduction.model_validate(repaired),
        ]
    )

    with pytest.raises(InvalidModelOutput, match="deepseek_model_evidence_invalid"):
        _run(ai)

    assert len(ai.messages) == 2


def test_content_format_repair_still_rejects_unbound_evidence_after_two_calls(
    caplog,
) -> None:
    invalid = _bad_reference(_good())
    ai = EvidenceAI([invalid, invalid])

    with pytest.raises(InvalidModelOutput, match="deepseek_model_evidence_invalid"):
        _run(ai)

    assert len(ai.messages) == 2
    assert "attempt=2 reason=unknown_reference" in caplog.text
    assert "private-reference-canary" not in caplog.text
    with pytest.raises(ValueError, match="not bound"):
        validate_stage_evidence(invalid, _bundle().evidence_catalog)


def test_failed_content_binding_preserves_eleven_nodes_then_resumes_only_content_and_brief() -> (
    None
):
    class FailingContentAI(ConcurrentAI):
        def __init__(self):
            super().__init__()
            self.binding_valid = False

        def complete_structured(self, model, messages, schema, *, max_tokens=None):
            if schema is CreatorVideoBatchDigest:
                index = parse_prompt_payload(messages)["batch_index"]
                self.calls.append((schema, index, max_tokens))
                payload = _batch_payload()
                for section in payload.values():
                    if not isinstance(section, dict):
                        continue
                    for claim in section.values():
                        for reference in claim["evidence"]:
                            reference["reference"] = f"video:video-{index * 10}"
                return CreatorVideoBatchDigest.model_validate(payload)
            if schema is CreatorContentFormatReduction:
                self.calls.append((schema, None, max_tokens))
                return _good() if self.binding_valid else _bad_reference(_good())
            return super().complete_structured(
                model, messages, schema, max_tokens=max_tokens
            )

    source = _twenty_video_source()
    source = source.model_copy(
        update={
            "videos": tuple(
                source.videos[0].model_copy(
                    update={"id": f"video-{index}", "title": f"Video {index}"}
                )
                for index in range(50)
            )
        }
    )
    ai = FailingContentAI()
    pipeline, service, youtube, _, _, checkpoints = _pipeline(source=source, ai=ai)

    with pytest.raises(InvalidModelOutput, match="deepseek_model_evidence_invalid"):
        pipeline.run(service.job_id)

    saved = deepcopy(checkpoints.values)
    assert len(saved) == 11
    assert REDUCTION_NODE_KEYS["content_format"] not in saved
    assert BRIEF_NODE_KEY not in saved
    assert service.publication is None
    old_calls = len(ai.calls)
    old_vision_calls = ai.vision_calls
    ai.binding_valid = True

    assert pipeline.run(service.job_id) == service.profile_id

    assert len(ai.calls) == old_calls + 2
    assert [schema for schema, _, _ in ai.calls[-2:]] == [
        CreatorContentFormatReduction,
        type(checkpoints.values[BRIEF_NODE_KEY]),
    ]
    assert ai.vision_calls == old_vision_calls
    assert youtube.calls == [("UCcreator123", 50)]
    assert all(checkpoints.values[key] == value for key, value in saved.items())
