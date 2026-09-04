from __future__ import annotations

from copy import deepcopy
from threading import Barrier, Lock
from typing import TypeVar

import pytest
from pydantic import BaseModel

from app.analysis.creator_map_reduce_pipeline import (
    BATCH_NODE_PREFIX,
    BRIEF_NODE_KEY,
    CONTACT_NODE_KEY,
    REDUCTION_NODE_KEYS,
    SOURCE_NODE_KEY,
    VISUAL_NODE_KEY,
    CreatorMapReducePipeline,
    CreatorSourceCheckpoint,
)
from app.analysis.prompts.common import parse_prompt_payload
from app.integrations.errors import TransientIntegrationError
from app.schemas.ai_creator import CreatorVisualAnalysis
from app.schemas.ai_creator_map_reduce import (
    CreatorBriefSynthesis,
    CreatorCommercialSafetyReduction,
    CreatorContentFormatReduction,
    CreatorPerformanceAudienceReduction,
    CreatorPresentationReduction,
    CreatorVideoBatchDigest,
)

from .test_creator_pipeline import (
    FakeArtifacts,
    FakePages,
    FakeService,
    FakeYouTube,
    Page,
    _source,
    _visual,
)


T = TypeVar("T", bound=BaseModel)


def _unavailable() -> dict[str, str]:
    return {"status": "unavailable", "reason": "No reliable public evidence."}


def _unavailable_inference() -> dict[str, str]:
    return {
        "status": "unavailable",
        "reason": "No reliable public evidence.",
        "provenance": "ai_inference",
    }


def _batch() -> CreatorVideoBatchDigest:
    return CreatorVideoBatchDigest.model_validate(
        {
            "english_language_check": True,
            "content_format": {
                "content_focus": _unavailable(),
                "primary_games": _unavailable(),
                "genres": _unavailable(),
                "formats": _unavailable(),
                "format_tendencies": _unavailable(),
                "representative_video_context": _unavailable(),
            },
            "presentation": {
                "style_and_pacing": _unavailable(),
                "production_signals": _unavailable(),
            },
            "performance_audience": {
                "recent_performance": _unavailable(),
                "engagement": _unavailable(),
                "publishing_cadence": _unavailable(),
                "audience_signals": _unavailable(),
            },
            "commercial_safety": {
                "sponsorship_signals": _unavailable(),
                "brand_safety_signals": _unavailable(),
                "collaboration_risks": _unavailable(),
            },
        }
    )


def _output_for(schema: type[T]) -> T:
    if schema is CreatorVideoBatchDigest:
        return _batch()  # type: ignore[return-value]
    fields: dict[type[BaseModel], dict[str, object]] = {
        CreatorContentFormatReduction: {
            "content_summary": _unavailable(),
            "primary_games": _unavailable(),
            "genres": _unavailable(),
            "formats": _unavailable(),
            "livestream_tendency": _unavailable(),
            "long_form_tendency": _unavailable(),
            "short_form_tendency": _unavailable(),
            "representative_video_context": _unavailable(),
            "suitable_game_types": _unavailable(),
        },
        CreatorPresentationReduction: {
            "style": _unavailable(),
            "pacing": _unavailable(),
            "production_quality": _unavailable(),
        },
        CreatorPerformanceAudienceReduction: {
            "recent_performance_summary": _unavailable(),
            "engagement_summary": _unavailable(),
            "publishing_frequency_context": _unavailable(),
            "audience_inference": {
                "primary_language": _unavailable_inference(),
                "likely_regions": _unavailable_inference(),
                "interests": _unavailable_inference(),
            },
        },
        CreatorCommercialSafetyReduction: {
            "sponsorship_patterns": _unavailable(),
            "brand_safety": _unavailable(),
            "collaboration_risks": _unavailable(),
        },
        CreatorBriefSynthesis: {
            "public_email": _unavailable(),
            "linked_site": _unavailable(),
            "social_links": _unavailable(),
            "creator_brief": {
                "positioning": _unavailable(),
                "content_focus": _unavailable(),
                "formats": _unavailable(),
                "style_and_pacing": _unavailable(),
                "audience": _unavailable_inference(),
                "performance_context": _unavailable(),
                "promotion_fit": _unavailable(),
                "brand_safety": _unavailable(),
                "suitable_game_types": _unavailable(),
                "collaboration_risks": _unavailable(),
            },
        },
    }
    payload = {"english_language_check": True, **fields[schema]}
    return schema.model_validate(payload)


