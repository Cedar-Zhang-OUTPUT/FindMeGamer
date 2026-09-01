"""Strict AI-stage contracts for creator analysis.

YouTube identity, exact public metrics, representative source records, manual
contact/notes, favorite state, schedules, and model metadata remain owned by the
Task 7 source contract and repository/pipeline layers.  These models contain
only bounded AI analysis, cautious audience inference, copied discovered public
contact values, and the compact Creator Brief.  Match Brief is intentionally
excluded because it belongs to a game-specific Match Task.
"""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, Field, field_validator, model_validator

from app.schemas.ai_game import (
    AvailableListClaim,
    AvailableTextClaim,
    Confidence,
    EvidenceList,
    EvidenceReferences,
    EvidenceText,
    LongText,
    ShortText,
    StageOutput,
    StrictAIModel,
    TextValues,
    UnavailableClaim,
    require_visual_evidence,
)


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
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("invalid public URL")
    try:
        parsed.port
    except ValueError:
        raise ValueError("invalid public URL") from None
    return value


EmailValue = Annotated[
    str,
    Field(min_length=3, max_length=320),
    AfterValidator(_validate_email_exact),
]
URLValue = Annotated[
    str,
    Field(min_length=8, max_length=2_048),
    AfterValidator(_validate_url_exact),
]
ContactValidationState = Literal["validated", "unvalidated"]


class AvailableEmailContact(StrictAIModel):
    status: Literal["available"]
    value: EmailValue
    value_type: Literal["email"]
    source_reference: ShortText
    validation_state: ContactValidationState


class AvailableURLContact(StrictAIModel):
    status: Literal["available"]
    value: URLValue
    value_type: Literal["url"]
    source_reference: ShortText
    validation_state: ContactValidationState


class UnavailableContact(StrictAIModel):
    status: Literal["unavailable"]
    reason: LongText


EmailContact = Annotated[
    AvailableEmailContact | UnavailableContact,
    Field(discriminator="status"),
]
URLContact = Annotated[
    AvailableURLContact | UnavailableContact,
    Field(discriminator="status"),
]


class AvailableSocialLinks(StrictAIModel):
    status: Literal["available"]
    values: Annotated[
        tuple[AvailableURLContact, ...],
        Field(min_length=1, max_length=20),
    ]

    @field_validator("values")
    @classmethod
    def _reject_duplicate_links(
        cls, values: tuple[AvailableURLContact, ...]
    ) -> tuple[AvailableURLContact, ...]:
        links = [item.value for item in values]
        if len(links) != len(set(links)):
            raise ValueError("social links must be unique")
        return values


SocialLinks = Annotated[
    AvailableSocialLinks | UnavailableContact,
    Field(discriminator="status"),
]


class CreatorBrief(StrictAIModel):
    """Compact, score-free input used by later matching stages."""

    positioning: EvidenceText
    content_focus: EvidenceList
    formats: EvidenceList
    style_and_pacing: EvidenceText
    audience: EvidenceText
    performance_context: EvidenceText
    promotion_fit: EvidenceText
    brand_safety: EvidenceText
    suitable_game_types: EvidenceList
    collaboration_risks: EvidenceList


class CreatorSynthesis(StageOutput):
    """All AI-owned Creator Profile fields plus copied discovered contacts."""

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
    public_email: EmailContact
    linked_site: URLContact
    social_links: SocialLinks
    creator_brief: CreatorBrief


__all__ = [
    "AudienceInference",
    "CreatorMetadataAnalysis",
    "CreatorSynthesis",
    "CreatorVisualAnalysis",
]
