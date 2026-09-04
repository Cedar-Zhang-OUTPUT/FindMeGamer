"""Bounded structured-output contracts for Creator Map-Reduce analysis.

The map stage turns at most ten public video-metadata records into compact
signals.  Four reducers then own disjoint slices of the final Creator Profile,
and a final small stage produces only ``CreatorBrief``.  The existing
``CreatorSynthesis`` remains the publication contract and is assembled without
another model call.
"""

from typing import Annotated, ClassVar, Literal

from pydantic import AfterValidator, Field, field_validator, model_validator

from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import (
    BriefReferenceText,
    Confidence,
    EvidenceReference,
    StageOutput,
    StrictAIModel,
)

MAX_CREATOR_VIDEO_BATCH_DIGEST_JSON_BYTES = 12_000
MAX_CREATOR_CONTENT_FORMAT_JSON_BYTES = 8_000
MAX_CREATOR_PRESENTATION_JSON_BYTES = 3_500
MAX_CREATOR_PERFORMANCE_AUDIENCE_JSON_BYTES = 6_000
MAX_CREATOR_COMMERCIAL_SAFETY_JSON_BYTES = 4_000
MAX_CREATOR_BRIEF_SYNTHESIS_JSON_BYTES = 7_500


def _bounded_text(value: str) -> str:
    if value != value.strip() or not value.strip():
        raise ValueError("text must be nonblank without surrounding whitespace")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError("text contains unsupported control characters")
    return value


def _unique_values(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) != len({value.casefold() for value in values}):
        raise ValueError("values must be unique")
    return values


ReducerTextValue = Annotated[
    str,
    Field(min_length=1, max_length=320),
    AfterValidator(_bounded_text),
]
ReducerListItem = Annotated[
    str,
    Field(min_length=1, max_length=64),
    AfterValidator(_bounded_text),
]
ReducerValues = Annotated[
    tuple[ReducerListItem, ...],
    Field(min_length=1, max_length=3),
    AfterValidator(_unique_values),
]
ReducerStyleItem = Annotated[
    str,
    Field(min_length=1, max_length=128),
    AfterValidator(_bounded_text),
]
ReducerStyleValues = Annotated[
    tuple[ReducerStyleItem, ...],
    Field(min_length=1, max_length=3),
    AfterValidator(_unique_values),
]
ReducerUnavailableReason = Annotated[
    str,
    Field(min_length=1, max_length=240),
    AfterValidator(_bounded_text),
]
ReducerObservation = Annotated[
    str,
    Field(min_length=1, max_length=160),
    AfterValidator(_bounded_text),
]


class ReducerEvidenceReference(EvidenceReference):
    """Evidence reference with a deliberately small observation budget."""

    reference: BriefReferenceText
    observation: ReducerObservation


ReducerEvidenceReferences = Annotated[
    tuple[ReducerEvidenceReference, ...],
    Field(min_length=1, max_length=3),
]


class ReducerUnavailableClaim(StrictAIModel):
    status: Literal["unavailable"]
    reason: ReducerUnavailableReason


class ReducerAvailableTextClaim(StrictAIModel):
    status: Literal["available"]
    value: ReducerTextValue
    evidence: ReducerEvidenceReferences
    confidence: Confidence


class ReducerAvailableListClaim(StrictAIModel):
    status: Literal["available"]
    values: ReducerValues
    evidence: ReducerEvidenceReferences
    confidence: Confidence


class ReducerAvailableStyleClaim(StrictAIModel):
    status: Literal["available"]
    values: ReducerStyleValues
    evidence: ReducerEvidenceReferences
    confidence: Confidence


ReducerEvidenceText = Annotated[
    ReducerAvailableTextClaim | ReducerUnavailableClaim,
    Field(discriminator="status"),
]
ReducerEvidenceList = Annotated[
    ReducerAvailableListClaim | ReducerUnavailableClaim,
    Field(discriminator="status"),
]
ReducerEvidenceStyle = Annotated[
    ReducerAvailableStyleClaim | ReducerUnavailableClaim,
    Field(discriminator="status"),
]


class ReducerUnavailableInference(StrictAIModel):
    status: Literal["unavailable"]
    reason: ReducerUnavailableReason
    provenance: Literal["ai_inference"]


