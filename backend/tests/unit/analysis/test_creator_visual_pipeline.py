"""Visual-stage evidence failures stay bounded, observable, and unavailable."""

import logging

import pytest

from app.analysis.creator_pipeline import unavailable_visual_analysis
from app.schemas.ai_creator import CreatorVisualAnalysis

from .test_creator_map_reduce_pipeline import _pipeline
from .test_creator_pipeline import _source
from .test_prompts import available_creator_visual


class VisualResults:
    def __init__(self, *outputs: CreatorVisualAnalysis) -> None:
        self.outputs = outputs
        self.calls = 0

    def complete_vision(self, *args, **kwargs) -> CreatorVisualAnalysis:
        del args, kwargs
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return output


def _wrong_reference() -> CreatorVisualAnalysis:
    payload = available_creator_visual().model_dump(mode="json")
    payload["visual_style"]["evidence"][0][
        "reference"
    ] = "video:untrusted-reference-canary:thumbnail:0"
    return CreatorVisualAnalysis.model_validate(payload)


def test_visual_evidence_rejection_is_bounded_and_logged_without_model_content(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Alembic's fileConfig can disable existing loggers in the full suite.
    monkeypatch.setattr(
        logging.getLogger("app.analysis.creator_map_reduce_pipeline"), "disabled", False
    )
    source = _source()
    ai = VisualResults(_wrong_reference())
    pipeline, *_ = _pipeline(source=source, ai=ai)

    with caplog.at_level(logging.WARNING):
        result = pipeline._visual_analysis(source, source.videos)

    assert ai.calls == 2
    assert result.status == "unavailable"
    assert all(
        getattr(result, name).status == "unavailable"
        for name in (
            "visual_style",
            "production_quality_signals",
            "thumbnail_patterns",
            "thumbnail_readability",
            "branding",
        )
    )
    assert caplog.text.count("reason=evidence_catalog_mismatch") == 2
    assert "attempt=1" in caplog.text
    assert "attempt=2" in caplog.text
    assert "untrusted-reference-canary" not in caplog.text
    assert "Consistent high-contrast thumbnail layout." not in caplog.text


def test_visual_evidence_retry_can_return_a_valid_partial_result() -> None:
    source = _source()
    expected = available_creator_visual()
    ai = VisualResults(_wrong_reference(), expected)
    pipeline, *_ = _pipeline(source=source, ai=ai)

    result = pipeline._visual_analysis(source, source.videos)

    assert ai.calls == 2
    assert result == expected
    assert result.status == "available"
    assert result.branding.status == "unavailable"


def test_visual_unavailable_result_is_not_forced_to_available() -> None:
    source = _source()
    expected = unavailable_visual_analysis("No reliable visible detail.")
    ai = VisualResults(expected)
    pipeline, *_ = _pipeline(source=source, ai=ai)

    result = pipeline._visual_analysis(source, source.videos)

    assert ai.calls == 1
    assert result == expected
    assert result.status == "unavailable"
