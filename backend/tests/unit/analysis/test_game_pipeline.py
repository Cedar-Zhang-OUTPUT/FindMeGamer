from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.analysis.contracts import SteamGameSource
from app.analysis.game_pipeline import (
    EXTRACTION_MODEL,
    SYNTHESIS_MODEL,
    VISION_MODEL,
    GameAnalysisPipeline,
)
from app.analysis.prompts.game import (
    build_game_extraction_bundle,
    build_game_synthesis_bundle,
    build_game_visual_bundle,
)
from app.analysis.prompts.common import PromptBundle, render_vision_prompt
from app.analysis.service import GameAnalysisPublication, GameJobLease
from app.integrations.errors import (
    InvalidModelOutput,
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.schemas.ai_game import (
    EvidenceCatalog,
    GameExtraction,
    GameSynthesis,
    GameVisualAnalysis,
)

from .test_ai_schemas import game_extraction_payload, game_synthesis_payload
from .test_prompts import sample_game_source


def _visual_payload() -> dict[str, object]:
    evidence = [
        {
            "kind": "visual_observation",
            "source_type": "visual_asset",
            "reference": "cover:0",
            "observation": "The cover uses a dark gold palette.",
        }
    ]
    text = {
        "status": "available",
        "value": "Dark fantasy with high-contrast gold accents.",
        "evidence": evidence,
        "confidence": "high",
    }
    values = {
        "status": "available",
        "values": ["Dark fantasy"],
        "evidence": evidence,
        "confidence": "high",
    }
    return {
        "english_language_check": True,
        "status": "available",
        "unavailable_reason": None,
        "visual_style": text,
        "visual_motifs": values,
        "readability": text,
        "content_hook_observations": values,
    }


class FakeService:
    def __init__(self, *, completed_profile_id: UUID | None = None) -> None:
        self.job_id = uuid4()
        self.profile_id = completed_profile_id or uuid4()
        self.completed_profile_id = completed_profile_id
        self.events: list[tuple[object, ...]] = []
        self.publication: GameAnalysisPublication | None = None
        self.active = False

    def start(self, job_id: UUID) -> GameJobLease:
        self.active = True
        try:
            self.events.append(("start", job_id))
            return GameJobLease(
                job_id=job_id,
                app_id="1245620",
                canonical_url="https://store.steampowered.com/app/1245620",
                completed_profile_id=self.completed_profile_id,
            )
        finally:
            self.active = False

    def advance(self, job_id: UUID, *, completed_units: int) -> None:
        self.active = True
        try:
            self.events.append(("advance", job_id, completed_units))
        finally:
            self.active = False

    def finalize(
        self, lease: GameJobLease, publication: GameAnalysisPublication
    ) -> UUID:
        self.active = True
        try:
            self.events.append(("finalize", lease.job_id))
            self.publication = publication
            return self.profile_id
        finally:
            self.active = False


class FakeSteam:
    def __init__(
        self, source: SteamGameSource, service: FakeService, events: list
    ) -> None:
        self.source = source
        self.service = service
        self.events = events
        self.calls = 0

    def fetch_game(self, app_id: str) -> SteamGameSource:
        assert not self.service.active
        self.calls += 1
        self.events.append(("steam", app_id))
        return self.source


class FakeArtifacts:
    def __init__(self, service: FakeService, events: list) -> None:
        self.service = service
        self.events = events
        self.calls: list[tuple[UUID, str, object]] = []

    def put_json(self, job_id: UUID, name: str, payload: object) -> str:
        assert not self.service.active
        self.events.append(("artifact", name))
        self.calls.append((job_id, name, payload))
        return f"acquisition/{job_id}/{name}"


class FakeDeepSeek:
    def __init__(
        self,
        service: FakeService,
        events: list,
        *,
        structured: list[object],
        vision: list[object] | None = None,
    ) -> None:
        self.service = service
        self.events = events
        self.structured = list(structured)
        self.vision = list(vision or [])
        self.structured_calls: list[tuple[str, object, object]] = []
        self.vision_calls: list[tuple[str, str, list[str], object]] = []

    def complete_structured(self, model: str, messages: list, schema: type) -> object:
        assert not self.service.active
        self.events.append(("structured", model, schema.__name__))
        self.structured_calls.append((model, messages, schema))
        result = self.structured.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def complete_vision(
        self, model: str, prompt: str, image_urls: list[str], schema: type
    ) -> object:
        assert not self.service.active
        self.events.append(("vision", model))
        self.vision_calls.append((model, prompt, image_urls, schema))
        result = self.vision.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _pipeline(
    *,
    source: SteamGameSource | None = None,
    structured: list[object] | None = None,
    vision: list[object] | None = None,
    completed_profile_id: UUID | None = None,
) -> tuple[
    GameAnalysisPipeline, FakeService, FakeSteam, FakeArtifacts, FakeDeepSeek, list
]:
    service = FakeService(completed_profile_id=completed_profile_id)
    events: list[tuple[object, ...]] = service.events
    source = source or sample_game_source()
    extraction = GameExtraction.model_validate(game_extraction_payload())
    synthesis = GameSynthesis.model_validate(game_synthesis_payload())
    steam = FakeSteam(source, service, events)
    artifacts = FakeArtifacts(service, events)
    deepseek = FakeDeepSeek(
        service,
        events,
        structured=structured or [extraction, synthesis],
        vision=vision or [GameVisualAnalysis.model_validate(_visual_payload())],
    )
    return (
        GameAnalysisPipeline(
            service=service,
            steam=steam,
            artifacts=artifacts,
            deepseek=deepseek,
        ),
        service,
        steam,
        artifacts,
        deepseek,
        events,
    )


def test_pipeline_uses_exact_stage_bundles_models_and_order() -> None:
    pipeline, service, _, artifacts, deepseek, events = _pipeline()

    assert pipeline.run(service.job_id) == service.profile_id

    source = sample_game_source()
    extraction = GameExtraction.model_validate(game_extraction_payload())
    visual = GameVisualAnalysis.model_validate(_visual_payload())
    extraction_bundle = build_game_extraction_bundle(source)
    visual_bundle = build_game_visual_bundle(source)
    synthesis_bundle = build_game_synthesis_bundle(source, extraction, visual)
    assert artifacts.calls == [(service.job_id, "steam-source.json", source.raw)]
    assert deepseek.structured_calls == [
        (EXTRACTION_MODEL, list(extraction_bundle.messages), GameExtraction),
        (SYNTHESIS_MODEL, list(synthesis_bundle.messages), GameSynthesis),
    ]
    assert deepseek.vision_calls == [
        (
            VISION_MODEL,
            render_vision_prompt(visual_bundle.messages),
            list(visual_bundle.image_urls),
            GameVisualAnalysis,
        )
    ]
    assert deepseek.vision_calls[0][1].startswith("SYSTEM\n")
    assert events == [
        ("start", service.job_id),
        ("steam", "1245620"),
        ("artifact", "steam-source.json"),
        ("advance", service.job_id, 2),
        ("structured", EXTRACTION_MODEL, "GameExtraction"),
        ("vision", VISION_MODEL),
        ("structured", SYNTHESIS_MODEL, "GameSynthesis"),
        ("advance", service.job_id, 4),
        ("finalize", service.job_id),
    ]


def test_semantically_invalid_extraction_gets_one_clean_retry() -> None:
    invalid = deepcopy(game_extraction_payload())
    invalid["short_summary"]["evidence"][0]["reference"] = "steam:not-supplied"
    pipeline, service, _, _, deepseek, _ = _pipeline(
        structured=[
            GameExtraction.model_validate(invalid),
            GameExtraction.model_validate(game_extraction_payload()),
            GameSynthesis.model_validate(game_synthesis_payload()),
        ]
    )

    pipeline.run(service.job_id)

    assert [call[0] for call in deepseek.structured_calls] == [
        EXTRACTION_MODEL,
        EXTRACTION_MODEL,
        SYNTHESIS_MODEL,
    ]
    assert deepseek.structured_calls[0][1] == deepseek.structured_calls[1][1]


def test_semantically_invalid_synthesis_fails_after_one_clean_retry() -> None:
    invalid = deepcopy(game_synthesis_payload())
    invalid["short_summary"]["evidence"][0]["reference"] = "steam:not-supplied"
    extraction = GameExtraction.model_validate(game_extraction_payload())
    bad = GameSynthesis.model_validate(invalid)
    pipeline, service, _, _, deepseek, _ = _pipeline(structured=[extraction, bad, bad])

    with pytest.raises(InvalidModelOutput, match="deepseek_model_evidence_invalid"):
        pipeline.run(service.job_id)

    assert len(deepseek.structured_calls) == 3
    assert service.publication is None


def test_empty_image_source_skips_vision_and_uses_exact_unavailable_schema() -> None:
    source = sample_game_source().model_copy(
        update={
            "cover_image_url": None,
            "header_image_url": None,
            "screenshots": (),
            "movies": (),
        }
    )
    pipeline, service, _, _, deepseek, _ = _pipeline(source=source, vision=[])

    pipeline.run(service.job_id)

    assert deepseek.vision_calls == []
    assert service.publication is not None
    visual = service.publication.visual
    assert visual.model_dump(mode="json") == {
        "english_language_check": True,
        "status": "unavailable",
        "unavailable_reason": "No usable public static game images were supplied.",
        "visual_style": {
            "status": "unavailable",
            "reason": "No usable public static game images were supplied.",
        },
        "visual_motifs": {
            "status": "unavailable",
            "reason": "No usable public static game images were supplied.",
        },
        "readability": {
            "status": "unavailable",
            "reason": "No usable public static game images were supplied.",
        },
        "content_hook_observations": {
            "status": "unavailable",
            "reason": "No usable public static game images were supplied.",
        },
    }


@pytest.mark.parametrize(
    "failure",
    [
        TransientIntegrationError("vision_unavailable"),
        PermanentIntegrationError("vision_rejected"),
        InvalidModelOutput("vision_model_output_invalid"),
    ],
)
def test_vision_integration_failures_retry_once_then_fall_back(failure) -> None:
    pipeline, service, _, _, deepseek, _ = _pipeline(vision=[failure, failure])

    pipeline.run(service.job_id)

    assert len(deepseek.vision_calls) == 2
    assert service.publication is not None
    assert service.publication.visual.status == "unavailable"


def test_transient_vision_failure_can_recover_on_its_single_retry() -> None:
    available = GameVisualAnalysis.model_validate(_visual_payload())
    pipeline, service, _, _, deepseek, _ = _pipeline(
        vision=[TransientIntegrationError("vision_unavailable"), available]
    )

    pipeline.run(service.job_id)

    assert len(deepseek.vision_calls) == 2
    assert service.publication is not None
    assert service.publication.visual.status == "available"


def test_vision_does_not_swallow_process_control_failures() -> None:
    pipeline, service, *_ = _pipeline(vision=[KeyboardInterrupt()])

    with pytest.raises(KeyboardInterrupt):
        pipeline.run(service.job_id)


def test_vision_does_not_swallow_gateway_programmer_value_error() -> None:
    programmer_bug = ValueError("programmer bug")
    pipeline, service, _, _, deepseek, events = _pipeline(
        vision=[programmer_bug, programmer_bug]
    )

    with pytest.raises(ValueError, match="programmer bug"):
        pipeline.run(service.job_id)

    assert len(deepseek.vision_calls) == 1
    assert service.publication is None
    assert not any(event[0] == "finalize" for event in events)


def test_semantically_invalid_vision_retries_once_then_falls_back() -> None:
    invalid = _visual_payload()
    invalid["visual_style"]["evidence"][0]["reference"] = "cover:not-supplied"
    visual = GameVisualAnalysis.model_validate(invalid)
    pipeline, service, _, _, deepseek, _ = _pipeline(vision=[visual, visual])

    pipeline.run(service.job_id)

    assert len(deepseek.vision_calls) == 2
    assert service.publication is not None
    assert service.publication.visual.status == "unavailable"


def test_invalid_static_image_is_nonfatal_without_provider_call() -> None:
    source = sample_game_source().model_copy(
        update={"cover_image_url": "https://cdn.example/dynamic-image"}
    )
    pipeline, service, _, _, deepseek, _ = _pipeline(source=source, vision=[])

    pipeline.run(service.job_id)

    assert deepseek.vision_calls == []
    assert service.publication is not None
    assert service.publication.visual.status == "unavailable"


def test_visual_bundle_programmer_value_error_propagates_without_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, service, _, _, deepseek, events = _pipeline()

    def programmer_bug(source: SteamGameSource):
        raise ValueError("programmer bug")

    monkeypatch.setattr(
        "app.analysis.game_pipeline.build_game_visual_bundle", programmer_bug
    )

    with pytest.raises(ValueError, match="programmer bug"):
        pipeline.run(service.job_id)

    assert deepseek.vision_calls == []
    assert service.publication is None
    assert not any(event[0] == "finalize" for event in events)


def test_visual_bundle_unrelated_validation_error_propagates_without_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, service, _, _, deepseek, events = _pipeline()
    with pytest.raises(ValidationError) as captured:
        PromptBundle(messages=(), evidence_catalog=EvidenceCatalog(entries=()))

    def unrelated_bundle_invariant(source: SteamGameSource):
        raise captured.value

    monkeypatch.setattr(
        "app.analysis.game_pipeline.build_game_visual_bundle",
        unrelated_bundle_invariant,
    )

    with pytest.raises(ValidationError) as raised:
        pipeline.run(service.job_id)

    assert raised.value is captured.value
    assert deepseek.vision_calls == []
    assert service.publication is None
    assert not any(event[0] == "finalize" for event in events)


def test_mismatched_source_identity_is_safe_and_never_persisted() -> None:
    source = sample_game_source().model_copy(update={"app_id": "999"})
    pipeline, service, _, artifacts, deepseek, _ = _pipeline(source=source)

    with pytest.raises(
        PermanentIntegrationError, match="steam_source_identity_mismatch"
    ):
        pipeline.run(service.job_id)

    assert artifacts.calls == []
    assert deepseek.structured_calls == []
    assert service.publication is None


def test_succeeded_job_is_idempotent_without_external_calls() -> None:
    profile_id = uuid4()
    pipeline, service, steam, artifacts, deepseek, events = _pipeline(
        completed_profile_id=profile_id
    )

    assert pipeline.run(service.job_id) == profile_id

    assert steam.calls == 0
    assert artifacts.calls == []
    assert deepseek.structured_calls == []
    assert events == [("start", service.job_id)]


def test_progress_is_coarse_monotonic_and_bounded() -> None:
    pipeline, service, *_ = _pipeline()

    pipeline.run(service.job_id)

    completed = [event[2] for event in service.events if event[0] == "advance"]
    assert completed == [2, 4]
    assert all(0 <= value <= 5 for value in completed)
