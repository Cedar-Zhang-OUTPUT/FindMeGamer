"""Transactional orchestration for YouTube Creator Profile analysis."""

from __future__ import annotations

import re
from typing import Protocol, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
import idna

from app.analysis.contracts import ArtifactStore, CreatorSource, Message, VideoSource
from app.analysis.creator_metrics import (
    compute_creator_metrics,
    select_representative_thumbnails,
)
from app.analysis.prompts.common import InvalidVisualAssetInput, render_vision_prompt
from app.analysis.prompts.creator import (
    build_creator_metadata_bundle,
    build_creator_synthesis_bundle,
    build_creator_visual_bundle,
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
    CreatorMetadataAnalysis,
    CreatorSynthesis,
    CreatorVisualAnalysis,
    EmailContactCandidate,
    URLContactCandidate,
    bind_creator_contacts,
)
from app.schemas.ai_game import (
    EvidenceCatalog,
    StageOutput,
    UnavailableClaim,
    validate_stage_evidence,
)


METADATA_MODEL = "deepseek-v4-flash"
VISION_MODEL = "deepseek-v4-flash-vision-exp"
SYNTHESIS_MODEL = "deepseek-v4-pro"
RAW_CHANNEL_ARTIFACT_NAME = "youtube-channel.json"
RAW_PLAYLIST_ARTIFACT_NAME = "youtube-playlist-pages.json"
RAW_VIDEOS_ARTIFACT_NAME = "youtube-video-responses.json"
_NO_IMAGES_REASON = "No usable public static creator thumbnails were supplied."
_VISION_FAILURE_REASON = (
    "Thumbnail visual analysis was unavailable after bounded attempts."
)
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?){1,10}"
    r"(?![A-Za-z0-9-])"
)
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']{1,512}", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}"
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_SOCIAL_HOSTS = frozenset(
    {
        "discord.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "social.example",
        "tiktok.com",
        "twitch.tv",
        "twitter.com",
        "x.com",
        "youtube.com",
    }
)
MAX_CONTACT_TEXT_CHARACTERS = 256_000
MAX_LINKED_PAGES = 5
MAX_CONTACT_CANDIDATES = 10

T = TypeVar("T", bound=StageOutput)


class YouTubeCreatorGateway(Protocol):
    def fetch_creator(
        self, channel_id: str, video_limit: int = 50
    ) -> CreatorSource: ...


class PublicPage(Protocol):
    url: str
    text: str
    content_type: str


class PublicPageGateway(Protocol):
    def fetch_page(self, url: str) -> PublicPage: ...


class DeepSeekCreatorGateway(Protocol):
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