class ReducerAvailableInferenceText(StrictAIModel):
    status: Literal["available"]
    value: ReducerTextValue
    provenance: Literal["ai_inference"]
    evidence: ReducerEvidenceReferences
    confidence: Confidence

    @model_validator(mode="after")
    def _require_inference_evidence(self) -> "ReducerAvailableInferenceText":
        if any(item.kind != "ai_inference" for item in self.evidence):
            raise ValueError("audience inference evidence must be labeled ai_inference")
        return self


class ReducerAvailableInferenceList(StrictAIModel):
    status: Literal["available"]
    values: ReducerValues
    provenance: Literal["ai_inference"]
    evidence: ReducerEvidenceReferences
    confidence: Confidence

    @model_validator(mode="after")
    def _require_inference_evidence(self) -> "ReducerAvailableInferenceList":
        if any(item.kind != "ai_inference" for item in self.evidence):
            raise ValueError("audience inference evidence must be labeled ai_inference")
        return self


ReducerInferenceText = Annotated[
    ReducerAvailableInferenceText | ReducerUnavailableInference,
    Field(discriminator="status"),
]
ReducerInferenceList = Annotated[
    ReducerAvailableInferenceList | ReducerUnavailableInference,
    Field(discriminator="status"),
]


class CreatorBatchContentFormat(StrictAIModel):
    content_focus: ReducerEvidenceList
    primary_games: ReducerEvidenceList
    genres: ReducerEvidenceList
    formats: ReducerEvidenceList
    format_tendencies: ReducerEvidenceText
    representative_video_context: ReducerEvidenceList


class CreatorBatchPresentation(StrictAIModel):
    style_and_pacing: ReducerEvidenceText
    production_signals: ReducerEvidenceText


class CreatorBatchPerformanceAudience(StrictAIModel):
    recent_performance: ReducerEvidenceText
    engagement: ReducerEvidenceText
    publishing_cadence: ReducerEvidenceText
    audience_signals: ReducerEvidenceList


class CreatorBatchCommercialSafety(StrictAIModel):
    sponsorship_signals: ReducerEvidenceList
    brand_safety_signals: ReducerEvidenceList
    collaboration_risks: ReducerEvidenceList


class CreatorVideoBatchDigest(StageOutput):
    """Compact analysis of one ordered batch of at most ten videos."""

    deepseek_max_tokens: ClassVar[int] = 6_144

    content_format: CreatorBatchContentFormat
    presentation: CreatorBatchPresentation
    performance_audience: CreatorBatchPerformanceAudience
    commercial_safety: CreatorBatchCommercialSafety

    @model_validator(mode="after")
    def _enforce_serialized_budget(self) -> "CreatorVideoBatchDigest":
        if (
            len(self.model_dump_json().encode("utf-8"))
            > MAX_CREATOR_VIDEO_BATCH_DIGEST_JSON_BYTES
        ):
            raise ValueError("CreatorVideoBatchDigest exceeds its serialization budget")
        return self


class CreatorContentFormatReduction(StageOutput):
    deepseek_max_tokens: ClassVar[int] = 4_096

    content_summary: ReducerEvidenceText
    primary_games: ReducerEvidenceList
    genres: ReducerEvidenceList
    formats: ReducerEvidenceList
    livestream_tendency: ReducerEvidenceText
    long_form_tendency: ReducerEvidenceText
    short_form_tendency: ReducerEvidenceText
    representative_video_context: ReducerEvidenceList
    suitable_game_types: ReducerEvidenceList

    @model_validator(mode="after")
    def _enforce_serialized_budget(self) -> "CreatorContentFormatReduction":
        if (
            len(self.model_dump_json().encode("utf-8"))
            > MAX_CREATOR_CONTENT_FORMAT_JSON_BYTES
        ):
            raise ValueError(
                "content-format reduction exceeds its serialization budget"
            )
        return self


class CreatorPresentationReduction(StageOutput):
    deepseek_max_tokens: ClassVar[int] = 2_048

    style: ReducerEvidenceStyle
    pacing: ReducerEvidenceText
    production_quality: ReducerEvidenceText

    @model_validator(mode="after")
    def _enforce_serialized_budget(self) -> "CreatorPresentationReduction":
        if (
            len(self.model_dump_json().encode("utf-8"))
            > MAX_CREATOR_PRESENTATION_JSON_BYTES
        ):
            raise ValueError("presentation reduction exceeds its serialization budget")
        return self


