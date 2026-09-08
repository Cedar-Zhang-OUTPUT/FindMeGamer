"""Checkpointed, bounded-parallel Creator Map-Reduce orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Literal, Protocol, TypeVar, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.analysis.contracts import ArtifactStore, CreatorSource, Message, VideoSource
from app.analysis.creator_map_reduce import merge_creator_synthesis
from app.analysis.creator_metrics import (
    compute_creator_metrics,
    select_representative_thumbnails,
)
from app.analysis.creator_pipeline import (
    VISION_MODEL,
    CreatorAnalysisPipeline,
    CreatorEmailResearchGateway,
    DeepSeekCreatorGateway,
    PublicPageGateway,
    YouTubeCreatorGateway,
    _discover_creator_contacts_with_research,
    unavailable_visual_analysis,
)
from app.analysis.prompts.common import InvalidVisualAssetInput, render_vision_prompt
from app.analysis.prompts.creator import build_creator_visual_bundle
from app.analysis.prompts.creator_map_reduce import (
    build_creator_brief_bundle,
    build_creator_commercial_safety_bundle,
    build_creator_content_format_bundle,
    build_creator_content_format_binding_repair,
    build_creator_performance_audience_bundle,
    build_creator_presentation_bundle,
    build_creator_video_batch_bundle,
    creator_video_batch_count,
)
from app.analysis.service import CreatorAnalysisPublication, CreatorAnalysisService
from app.integrations.errors import (
    IntegrationError,
    InvalidModelOutput,
    PermanentIntegrationError,
)
from app.schemas.ai_creator import (
    BoundCreatorContacts,
    CreatorContactEvidence,
    CreatorSynthesis,
    CreatorVisualAnalysis,
    bind_creator_contacts,
)
from app.schemas.ai_creator_map_reduce import (
    CreatorBriefSynthesis,
    CreatorCommercialSafetyReduction,
    CreatorContentFormatReduction,
    CreatorPerformanceAudienceReduction,
    CreatorPresentationReduction,
    CreatorVideoBatchDigest,
)
from app.schemas.ai_game import EvidenceCatalog, StageOutput, validate_stage_evidence


logger = logging.getLogger(__name__)

MAP_MODEL = "deepseek-v4-flash"
REDUCTION_MODEL = "deepseek-v4-flash"
BRIEF_MODEL = "deepseek-v4-pro"
VISUAL_MAX_TOKENS = 2_048
MAX_PARALLEL_CALLS = 5

SOURCE_NODE_KEY = "source:v1"
BATCH_NODE_PREFIX = "batch:v1:"
VISUAL_NODE_KEY = "visual:v1"
CONTACT_NODE_KEY = "contact:v2"
REDUCTION_NODE_KEYS = {
    "content_format": "reduce:v1:content-format",
    "presentation": "reduce:v1:presentation",
    "performance_audience": "reduce:v1:performance-audience",
    "commercial_safety": "reduce:v1:commercial-safety",
}
BRIEF_NODE_KEY = "brief:v2"

_NO_IMAGES_REASON = "No usable public static creator thumbnails were supplied."
_VISION_FAILURE_REASON = (
    "Thumbnail visual analysis was unavailable after bounded attempts."
)

T = TypeVar("T", bound=BaseModel)
S = TypeVar("S", bound=StageOutput)


class CreatorCheckpointStore(Protocol):
    def load(self, job_id: UUID, node_key: str, schema: type[T]) -> T | None: ...

    def save_success(self, job_id: UUID, node_key: str, output: T) -> T: ...


class MapReduceDeepSeekGateway(DeepSeekCreatorGateway, Protocol):
    def complete_structured(
        self,
        model: str,
        messages: list[Message],
        schema: type[S],
        *,
        max_tokens: int | None = None,
    ) -> S: ...

    def complete_vision(
        self,
        model: str,
        prompt: str,
        image_urls: list[str],
        schema: type[S],
        *,
        max_tokens: int | None = None,
    ) -> S: ...


class _CheckpointModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreatorVideoCheckpoint(_CheckpointModel):
    id: str
    title: str
    description: str = ""
    published_at: datetime | None = None
    channel_id: str | None = None
    tags: tuple[str, ...] = ()
    category_id: str | None = None
    duration_seconds: int | None = None
    definition: str | None = None
    caption_available: bool | None = None
    audio_language: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    thumbnail_urls: tuple[str, ...] = ()

    @classmethod
    def from_source(cls, video: VideoSource) -> "CreatorVideoCheckpoint":
        if not isinstance(video, VideoSource):
            raise TypeError("Creator video checkpoint requires a VideoSource")
        return cls(**video.model_dump(exclude={"raw"}))

    def to_source(self) -> VideoSource:
        return VideoSource(**self.model_dump(), raw={})


class CreatorSourceCheckpoint(_CheckpointModel):
    """Reconstructible normalized source without raw provider envelopes."""

    channel_id: str
    canonical_url: str
    title: str
    description: str = ""
    custom_url: str | None = None
    published_at: datetime | None = None
    country: str | None = None
    thumbnail_urls: tuple[str, ...] = ()
    banner_url: str | None = None
    subscriber_count: int | None = None
    hidden_subscriber_count: bool | None = None
    total_view_count: int | None = None
    public_video_count: int | None = None
    uploads_playlist_id: str
    videos: tuple[CreatorVideoCheckpoint, ...]

    @classmethod
    def from_source(cls, source: CreatorSource) -> "CreatorSourceCheckpoint":
        if not isinstance(source, CreatorSource):
            raise TypeError("Creator source checkpoint requires a CreatorSource")
        return cls(
            channel_id=source.channel_id,
            canonical_url=source.canonical_url,
            title=source.title,
            description=source.description,
            custom_url=source.custom_url,
            published_at=source.published_at,
            country=source.country,
            thumbnail_urls=source.thumbnail_urls,
            banner_url=source.banner_url,
            subscriber_count=source.subscriber_count,
            hidden_subscriber_count=source.hidden_subscriber_count,
            total_view_count=source.total_view_count,
            public_video_count=source.public_video_count,
            uploads_playlist_id=source.uploads_playlist_id,
            videos=tuple(
                CreatorVideoCheckpoint.from_source(video) for video in source.videos
            ),
        )

    def to_source(self) -> CreatorSource:
        return CreatorSource(
            channel_id=self.channel_id,
            canonical_url=self.canonical_url,
            title=self.title,
            description=self.description,
            custom_url=self.custom_url,
            published_at=self.published_at,
            country=self.country,
            thumbnail_urls=self.thumbnail_urls,
            banner_url=self.banner_url,
            subscriber_count=self.subscriber_count,
            hidden_subscriber_count=self.hidden_subscriber_count,
            total_view_count=self.total_view_count,
            public_video_count=self.public_video_count,
            uploads_playlist_id=self.uploads_playlist_id,
            videos=tuple(video.to_source() for video in self.videos),
            raw_channel={},
            raw_playlist_pages=(),
            raw_video_responses=(),
        )


class CreatorContactCheckpoint(_CheckpointModel):
    evidence: CreatorContactEvidence
    status: Literal["available", "partial", "unavailable"]


class CreatorMapReducePipeline(CreatorAnalysisPipeline):
    """Analyze one Creator in three waves and checkpoint validated successes."""

    def __init__(
        self,
        *,
        service: CreatorAnalysisService,
        youtube: YouTubeCreatorGateway,
        artifacts: ArtifactStore,
        public_pages: PublicPageGateway,
        deepseek: MapReduceDeepSeekGateway,
        checkpoints: CreatorCheckpointStore,
        max_parallel_calls: int = MAX_PARALLEL_CALLS,
        email_research: CreatorEmailResearchGateway | None = None,
        acquisition_guard: Callable[[], None] | None = None,
    ) -> None:
        if (
            type(max_parallel_calls) is not int
            or not 1 <= max_parallel_calls <= MAX_PARALLEL_CALLS
        ):
            raise ValueError("invalid Creator analysis parallelism")
        super().__init__(
            service=service,
            youtube=youtube,
            artifacts=artifacts,
            public_pages=public_pages,
            deepseek=deepseek,
            email_research=email_research,
        )
        self._checkpoints = checkpoints
        self._max_parallel_calls = max_parallel_calls
        self._acquisition_guard = acquisition_guard or (lambda: None)

    def run(self, job_id: UUID) -> UUID:
        lease = self._service.start(job_id)
        if lease.completed_profile_id is not None:
            return lease.completed_profile_id

        source = self._source(lease.job_id, lease.channel_id, lease.canonical_url)
        self._service.advance(lease.job_id, completed_units=2)
        representative_videos = tuple(select_representative_thumbnails(source.videos))

        digests, visual, contact = self._map_wave(
            lease.job_id,
            source,
            representative_videos,
        )
        reductions = self._reduction_wave(
            lease.job_id,
            digests,
            visual,
        )
        synthesis, contacts = self._brief_wave(
            lease.job_id,
            reductions,
            contact.evidence,
        )

        self._service.advance(lease.job_id, completed_units=4)
        return self._service.finalize(
            lease,
            CreatorAnalysisPublication(
                source=source,
                synthesis=synthesis,
                visual=visual,
                contacts=contacts,
                contact_evidence=contact.evidence,
                contact_status=contact.status,
                metrics=compute_creator_metrics(source.videos),
                representative_videos=representative_videos,
            ),
        )

    def _source(
        self,
        job_id: UUID,
        channel_id: str,
        canonical_url: str,
    ) -> CreatorSource:
        checkpoint = self._checkpoints.load(
            job_id, SOURCE_NODE_KEY, CreatorSourceCheckpoint
        )
        if checkpoint is not None:
            source = checkpoint.to_source()
            self._require_source_identity(source, channel_id, canonical_url)
            return source

        self._acquisition_guard()
        source = self._youtube.fetch_creator(channel_id, video_limit=50)
        self._require_source_identity(source, channel_id, canonical_url)
        self._store_raw_source(job_id, source)
        saved = self._checkpoints.save_success(
            job_id,
            SOURCE_NODE_KEY,
            CreatorSourceCheckpoint.from_source(source),
        )
        restored = saved.to_source()
        self._require_source_identity(restored, channel_id, canonical_url)
        return restored

    @staticmethod
    def _require_source_identity(
        source: CreatorSource,
        channel_id: str,
        canonical_url: str,
    ) -> None:
        if source.channel_id != channel_id or source.canonical_url.rstrip(
            "/"
        ) != canonical_url.rstrip("/"):
            raise PermanentIntegrationError("youtube_source_identity_mismatch")

    def _map_wave(
        self,
        job_id: UUID,
        source: CreatorSource,
        representative_videos: tuple[VideoSource, ...],
    ) -> tuple[
        tuple[CreatorVideoBatchDigest, ...],
        CreatorVisualAnalysis,
        CreatorContactCheckpoint,
    ]:
        batch_bundles = tuple(
            build_creator_video_batch_bundle(source, batch_index=index)
            for index in range(creator_video_batch_count(source))
        )
        values: dict[str, BaseModel] = {}
        calls: dict[str, Callable[[], BaseModel]] = {}
        for index, bundle in enumerate(batch_bundles):
            key = f"{BATCH_NODE_PREFIX}{index:02d}"
            existing = self._checkpoints.load(job_id, key, CreatorVideoBatchDigest)
            if existing is None:
                calls[key] = lambda bundle=bundle: self._structured_stage(
                    model=MAP_MODEL,
                    messages=list(bundle.messages),
                    schema=CreatorVideoBatchDigest,
                    catalog=bundle.evidence_catalog,
                )
            else:
                self._require_checkpoint_evidence(existing, bundle.evidence_catalog)
                values[key] = existing

        visual = self._checkpoints.load(job_id, VISUAL_NODE_KEY, CreatorVisualAnalysis)
        if visual is None:
            calls[VISUAL_NODE_KEY] = lambda: self._visual_analysis(
                source, representative_videos
            )
        else:
            values[VISUAL_NODE_KEY] = visual

        contact = self._checkpoints.load(
            job_id, CONTACT_NODE_KEY, CreatorContactCheckpoint
        )
        if contact is None:
            calls[CONTACT_NODE_KEY] = lambda: self._contact_checkpoint(source)
        else:
            values[CONTACT_NODE_KEY] = contact

        if VISUAL_NODE_KEY in calls or CONTACT_NODE_KEY in calls:
            self._acquisition_guard()
        values.update(self._run_parallel(job_id, calls))
        digests = tuple(
            cast(
                CreatorVideoBatchDigest,
                values[f"{BATCH_NODE_PREFIX}{index:02d}"],
            )
            for index in range(len(batch_bundles))
        )
        return (
            digests,
            cast(CreatorVisualAnalysis, values[VISUAL_NODE_KEY]),
            cast(CreatorContactCheckpoint, values[CONTACT_NODE_KEY]),
        )

    def _reduction_wave(
        self,
        job_id: UUID,
        digests: tuple[CreatorVideoBatchDigest, ...],
        visual: CreatorVisualAnalysis,
    ) -> dict[str, StageOutput]:
        bundles_and_schemas = {
            "content_format": (
                build_creator_content_format_bundle(digests),
                CreatorContentFormatReduction,
            ),
            "presentation": (
                build_creator_presentation_bundle(digests, visual=visual),
                CreatorPresentationReduction,
            ),
            "performance_audience": (
                build_creator_performance_audience_bundle(digests),
                CreatorPerformanceAudienceReduction,
            ),
            "commercial_safety": (
                build_creator_commercial_safety_bundle(digests),
                CreatorCommercialSafetyReduction,
            ),
        }
        values: dict[str, BaseModel] = {}
        calls: dict[str, Callable[[], BaseModel]] = {}
        for name, (bundle, schema) in bundles_and_schemas.items():
            node_key = REDUCTION_NODE_KEYS[name]
            existing = self._checkpoints.load(job_id, node_key, schema)
            if existing is None:
                calls[node_key] = (
                    lambda bundle=bundle, schema=schema: self._structured_stage(
                        model=REDUCTION_MODEL,
                        messages=list(bundle.messages),
                        schema=schema,
                        catalog=bundle.evidence_catalog,
                    )
                )
            else:
                self._require_checkpoint_evidence(existing, bundle.evidence_catalog)
                values[node_key] = existing
        values.update(self._run_parallel(job_id, calls))
        return {
            name: cast(StageOutput, values[node_key])
            for name, node_key in REDUCTION_NODE_KEYS.items()
        }

    def _brief_wave(
        self,
        job_id: UUID,
        reductions: dict[str, StageOutput],
        contact_evidence: CreatorContactEvidence,
    ) -> tuple[CreatorSynthesis, BoundCreatorContacts]:
        content = cast(CreatorContentFormatReduction, reductions["content_format"])
        presentation = cast(CreatorPresentationReduction, reductions["presentation"])
        performance = cast(
            CreatorPerformanceAudienceReduction,
            reductions["performance_audience"],
        )
        commercial = cast(
            CreatorCommercialSafetyReduction,
            reductions["commercial_safety"],
        )
        bundle = build_creator_brief_bundle(
            content_format=content,
            presentation=presentation,
            performance_audience=performance,
            commercial_safety=commercial,
            contact_evidence=contact_evidence,
        )
        brief = self._checkpoints.load(job_id, BRIEF_NODE_KEY, CreatorBriefSynthesis)
        if brief is None:
            brief = self._brief_with_binding_retry(
                messages=list(bundle.messages),
                catalog=bundle.evidence_catalog,
                contact_evidence=contact_evidence,
                reductions=(content, presentation, performance, commercial),
            )[0]
            brief = self._checkpoints.save_success(job_id, BRIEF_NODE_KEY, brief)
        self._require_checkpoint_evidence(brief, bundle.evidence_catalog)
        synthesis = merge_creator_synthesis(
            content_format=content,
            presentation=presentation,
            performance_audience=performance,
            commercial_safety=commercial,
            brief=brief,
        )
        try:
            contacts = bind_creator_contacts(synthesis, contact_evidence)
        except ValueError:
            raise PermanentIntegrationError("analysis_job_state_invalid") from None
        return synthesis, contacts

    def _brief_with_binding_retry(
        self,
        *,
        messages: list[Message],
        catalog: EvidenceCatalog,
        contact_evidence: CreatorContactEvidence,
        reductions: tuple[
            CreatorContentFormatReduction,
            CreatorPresentationReduction,
            CreatorPerformanceAudienceReduction,
            CreatorCommercialSafetyReduction,
        ],
    ) -> tuple[CreatorBriefSynthesis, BoundCreatorContacts]:
        last_failure = "evidence"
        for attempt in range(2):
            brief = self._deepseek.complete_structured(
                BRIEF_MODEL,
                messages,
                CreatorBriefSynthesis,
                max_tokens=CreatorBriefSynthesis.deepseek_max_tokens,
            )
            try:
                validate_stage_evidence(brief, catalog)
                synthesis = merge_creator_synthesis(
                    content_format=reductions[0],
                    presentation=reductions[1],
                    performance_audience=reductions[2],
                    commercial_safety=reductions[3],
                    brief=brief,
                )
                contacts = bind_creator_contacts(synthesis, contact_evidence)
            except ValueError as error:
                last_failure = (
                    "contacts" if "contact selection" in str(error) else "evidence"
                )
                if attempt == 0:
                    continue
                code = (
                    "deepseek_model_contacts_invalid"
                    if last_failure == "contacts"
                    else "deepseek_model_evidence_invalid"
                )
                raise InvalidModelOutput(code) from None
            return brief, contacts
        raise AssertionError(
            f"bounded Creator brief attempts exhausted: {last_failure}"
        )

    def _structured_stage(
        self,
        *,
        model: str,
        messages: list[Message],
        schema: type[S],
        catalog: EvidenceCatalog,
    ) -> S:
        request_messages = messages
        original_content: dict[str, object] | None = None
        for attempt in range(2):
            output = self._deepseek.complete_structured(
                model,
                request_messages,
                schema,
                max_tokens=schema.deepseek_max_tokens,
            )
            try:
                validate_stage_evidence(output, catalog)
            except ValueError:
                if schema is CreatorContentFormatReduction:
                    content = cast(CreatorContentFormatReduction, output)
                    reason = _content_format_binding_reason(content, catalog)
                    logger.warning(
                        "creator_content_format_evidence_rejected attempt=%d reason=%s",
                        attempt + 1,
                        reason,
                    )
                    if attempt == 0:
                        original_content = _content_format_without_bindings(content)
                        request_messages = build_creator_content_format_binding_repair(
                            messages, content, reason=reason
                        )
                if attempt == 0:
                    continue
                raise InvalidModelOutput("deepseek_model_evidence_invalid") from None
            if (
                original_content is not None
                and _content_format_without_bindings(
                    cast(CreatorContentFormatReduction, output)
                )
                != original_content
            ):
                logger.warning(
                    "creator_content_format_evidence_rejected "
                    "attempt=%d reason=repair_content_changed",
                    attempt + 1,
                )
                raise InvalidModelOutput("deepseek_model_evidence_invalid")
            return output
        raise AssertionError("bounded Creator stage attempts exhausted")

    @staticmethod
    def _require_checkpoint_evidence(
        output: StageOutput, catalog: EvidenceCatalog
    ) -> None:
        try:
            validate_stage_evidence(output, catalog)
        except ValueError:
            raise PermanentIntegrationError("analysis_job_state_invalid") from None

    def _visual_analysis(
        self,
        source: CreatorSource,
        representative_videos: tuple[VideoSource, ...],
    ) -> CreatorVisualAnalysis:
        selected_refs = tuple(
            f"video:{video.id}:thumbnail:0" for video in representative_videos
        )
        try:
            bundle = build_creator_visual_bundle(
                source, selected_asset_refs=selected_refs
            )
        except InvalidVisualAssetInput:
            return unavailable_visual_analysis(_VISION_FAILURE_REASON)
        if not bundle.image_urls:
            return unavailable_visual_analysis(_NO_IMAGES_REASON)
        prompt = render_vision_prompt(bundle.messages)
        for attempt in range(1, 3):
            try:
                output = self._deepseek.complete_vision(
                    VISION_MODEL,
                    prompt,
                    list(bundle.image_urls),
                    CreatorVisualAnalysis,
                    max_tokens=VISUAL_MAX_TOKENS,
                )
            except IntegrationError:
                continue
            try:
                validate_stage_evidence(output, bundle.evidence_catalog)
            except ValueError:
                logger.warning(
                    "creator_visual_evidence_rejected "
                    "attempt=%d reason=evidence_catalog_mismatch",
                    attempt,
                )
                continue
            return output
        return unavailable_visual_analysis(_VISION_FAILURE_REASON)

    def _contact_checkpoint(self, source: CreatorSource) -> CreatorContactCheckpoint:
        evidence, status = _discover_creator_contacts_with_research(
            source,
            pages=self._public_pages,
            email_research=self._email_research,
        )
        return CreatorContactCheckpoint(evidence=evidence, status=status)

    def _run_parallel(
        self,
        job_id: UUID,
        calls: dict[str, Callable[[], BaseModel]],
    ) -> dict[str, BaseModel]:
        if not calls:
            return {}
        completed: dict[str, BaseModel] = {}
        errors: list[tuple[str, Exception]] = []
        with ThreadPoolExecutor(
            max_workers=min(self._max_parallel_calls, len(calls)),
            thread_name_prefix="creator-analysis",
        ) as executor:
            futures = {
                executor.submit(call): node_key for node_key, call in calls.items()
            }
            for future in as_completed(futures):
                node_key = futures[future]
                try:
                    output = future.result()
                    completed[node_key] = self._checkpoints.save_success(
                        job_id, node_key, output
                    )
                except Exception as error:
                    errors.append((node_key, error))
        if errors:
            errors.sort(key=lambda item: item[0])
            raise errors[0][1]
        return completed


def _content_format_binding_reason(
    output: CreatorContentFormatReduction, catalog: EvidenceCatalog
) -> str:
    """Return code-owned diagnostics only: never emit model/source references."""

    allowed = {entry.reference: entry for entry in catalog.entries}
    for field_name in type(output).model_fields:
        claim = getattr(output, field_name)
        for reference in getattr(claim, "evidence", ()):
            entry = allowed.get(reference.reference)
            if entry is None:
                return "unknown_reference"
            if entry.source_type != reference.source_type:
                return "source_type_mismatch"
            if reference.kind not in entry.allowed_kinds:
                return "kind_not_allowed"
    return "evidence_catalog_mismatch"


def _content_format_without_bindings(
    output: CreatorContentFormatReduction,
) -> dict[str, object]:
    """Only citation identity may change in the bounded evidence repair."""

    payload = output.model_dump(mode="json")
    for claim in payload.values():
        if not isinstance(claim, dict):
            continue
        for reference in claim.get("evidence", []):
            for key in ("reference", "source_type", "kind"):
                reference.pop(key)
    return payload


__all__ = [
    "BATCH_NODE_PREFIX",
    "BRIEF_NODE_KEY",
    "CONTACT_NODE_KEY",
    "CreatorContactCheckpoint",
    "CreatorMapReducePipeline",
    "CreatorSourceCheckpoint",
    "REDUCTION_NODE_KEYS",
    "SOURCE_NODE_KEY",
    "VISUAL_NODE_KEY",
]