class CreatorAnalysisPipeline:
    def __init__(
        self,
        *,
        service: CreatorAnalysisService,
        youtube: YouTubeCreatorGateway,
        artifacts: ArtifactStore,
        public_pages: PublicPageGateway,
        deepseek: DeepSeekCreatorGateway,
    ) -> None:
        self._service = service
        self._youtube = youtube
        self._artifacts = artifacts
        self._public_pages = public_pages
        self._deepseek = deepseek

    def run(self, job_id: UUID) -> UUID:
        lease = self._service.start(job_id)
        if lease.completed_profile_id is not None:
            return lease.completed_profile_id

        source = self._youtube.fetch_creator(lease.channel_id, video_limit=50)
        if source.channel_id != lease.channel_id or source.canonical_url.rstrip(
            "/"
        ) != lease.canonical_url.rstrip("/"):
            raise PermanentIntegrationError("youtube_source_identity_mismatch")
        self._store_raw_source(lease.job_id, source)
        self._service.advance(lease.job_id, completed_units=2)

        metadata_bundle = build_creator_metadata_bundle(source)
        metadata = self._structured_with_semantic_retry(
            model=METADATA_MODEL,
            messages=list(metadata_bundle.messages),
            schema=CreatorMetadataAnalysis,
            catalog=metadata_bundle.evidence_catalog,
        )
        representative_videos = tuple(select_representative_thumbnails(source.videos))
        visual = self._visual_analysis(source, representative_videos)
        contact_evidence, contact_status = _discover_creator_contacts(
            source, pages=self._public_pages
        )
        synthesis_bundle = build_creator_synthesis_bundle(
            source, metadata, visual, contact_evidence
        )
        synthesis, contacts = self._synthesis_with_binding_retry(
            messages=list(synthesis_bundle.messages),
            catalog=synthesis_bundle.evidence_catalog,
            evidence=contact_evidence,
        )

        self._service.advance(lease.job_id, completed_units=4)
        return self._service.finalize(
            lease,
            CreatorAnalysisPublication(
                source=source,
                synthesis=synthesis,
                visual=visual,
                contacts=contacts,
                contact_evidence=contact_evidence,
                contact_status=contact_status,
                metrics=compute_creator_metrics(source.videos),
                representative_videos=representative_videos,
            ),
        )

    def _store_raw_source(self, job_id: UUID, source: CreatorSource) -> None:
        self._artifacts.put_json(job_id, RAW_CHANNEL_ARTIFACT_NAME, source.raw_channel)
        self._artifacts.put_json(
            job_id,
            RAW_PLAYLIST_ARTIFACT_NAME,
            {"pages": list(source.raw_playlist_pages)},
        )
        self._artifacts.put_json(
            job_id,
            RAW_VIDEOS_ARTIFACT_NAME,
            {"responses": list(source.raw_video_responses)},
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

    def _synthesis_with_binding_retry(
        self,
        *,
        messages: list[Message],
        catalog: EvidenceCatalog,
        evidence: CreatorContactEvidence,
    ) -> tuple[CreatorSynthesis, BoundCreatorContacts]:
        last_failure = "evidence"
        for attempt in range(2):
            output = self._deepseek.complete_structured(
                SYNTHESIS_MODEL, messages, CreatorSynthesis
            )
            try:
                validate_stage_evidence(output, catalog)
            except ValueError:
                last_failure = "evidence"
                if attempt == 0:
                    continue
                raise InvalidModelOutput("deepseek_model_evidence_invalid") from None
            try:
                contacts = bind_creator_contacts(output, evidence)
            except ValueError:
                last_failure = "contacts"
                if attempt == 0:
                    continue
                raise InvalidModelOutput("deepseek_model_contacts_invalid") from None
            return output, contacts
        raise AssertionError(f"bounded synthesis attempts exhausted: {last_failure}")

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
        for _ in range(2):
            try:
                output = self._deepseek.complete_vision(
                    VISION_MODEL,
                    prompt,
                    list(bundle.image_urls),
                    CreatorVisualAnalysis,
                )
            except IntegrationError:
                continue
            try:
                validate_stage_evidence(output, bundle.evidence_catalog)
            except ValueError:
                continue
            return output
        return unavailable_visual_analysis(_VISION_FAILURE_REASON)


def build_creator_contact_evidence(
    source: CreatorSource, *, pages: PublicPageGateway
) -> CreatorContactEvidence:
    evidence, _ = _discover_creator_contacts(source, pages=pages)
    return evidence


def _discover_creator_contacts(
    source: CreatorSource, *, pages: PublicPageGateway
) -> tuple[CreatorContactEvidence, str]:
    if not isinstance(source, CreatorSource):
        raise TypeError("contact discovery requires a CreatorSource")
    candidates: list[EmailContactCandidate | URLContactCandidate] = []
    email_keys: set[str] = set()
    url_keys: set[tuple[str, str, int | None, str, str]] = set()
    counters = {"email": 0, "site": 0, "social": 0}
    linked_pages: list[str] = []

    def add_email(value: str, *, source_type: str, source_url: str) -> None:
        if len(candidates) >= MAX_CONTACT_CANDIDATES:
            return
        try:
            normalized = validate_email(value, check_deliverability=False).normalized
        except EmailNotValidError:
            return
        key = normalized.casefold()
        if key in email_keys:
            return
        try:
            candidate = EmailContactCandidate(
                candidate_id=f"contact.email.{counters['email']}",
                kind="email",
                value=value,
                source_type=source_type,
                source_url=source_url,
                validation_state="validated",
            )
        except ValueError:
            return
        email_keys.add(key)
        counters["email"] += 1
        candidates.append(candidate)

    def add_url(value: str, *, source_type: str, source_url: str) -> None:
        if len(candidates) >= MAX_CONTACT_CANDIDATES:
            return
        kind = "social_link" if _is_social_url(value) else "linked_site"
        label = "social" if kind == "social_link" else "site"
        try:
            candidate = URLContactCandidate(
                candidate_id=f"contact.{label}.{counters[label]}",
                kind=kind,
                value=value,
                source_type=source_type,
                source_url=source_url,
                validation_state="unvalidated",
            )
        except ValueError:
            return
        key = _url_key(value)
        if key in url_keys:
            return
        url_keys.add(key)
        counters[label] += 1
        candidates.append(candidate)
        if kind == "linked_site" and source_type == "channel_description":
            linked_pages.append(value)

    channel_text = source.description[:MAX_CONTACT_TEXT_CHARACTERS]
    for kind, value in _ordered_contacts(channel_text):
        if kind == "email":
            add_email(
                value,
                source_type="channel_description",
                source_url=source.canonical_url,
            )
        else:
            add_url(
                value,
                source_type="channel_description",
                source_url=source.canonical_url,
            )

    failures = 0
    for linked_url in linked_pages[:MAX_LINKED_PAGES]:
        try:
            page = pages.fetch_page(linked_url)
        except IntegrationError:
            failures += 1
            continue
        if not isinstance(page.text, str) or not isinstance(page.url, str):
            raise TypeError("public page gateway returned an invalid page")
        page_text = page.text[:MAX_CONTACT_TEXT_CHARACTERS]
        for kind, value in _ordered_contacts(page_text):
            if kind == "email":
                add_email(
                    value,
                    source_type="linked_public_page",
                    source_url=page.url,
                )
            else:
                add_url(
                    value,
                    source_type="linked_public_page",
                    source_url=page.url,
                )
    status = (
        "partial"
        if failures and candidates
        else "unavailable" if not candidates else "available"
    )
    return CreatorContactEvidence(candidates=tuple(candidates)), status


def _ordered_contacts(text: str) -> list[tuple[str, str]]:
    matches: list[tuple[int, int, str, str]] = []
    for match in _EMAIL_PATTERN.finditer(text):
        matches.append((match.start(), 0, "email", match.group(0)))
    for match in _URL_PATTERN.finditer(text):
        value = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        matches.append((match.start(), 1, "url", value))
    matches.sort(key=lambda item: (item[0], item[1]))
    return [(kind, value) for _, _, kind, value in matches]


def _is_social_url(value: str) -> bool:
    hostname = (urlsplit(value).hostname or "").casefold().rstrip(".")
    return any(
        hostname == host or hostname.endswith(f".{host}") for host in _SOCIAL_HOSTS
    )


def _url_key(value: str) -> tuple[str, str, int | None, str, str]:
    parsed = urlsplit(value)
    port = parsed.port
    if (parsed.scheme.casefold(), port) in {("http", 80), ("https", 443)}:
        port = None
    hostname = idna.encode(
        (parsed.hostname or "").rstrip("."), uts46=True, std3_rules=True
    ).decode("ascii")
    return (
        parsed.scheme.casefold(),
        hostname.casefold(),
        port,
        _remove_dot_segments(_normalize_unreserved(parsed.path or "/")),
        _normalize_unreserved(parsed.query),
    )


def _normalize_unreserved(component: str) -> str:
    normalized: list[str] = []
    position = 0
    while position < len(component):
        if component[position] != "%":
            normalized.append(component[position])
            position += 1
            continue
        encoded = component[position + 1 : position + 3]
        character = chr(int(encoded, 16))
        normalized.append(
            character if character in _UNRESERVED else f"%{encoded.upper()}"
        )
        position += 3
    return "".join(normalized)


def _remove_dot_segments(path: str) -> str:
    output: list[str] = []
    for segment in path.split("/"):
        if segment == ".":
            continue
        if segment == "..":
            if output and output[-1] != "":
                output.pop()
            continue
        output.append(segment)
    normalized = "/".join(output)
    if path.startswith("/") and not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized or "/"


def unavailable_visual_analysis(reason: str) -> CreatorVisualAnalysis:
    claim = UnavailableClaim(status="unavailable", reason=reason)
    return CreatorVisualAnalysis(
        english_language_check=True,
        status="unavailable",
        unavailable_reason=reason,
        visual_style=claim,
        production_quality_signals=claim,
        thumbnail_patterns=claim,
        thumbnail_readability=claim,
        branding=claim,
    )


__all__ = [
    "build_creator_contact_evidence",
    "CreatorAnalysisPipeline",
    "METADATA_MODEL",
    "SYNTHESIS_MODEL",
    "VISION_MODEL",
]