class CreatorReducerAudienceInference(StrictAIModel):
    primary_language: ReducerInferenceText
    likely_regions: ReducerInferenceList
    interests: ReducerInferenceList


class CreatorPerformanceAudienceReduction(StageOutput):
    deepseek_max_tokens: ClassVar[int] = 3_072

    recent_performance_summary: ReducerEvidenceText
    engagement_summary: ReducerEvidenceText
    publishing_frequency_context: ReducerEvidenceText
    audience_inference: CreatorReducerAudienceInference

    @model_validator(mode="after")
    def _enforce_serialized_budget(self) -> "CreatorPerformanceAudienceReduction":
        if (
            len(self.model_dump_json().encode("utf-8"))
            > MAX_CREATOR_PERFORMANCE_AUDIENCE_JSON_BYTES
        ):
            raise ValueError(
                "performance-audience reduction exceeds its serialization budget"
            )
        return self


class CreatorCommercialSafetyReduction(StageOutput):
    deepseek_max_tokens: ClassVar[int] = 2_048

    sponsorship_patterns: ReducerEvidenceList
    brand_safety: ReducerEvidenceList
    collaboration_risks: ReducerEvidenceList

    @model_validator(mode="after")
    def _enforce_serialized_budget(self) -> "CreatorCommercialSafetyReduction":
        if (
            len(self.model_dump_json().encode("utf-8"))
            > MAX_CREATOR_COMMERCIAL_SAFETY_JSON_BYTES
        ):
            raise ValueError(
                "commercial-safety reduction exceeds its serialization budget"
            )
        return self


class BriefUnavailableContact(StrictAIModel):
    status: Literal["unavailable"]
    reason: ReducerUnavailableReason


class BriefAvailableContactSelection(StrictAIModel):
    status: Literal["available"]
    candidate_id: BriefReferenceText


BriefContactSelection = Annotated[
    BriefAvailableContactSelection | BriefUnavailableContact,
    Field(discriminator="status"),
]


class BriefAvailableSocialSelections(StrictAIModel):
    status: Literal["available"]
    candidate_ids: Annotated[
        tuple[BriefReferenceText, ...], Field(min_length=1, max_length=10)
    ]

    @field_validator("candidate_ids")
    @classmethod
    def _reject_duplicate_links(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("social contact selections must be unique")
        return values


BriefSocialLinks = Annotated[
    BriefAvailableSocialSelections | BriefUnavailableContact,
    Field(discriminator="status"),
]


class CreatorBriefSynthesis(StageOutput):
    """Small final model output after the four profile reducers finish."""

    deepseek_max_tokens: ClassVar[int] = 3_072

    public_email: BriefContactSelection
    linked_site: BriefContactSelection
    social_links: BriefSocialLinks
    creator_brief: CreatorBrief

    @model_validator(mode="after")
    def _enforce_serialized_budget(self) -> "CreatorBriefSynthesis":
        if (
            len(self.model_dump_json().encode("utf-8"))
            > MAX_CREATOR_BRIEF_SYNTHESIS_JSON_BYTES
        ):
            raise ValueError("CreatorBriefSynthesis exceeds its serialization budget")
        return self


__all__ = [
    "CreatorBriefSynthesis",
    "CreatorCommercialSafetyReduction",
    "CreatorContentFormatReduction",
    "CreatorPerformanceAudienceReduction",
    "CreatorPresentationReduction",
    "CreatorVideoBatchDigest",
    "MAX_CREATOR_COMMERCIAL_SAFETY_JSON_BYTES",
    "MAX_CREATOR_BRIEF_SYNTHESIS_JSON_BYTES",
    "MAX_CREATOR_CONTENT_FORMAT_JSON_BYTES",
    "MAX_CREATOR_PERFORMANCE_AUDIENCE_JSON_BYTES",
    "MAX_CREATOR_PRESENTATION_JSON_BYTES",
    "MAX_CREATOR_VIDEO_BATCH_DIGEST_JSON_BYTES",
]
