"""Strict AI-stage contracts for creator analysis.

YouTube identity, exact public metrics, representative source records, manual
contact/notes, favorite state, schedules, and model metadata remain owned by the
Task 7 source contract and repository/pipeline layers.  These models contain
only bounded AI analysis, cautious audience inference, pipeline-bound contact
candidate selections, and the compact Creator Brief.  Match Brief is intentionally
excluded because it belongs to a game-specific Match Task.
"""

from ipaddress import ip_address
from typing import Annotated, Literal
import unicodedata
from urllib.parse import unquote, urlsplit

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, Field, field_validator, model_validator

from app.schemas.ai_game import (
    BriefEvidenceReference,
    Confidence,
    EvidenceList,
    EvidenceReferences,
    EvidenceText,
    LongText,
    MAX_CREATOR_BRIEF_JSON_BYTES,
    ReferenceText,
    StageOutput,
    StrictAIModel,
    TextValues,
    require_visual_evidence,
)


def _creator_brief_text(value: str) -> str:
    if value != value.strip() or not value.strip():
        raise ValueError("brief text must be nonblank without surrounding whitespace")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError("brief text contains unsupported control characters")
    return value


def _unique_creator_brief_values(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) != len({value.casefold() for value in values}):
        raise ValueError("brief values must be unique")
    return values


CreatorBriefText = Annotated[
    str,
    Field(min_length=1, max_length=144),
    AfterValidator(_creator_brief_text),
]
CreatorBriefItem = Annotated[
    str,
    Field(min_length=1, max_length=48),
    AfterValidator(_creator_brief_text),
]
CreatorBriefValues = Annotated[
    tuple[CreatorBriefItem, ...],
    Field(min_length=1, max_length=3),
    AfterValidator(_unique_creator_brief_values),
]
CreatorBriefEvidence = Annotated[
    tuple[BriefEvidenceReference, ...],
    Field(min_length=1, max_length=1),
]


class CreatorMetadataAnalysis(StageOutput):
    """Analysis limited to official channel and public video metadata."""

    primary_games: EvidenceList
    genres: EvidenceList
    formats: EvidenceList
    style: EvidenceList
    pacing: EvidenceText
    livestream_tendency: EvidenceText
    long_form_tendency: EvidenceText
    short_form_tendency: EvidenceText
    recent_performance_summary: EvidenceText
    engagement_summary: EvidenceText
    publishing_frequency_context: EvidenceText
    sponsorship_patterns: EvidenceList
    brand_safety_signals: EvidenceList
    collaboration_risks: EvidenceList


class CreatorVisualAnalysis(StageOutput):
    """Thumbnail-only observations; never a claim about video content/audience."""

    status: Literal["available", "unavailable"]
    unavailable_reason: LongText | None
    visual_style: EvidenceText
    production_quality_signals: EvidenceText
    thumbnail_patterns: EvidenceList
    thumbnail_readability: EvidenceText
    branding: EvidenceText

    @model_validator(mode="after")
    def _validate_visual_availability(self) -> "CreatorVisualAnalysis":
        claims = (
            self.visual_style,
            self.production_quality_signals,
            self.thumbnail_patterns,
            self.thumbnail_readability,
            self.branding,
        )
        if self.status == "unavailable":
            if self.unavailable_reason is None or any(
                claim.status != "unavailable" for claim in claims
            ):
                raise ValueError(
                    "unavailable visual analysis requires a reason and unavailable claims"
                )
            return self
        if self.unavailable_reason is not None:
            raise ValueError(
                "available visual analysis cannot carry an unavailable reason"
            )
        if not any(claim.status == "available" for claim in claims):
            raise ValueError("available visual analysis requires an available claim")
        require_visual_evidence(claims)
        return self


class UnavailableInference(StrictAIModel):
    status: Literal["unavailable"]
    reason: LongText
    provenance: Literal["ai_inference"]