class MemoryCheckpoints:
    def __init__(self) -> None:
        self.values: dict[str, BaseModel] = {}

    def load(self, job_id, node_key: str, schema: type[T]) -> T | None:
        del job_id
        value = self.values.get(node_key)
        if value is None:
            return None
        return schema.model_validate(value.model_dump(mode="json"))

    def save_success(self, job_id, node_key: str, output: T) -> T:
        del job_id
        existing = self.values.setdefault(node_key, output)
        return type(output).model_validate(existing.model_dump(mode="json"))


class ConcurrentAI:
    def __init__(
        self,
        *,
        synchronize_batches: int = 0,
        fail_batch_once: int | None = None,
        fail_brief_once: bool = False,
    ) -> None:
        self.calls: list[tuple[type[BaseModel], int | None, int | None]] = []
        self.vision_calls = 0
        self.max_active_batches = 0
        self._active_batches = 0
        self._lock = Lock()
        self._barrier = (
            Barrier(synchronize_batches) if synchronize_batches > 1 else None
        )
        self._fail_batch_once = fail_batch_once
        self._failed_batch = False
        self._fail_brief_once = fail_brief_once
        self._failed_brief = False

    def complete_structured(
        self,
        model,
        messages,
        schema: type[T],
        *,
        max_tokens: int | None = None,
    ) -> T:
        del model
        batch_index = None
        if schema is CreatorVideoBatchDigest:
            batch_index = parse_prompt_payload(messages)["batch_index"]
        with self._lock:
            self.calls.append((schema, batch_index, max_tokens))
        if schema is CreatorVideoBatchDigest:
            with self._lock:
                self._active_batches += 1
                self.max_active_batches = max(
                    self.max_active_batches, self._active_batches
                )
            try:
                if self._barrier is not None:
                    self._barrier.wait(timeout=5)
                if batch_index == self._fail_batch_once and not self._failed_batch:
                    self._failed_batch = True
                    raise TransientIntegrationError("deepseek_unavailable")
                return _output_for(schema)
            finally:
                with self._lock:
                    self._active_batches -= 1
        if schema is CreatorBriefSynthesis and self._fail_brief_once:
            if not self._failed_brief:
                self._failed_brief = True
                raise TransientIntegrationError("deepseek_unavailable")
        return _output_for(schema)

    def complete_vision(
        self,
        model,
        prompt,
        image_urls,
        schema,
        *,
        max_tokens: int | None = None,
    ) -> CreatorVisualAnalysis:
        del model, prompt, image_urls, schema, max_tokens
        with self._lock:
            self.vision_calls += 1
        return _visual()


def _twenty_video_source():
    source = _source()
    prototype = source.videos[0]
    videos = tuple(
        prototype.model_copy(
            update={
                "id": f"video-{index}",
                "title": f"Video {index}",
                "raw": {"secret": "raw-video-canary"},
            }
        )
        for index in range(20)
    )
    return source.model_copy(
        update={
            "videos": videos,
            "raw_channel": {"secret": "raw-channel-canary"},
            "raw_playlist_pages": ({"secret": "raw-playlist-canary"},),
            "raw_video_responses": ({"secret": "raw-response-canary"},),
        }
    )


def _pipeline(*, source=None, ai=None, checkpoints=None):
    service = FakeService()
    source = source or _twenty_video_source()
    youtube = FakeYouTube(source, service)
    artifacts = FakeArtifacts(service)
    pages = FakePages(
        {
            "https://creator.example/about": Page(
                "https://creator.example/about", "Business: team@example.com"
            )
        }
    )
    ai = ai or ConcurrentAI()
    checkpoints = checkpoints or MemoryCheckpoints()
    pipeline = CreatorMapReducePipeline(
        service=service,
        youtube=youtube,
        artifacts=artifacts,
        public_pages=pages,
        deepseek=ai,
        checkpoints=checkpoints,
        max_parallel_calls=5,
    )
    return pipeline, service, youtube, artifacts, ai, checkpoints


