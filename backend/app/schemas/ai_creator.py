"""Strict AI-stage contracts for creator analysis.

YouTube identity, exact public metrics, representative source records, manual
contact/notes, favorite state, schedules, and model metadata remain owned by the
Task 7 source contract and repository/pipeline layers.  These models contain
only bounded AI analysis, cautious audience inference, pipeline-bound contact
candidate selections, and the compact Creator Brief.  Match Brief is intentionally
excluded because it belongs to a game-specific Match Task.
"""

from ipaddress import ip_address
import re
from socket import inet_aton
from typing import Annotated, Literal
import unicodedata
from urllib.parse import SplitResult, unquote_to_bytes, urlsplit

from email_validator import EmailNotValidError, validate_email
import idna
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
    Field(min_length=1, max_length=64),
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


_HEX_PAIR = re.compile(r"^[0-9A-Fa-f]{2}$")
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_PATH_SAFE_ASCII = frozenset("/:@!$&'()*+,;=")
_QUERY_SAFE_ASCII = _PATH_SAFE_ASCII | {"?"}


def _has_unsafe_url_characters(value: str) -> bool:
    return any(
        character.isspace() or unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        for character in value
    )


def _validate_percent_escape_syntax(component: str) -> None:
    position = 0
    while position < len(component):
        if component[position] != "%":
            position += 1
            continue
        if position + 2 >= len(component) or not _HEX_PAIR.fullmatch(
            component[position + 1 : position + 3]
        ):
            raise ValueError("invalid public URL")
        position += 3


def _decode_url_component_until_stable(component: str) -> str:
    _validate_percent_escape_syntax(component)
    current = component.encode("utf-8")
    for _ in range(len(component) + 1):
        decoded = unquote_to_bytes(current)
        if _decoded_url_octets_are_unsafe(decoded):
            raise ValueError("invalid public URL")
        if decoded == current:
            return component
        current = decoded
    raise ValueError("invalid public URL")


def _decoded_url_octets_are_unsafe(value: bytes) -> bool:
    position = 0
    while position < len(value):
        first = value[position]
        if first < 32 or first in {92, 127}:
            return True
        sequence_length = _utf8_sequence_length(first)
        if sequence_length is not None:
            sequence = value[position : position + sequence_length]
            try:
                decoded = sequence.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                if any(
                    unicodedata.category(character) in {"Cc", "Cf", "Cs"}
                    for character in decoded
                ):
                    return True
                position += sequence_length
                continue
        if 128 <= first <= 159:
            return True
        position += 1
    return False


def _utf8_sequence_length(first: int) -> int | None:
    if 194 <= first <= 223:
        return 2
    if 224 <= first <= 239:
        return 3
    if 240 <= first <= 244:
        return 4
    return None


def _canonical_host(hostname: str) -> str:
    normalized = hostname[:-1] if hostname.endswith(".") else hostname
    if not normalized or normalized == "localhost" or normalized.endswith(".localhost"):
        raise ValueError("invalid public URL")
    try:
        ip_address(normalized)
    except ValueError:
        try:
            inet_aton(normalized)
        except OSError:
            pass
        else:
            raise ValueError("invalid public URL") from None
        try:
            ascii_hostname = (
                idna.encode(
                    normalized,
                    uts46=True,
                    std3_rules=True,
                )
                .decode("ascii")
                .casefold()
            )
        except idna.IDNAError:
            raise ValueError("invalid public URL") from None
        ascii_hostname = (
            ascii_hostname[:-1] if ascii_hostname.endswith(".") else ascii_hostname
        )
        if (
            not ascii_hostname
            or ascii_hostname == "localhost"
            or ascii_hostname.endswith(".localhost")
        ):
            raise ValueError("invalid public URL")
        try:
            ip_address(ascii_hostname)
        except ValueError:
            pass
        else:
            raise ValueError("invalid public URL") from None
        try:
            inet_aton(ascii_hostname)
        except OSError:
            return ascii_hostname
        raise ValueError("invalid public URL")
    raise ValueError("invalid public URL")


def _parse_public_url(value: str) -> tuple[SplitResult, str]:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or "#" in value
        or "%" in parsed.netloc
        or "\\" in value
        or _has_unsafe_url_characters(value)
    ):
        raise ValueError("invalid public URL")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("invalid public URL") from None
    if port == 0:
        raise ValueError("invalid public URL")
    canonical_host = _canonical_host(parsed.hostname)
    _decode_url_component_until_stable(parsed.path)
    _decode_url_component_until_stable(parsed.query)
    return parsed, canonical_host


def _validate_url_exact(value: str) -> str:
    _parse_public_url(value)
    return value


def _canonical_url_component(component: str, *, query: bool = False) -> str:
    _validate_percent_escape_syntax(component)
    safe_ascii = _QUERY_SAFE_ASCII if query else _PATH_SAFE_ASCII
    normalized: list[str] = []
    position = 0
    while position < len(component):
        character = component[position]
        if character != "%":
            if character in _UNRESERVED or character in safe_ascii:
                normalized.append(character)
            else:
                normalized.extend(
                    f"%{octet:02X}" for octet in character.encode("utf-8")
                )
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
    if not path:
        return "/"
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
    if path.endswith(("/.", "/..")) and not normalized.endswith("/"):
        normalized = f"{normalized}/"
    return normalized or "/"


def _canonical_public_url_key(value: str) -> tuple[str, str, int | None, str, str]:
    """Compare public URLs without DNS or changing exact pipeline-owned values.

    Fragments are forbidden. Hostnames are IDNA-normalized, default ports and an
    empty root path are normalized, unreserved percent escapes are decoded, and
    path dot segments are removed. Reserved escaped separators remain escaped.
    Task 10 still owns SSRF-safe DNS, fetch, and redirect enforcement.
    """

    parsed, canonical_host = _parse_public_url(value)
    port = parsed.port
    if (parsed.scheme == "https" and port == 443) or (
        parsed.scheme == "http" and port == 80
    ):
        port = None
    return (
        parsed.scheme.casefold(),
        canonical_host,
        port,
        _remove_dot_segments(_canonical_url_component(parsed.path)),
        _canonical_url_component(parsed.query, query=True),
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