class AvailableInferenceText(StrictAIModel):
    status: Literal["available"]
    value: LongText
    provenance: Literal["ai_inference"]
    evidence: EvidenceReferences
    confidence: Confidence

    @model_validator(mode="after")
    def _require_inference_evidence(self) -> "AvailableInferenceText":
        if any(item.kind != "ai_inference" for item in self.evidence):
            raise ValueError("audience inference evidence must be labeled ai_inference")
        return self


class AvailableInferenceList(StrictAIModel):
    status: Literal["available"]
    values: TextValues
    provenance: Literal["ai_inference"]
    evidence: EvidenceReferences
    confidence: Confidence

    @model_validator(mode="after")
    def _require_inference_evidence(self) -> "AvailableInferenceList":
        if any(item.kind != "ai_inference" for item in self.evidence):
            raise ValueError("audience inference evidence must be labeled ai_inference")
        return self


InferenceText = Annotated[
    AvailableInferenceText | UnavailableInference,
    Field(discriminator="status"),
]
InferenceList = Annotated[
    AvailableInferenceList | UnavailableInference,
    Field(discriminator="status"),
]


class AudienceInference(StrictAIModel):
    primary_language: InferenceText
    likely_regions: InferenceList
    interests: InferenceList


def _validate_email_exact(value: str) -> str:
    try:
        validate_email(value, check_deliverability=False)
    except EmailNotValidError:
        raise ValueError("invalid public email") from None
    return value


def _validate_url_exact(value: str) -> str:
    parsed = urlsplit(value)
    decoded = value
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    hostname = parsed.hostname.casefold() if parsed.hostname is not None else None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or "#" in value
        or hostname == "localhost"
        or hostname.endswith(".localhost")
        or any(
            character.isspace() or unicodedata.category(character) in {"Cc", "Cf"}
            for character in decoded
        )
    ):
        raise ValueError("invalid public URL")
    try:
        parsed.port
    except ValueError:
        raise ValueError("invalid public URL") from None
    try:
        address = ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("invalid public URL")
    return value


def _canonical_public_url_key(value: str) -> tuple[str, str, int | None, str, str]:
    """Return a comparison key without changing the exact pipeline-owned value.

    URL fragments are rejected by ``_validate_url_exact``. Host and scheme case and
    default HTTP(S) ports are insignificant for duplicate contact selection checks.
    This performs no DNS lookup; Task 10 still owns fetch/redirect SSRF controls.
    """

    parsed = urlsplit(value)
    port = parsed.port
    if (parsed.scheme == "https" and port == 443) or (
        parsed.scheme == "http" and port == 80
    ):
        port = None
    return (
        parsed.scheme.casefold(),
        (parsed.hostname or "").casefold(),
        port,
        parsed.path,
        parsed.query,
    )


EmailValue = Annotated[
    str,
    Field(min_length=3, max_length=320),
    AfterValidator(_validate_email_exact),
]
URLValue = Annotated[
    str,
    Field(min_length=8, max_length=512),
    AfterValidator(_validate_url_exact),
]
ContactValidationState = Literal["validated", "unvalidated"]
ContactEvidenceSource = Literal["channel_description", "linked_public_page"]


class EmailContactCandidate(StrictAIModel):
    candidate_id: ReferenceText
    kind: Literal["email"]
    value: EmailValue
    source_type: ContactEvidenceSource
    source_url: URLValue
    validation_state: ContactValidationState


class URLContactCandidate(StrictAIModel):
    candidate_id: ReferenceText
    kind: Literal["linked_site", "social_link"]
    value: URLValue
    source_type: ContactEvidenceSource
    source_url: URLValue
    validation_state: ContactValidationState


ContactCandidate = Annotated[
    EmailContactCandidate | URLContactCandidate,
    Field(discriminator="kind"),
]