def test_pipeline_runs_bounded_batches_concurrently_and_finalizes() -> None:
    ai = ConcurrentAI(synchronize_batches=2)
    pipeline, service, youtube, artifacts, ai, checkpoints = _pipeline(ai=ai)

    assert pipeline.run(service.job_id) == service.profile_id

    assert ai.max_active_batches >= 2
    assert youtube.calls == [("UCcreator123", 50)]
    assert len(artifacts.calls) == 3
    assert service.publication is not None
    assert service.events == [
        ("start", service.job_id),
        ("advance", service.job_id, 2),
        ("advance", service.job_id, 4),
        ("finalize", service.job_id),
    ]
    assert set(checkpoints.values) == {
        SOURCE_NODE_KEY,
        f"{BATCH_NODE_PREFIX}00",
        f"{BATCH_NODE_PREFIX}01",
        VISUAL_NODE_KEY,
        CONTACT_NODE_KEY,
        *REDUCTION_NODE_KEYS.values(),
        BRIEF_NODE_KEY,
    }
    structured = [call for call in ai.calls if call[0] is not CreatorVisualAnalysis]
    assert len(structured) == 7
    assert all(
        max_tokens == schema.deepseek_max_tokens for schema, _, max_tokens in structured
    )


def test_retry_reuses_all_successful_checkpoints_and_only_calls_missing_brief() -> None:
    ai = ConcurrentAI(fail_brief_once=True)
    pipeline, service, youtube, _, ai, checkpoints = _pipeline(ai=ai)

    with pytest.raises(TransientIntegrationError, match="deepseek_unavailable"):
        pipeline.run(service.job_id)
    calls_before_retry = len(ai.calls)
    assert BRIEF_NODE_KEY not in checkpoints.values

    assert pipeline.run(service.job_id) == service.profile_id

    assert youtube.calls == [("UCcreator123", 50)]
    assert len(ai.calls) == calls_before_retry + 1
    assert ai.calls[-1][0] is CreatorBriefSynthesis
    assert BRIEF_NODE_KEY in checkpoints.values


def test_failed_parallel_wave_harvests_other_successes_before_retry() -> None:
    ai = ConcurrentAI(fail_batch_once=0)
    pipeline, service, youtube, _, ai, checkpoints = _pipeline(ai=ai)

    with pytest.raises(TransientIntegrationError, match="deepseek_unavailable"):
        pipeline.run(service.job_id)

    assert f"{BATCH_NODE_PREFIX}00" not in checkpoints.values
    assert f"{BATCH_NODE_PREFIX}01" in checkpoints.values
    assert VISUAL_NODE_KEY in checkpoints.values
    assert CONTACT_NODE_KEY in checkpoints.values
    assert not any(key in checkpoints.values for key in REDUCTION_NODE_KEYS.values())

    assert pipeline.run(service.job_id) == service.profile_id
    batch_calls = [call for call in ai.calls if call[0] is CreatorVideoBatchDigest]
    assert [call[1] for call in batch_calls].count(0) == 2
    assert [call[1] for call in batch_calls].count(1) == 1
    assert youtube.calls == [("UCcreator123", 50)]


def test_source_checkpoint_is_curated_and_excludes_raw_provider_envelopes() -> None:
    pipeline, service, _, _, _, checkpoints = _pipeline()

    pipeline.run(service.job_id)

    checkpoint = checkpoints.values[SOURCE_NODE_KEY]
    assert isinstance(checkpoint, CreatorSourceCheckpoint)
    serialized = checkpoint.model_dump_json()
    assert "raw-channel-canary" not in serialized
    assert "raw-playlist-canary" not in serialized
    assert "raw-response-canary" not in serialized
    assert "raw-video-canary" not in serialized
    restored = checkpoint.to_source()
    assert len(restored.videos) == 20
    assert restored.raw_channel == {}
    assert all(video.raw == {} for video in restored.videos)
