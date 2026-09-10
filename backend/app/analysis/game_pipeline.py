"""Transactional orchestration for Steam Game Profile analysis."""

from __future__ import annotations

from typing import Protocol, TypeVar
from uuid import UUID

from app.analysis.contracts import ArtifactStore, Message, SteamGameSource
from app.analysis.prompts.game import (
    build_game_extraction_bundle,
    build_game_synthesis_bundle,
    build_game_visual_bundle,
)
from app.analysis.prompts.common import InvalidVisualAssetInput, render_vision_prompt
from app.analysis.service import GameAnalysisPublication, GameAnalysisService
from app.integrations.errors import (
    IntegrationError,
    InvalidModelOutput,
    PermanentIntegrationError,
)
from app.schemas.ai_game import (
    EvidenceCatalog,
    GameExtraction,
    GameSynthesis,
    GameVisualAnalysis,
    StageOutput,
    UnavailableClaim,
    validate_stage_evidence,
)


EXTRACTION_MODEL = "deepseek-flash"
VISION_MODEL = "deepseek-flash"
SYNTHESIS_MODEL = "deepseek-flash"
RAW_STEAM_ARTIFACT_NAME = "steam-source.json"
_NO_IMAGES_REASON = "No usable public static game images were supplied."
_VISION_FAILURE_REASON = "Visual analysis was unavailable after bounded attempts."

T = TypeVar("T", bound=StageOutput)


class SteamGameGateway(Protocol):
    def fetch_game(self, app_id: str) -> SteamGameSource: ...


class DeepSeekAnalysisGateway(Protocol):
    def complete_structured(
        self, model: str, messages: list[Message], schema: type[T]
    ) -> T: ...

    def complete_vision(
        self,
        model: str,
        prompt: str,
        image_urls: list[str],
        schema: type[T],
    ) -> T: ...


class GameAnalysisPipeline:
    def __init__(
        self,
        *,
        service: GameAnalysisService,
        steam: SteamGameGateway,
        artifacts: ArtifactStore,
        deepseek: DeepSeekAnalysisGateway,
    ) -> None:
        self._service = service
        self._steam = steam
        self._artifacts = artifacts
        self._deepseek = deepseek

    def run(self, job_id: UUID) -> UUID:
        lease = self._service.start(job_id)
        if lease.completed_profile_id is not None:
            return lease.completed_profile_id

        source = self._steam.fetch_game(lease.app_id)
        if source.app_id != lease.app_id or source.canonical_url.rstrip(
            "/"
        ) != lease.canonical_url.rstrip("/"):
            raise PermanentIntegrationError("steam_source_identity_mismatch")
        self._artifacts.put_json(
            lease.job_id,
            RAW_STEAM_ARTIFACT_NAME,
            source.raw,
        )
        self._service.advance(lease.job_id, completed_units=2)

        extraction_bundle = build_game_extraction_bundle(source)
        extraction = self._structured_with_semantic_retry(
            model=EXTRACTION_MODEL,
            messages=list(extraction_bundle.messages),
            schema=GameExtraction,
            catalog=extraction_bundle.evidence_catalog,
        )
        visual = self._visual_analysis(source)
        synthesis_bundle = build_game_synthesis_bundle(source, extraction, visual)
        synthesis = self._structured_with_semantic_retry(
            model=SYNTHESIS_MODEL,
            messages=list(synthesis_bundle.messages),
            schema=GameSynthesis,
            catalog=synthesis_bundle.evidence_catalog,
        )

        self._service.advance(lease.job_id, completed_units=4)
        return self._service.finalize(
            lease,
            GameAnalysisPublication(
                source=source,
                synthesis=synthesis,
                visual=visual,
            ),
        )

    def _structured_with_semantic_retry(
        self,
        *,
        model: str,
        messages: list[Message],
        schema: type[T],
        catalog: EvidenceCatalog,
    ) -> T:
        for attempt in range(2):
            output = self._deepseek.complete_structured(model, messages, schema)
            try:
                validate_stage_evidence(output, catalog)
            except ValueError:
                if attempt == 0:
                    continue
                raise InvalidModelOutput("deepseek_model_evidence_invalid") from None
            return output
        raise AssertionError("bounded structured attempts exhausted")

    def _visual_analysis(self, source: SteamGameSource) -> GameVisualAnalysis:
        try:
            bundle = build_game_visual_bundle(source)
        except InvalidVisualAssetInput:
            return unavailable_visual_analysis(_VISION_FAILURE_REASON)
        if not bundle.image_urls:
            return unavailable_visual_analysis(_NO_IMAGES_REASON)
        prompt = render_vision_prompt(bundle.messages)
        for _ in range(2):
            try:
                output = self._deepseek.complete_vision(
                    VISION_MODEL,
                    prompt,
                    list(bundle.image_urls),
                    GameVisualAnalysis,
                )
            except IntegrationError:
                continue
            try:
                validate_stage_evidence(output, bundle.evidence_catalog)
            except ValueError:
                continue
            return output
        return unavailable_visual_analysis(_VISION_FAILURE_REASON)


def unavailable_visual_analysis(reason: str) -> GameVisualAnalysis:
    claim = UnavailableClaim(status="unavailable", reason=reason)
    return GameVisualAnalysis(
        english_language_check=True,
        status="unavailable",
        unavailable_reason=reason,
        visual_style=claim,
        visual_motifs=claim,
        readability=claim,
        content_hook_observations=claim,
    )