class CreatorContactEvidence(StrictAIModel):
    """Pipeline-owned exact public contact discoveries supplied to synthesis."""

    candidates: Annotated[tuple[ContactCandidate, ...], Field(max_length=10)]

    @field_validator("candidates")
    @classmethod
    def _reject_duplicate_candidates(
        cls, candidates: tuple[ContactCandidate, ...]
    ) -> tuple[ContactCandidate, ...]:
        identifiers = [candidate.candidate_id for candidate in candidates]
        exact_values = [
            (candidate.kind, candidate.value, candidate.source_url)
            for candidate in candidates
        ]
        if len(identifiers) != len(set(identifiers)) or len(exact_values) != len(
            set(exact_values)
        ):
            raise ValueError("contact candidates must be unique")
        social_urls = [
            _canonical_public_url_key(candidate.value)
            for candidate in candidates
            if candidate.kind == "social_link"
        ]
        if len(social_urls) != len(set(social_urls)):
            raise ValueError("social URL candidates must resolve uniquely")
        return candidates


class AvailableContactSelection(StrictAIModel):
    status: Literal["available"]
    candidate_id: ReferenceText


class UnavailableContact(StrictAIModel):
    status: Literal["unavailable"]
    reason: LongText


ContactSelection = Annotated[
    AvailableContactSelection | UnavailableContact,
    Field(discriminator="status"),
]


class AvailableSocialSelections(StrictAIModel):
    status: Literal["available"]
    candidate_ids: Annotated[
        tuple[ReferenceText, ...], Field(min_length=1, max_length=20)
    ]

    @field_validator("candidate_ids")
    @classmethod
    def _reject_duplicate_links(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("social contact selections must be unique")
        return values


SocialLinks = Annotated[
    AvailableSocialSelections | UnavailableContact,
    Field(discriminator="status"),
]


class BoundCreatorContacts(StrictAIModel):
    public_email: EmailContactCandidate | None
    linked_site: URLContactCandidate | None
    social_links: tuple[URLContactCandidate, ...]


class CreatorBriefUnavailableClaim(StrictAIModel):
    status: Literal["unavailable"]
    reason: CreatorBriefText


class CreatorBriefAvailableTextClaim(StrictAIModel):
    status: Literal["available"]
    value: CreatorBriefText
    evidence: CreatorBriefEvidence
    confidence: Confidence


class CreatorBriefAvailableListClaim(StrictAIModel):
    status: Literal["available"]
    values: CreatorBriefValues
    evidence: CreatorBriefEvidence
    confidence: Confidence


CreatorBriefEvidenceText = Annotated[
    CreatorBriefAvailableTextClaim | CreatorBriefUnavailableClaim,
    Field(discriminator="status"),
]
CreatorBriefEvidenceList = Annotated[
    CreatorBriefAvailableListClaim | CreatorBriefUnavailableClaim,
    Field(discriminator="status"),
]


class CompactUnavailableInference(StrictAIModel):
    status: Literal["unavailable"]
    reason: CreatorBriefText
    provenance: Literal["ai_inference"]


class CompactAvailableInferenceText(StrictAIModel):
    status: Literal["available"]
    value: CreatorBriefText
    provenance: Literal["ai_inference"]
    evidence: CreatorBriefEvidence
    confidence: Confidence

    @model_validator(mode="after")
    def _require_inference_evidence(self) -> "CompactAvailableInferenceText":
        if any(item.kind != "ai_inference" for item in self.evidence):
            raise ValueError("brief audience evidence must be labeled ai_inference")
        return self


CompactInferenceText = Annotated[
    CompactAvailableInferenceText | CompactUnavailableInference,
    Field(discriminator="status"),
]


class CreatorBrief(StrictAIModel):
    """Compact, score-free input used by later matching stages."""

    positioning: CreatorBriefEvidenceText
    content_focus: CreatorBriefEvidenceList
    formats: CreatorBriefEvidenceList
    style_and_pacing: CreatorBriefEvidenceText
    audience: CompactInferenceText
    performance_context: CreatorBriefEvidenceText
    promotion_fit: CreatorBriefEvidenceText
    brand_safety: CreatorBriefEvidenceText
    suitable_game_types: CreatorBriefEvidenceList
    collaboration_risks: CreatorBriefEvidenceList

    @model_validator(mode="after")
    def _enforce_serialized_budget(self) -> "CreatorBrief":
        if len(self.model_dump_json().encode("utf-8")) > MAX_CREATOR_BRIEF_JSON_BYTES:
            raise ValueError("CreatorBrief exceeds its screening serialization budget")
        return self


class CreatorSynthesis(StageOutput):
    """AI-owned Creator fields plus pipeline-resolved contact selections."""

    content_summary: EvidenceText
    primary_games: EvidenceList
    genres: EvidenceList
    formats: EvidenceList
    style: EvidenceList
    pacing: EvidenceText
    production_quality: EvidenceText
    livestream_tendency: EvidenceText
    long_form_tendency: EvidenceText
    short_form_tendency: EvidenceText
    recent_performance_summary: EvidenceText
    engagement_summary: EvidenceText
    publishing_frequency_context: EvidenceText
    representative_video_context: EvidenceList
    sponsorship_patterns: EvidenceList
    brand_safety: EvidenceList
    suitable_game_types: EvidenceList
    collaboration_risks: EvidenceList
    audience_inference: AudienceInference
    public_email: ContactSelection
    linked_site: ContactSelection
    social_links: SocialLinks
    creator_brief: CreatorBrief


def bind_creator_contacts(
    synthesis: CreatorSynthesis,
    evidence: CreatorContactEvidence,
) -> BoundCreatorContacts:
    """Resolve model selections against exact pipeline-owned contact evidence."""

    if not isinstance(synthesis, CreatorSynthesis) or not isinstance(
        evidence, CreatorContactEvidence
    ):
        raise TypeError("contact binding requires validated synthesis and evidence")
    candidates = {
        candidate.candidate_id: candidate for candidate in evidence.candidates
    }

    def selected(
        selection: ContactSelection,
        expected_kind: str,
    ) -> ContactCandidate | None:
        if selection.status == "unavailable":
            return None
        candidate = candidates.get(selection.candidate_id)
        if candidate is None or candidate.kind != expected_kind:
            raise ValueError("contact selection is not bound to supplied evidence")
        return candidate

    public_email = selected(synthesis.public_email, "email")
    linked_site = selected(synthesis.linked_site, "linked_site")
    social_links: list[URLContactCandidate] = []
    selected_social_urls: set[tuple[str, str, int | None, str, str]] = set()
    if synthesis.social_links.status == "available":
        for candidate_id in synthesis.social_links.candidate_ids:
            candidate = candidates.get(candidate_id)
            if (
                not isinstance(candidate, URLContactCandidate)
                or candidate.kind != "social_link"
            ):
                raise ValueError("contact selection is not bound to supplied evidence")
            canonical_url = _canonical_public_url_key(candidate.value)
            if canonical_url in selected_social_urls:
                raise ValueError("selected social URLs must resolve uniquely")
            selected_social_urls.add(canonical_url)
            social_links.append(candidate)
    if public_email is not None and not isinstance(public_email, EmailContactCandidate):
        raise ValueError("contact selection is not bound to supplied evidence")
    if linked_site is not None and not isinstance(linked_site, URLContactCandidate):
        raise ValueError("contact selection is not bound to supplied evidence")
    return BoundCreatorContacts(
        public_email=public_email,
        linked_site=linked_site,
        social_links=tuple(social_links),
    )


__all__ = [
    "AudienceInference",
    "bind_creator_contacts",
    "CreatorContactEvidence",
    "CreatorMetadataAnalysis",
    "CreatorSynthesis",
    "CreatorVisualAnalysis",
]
