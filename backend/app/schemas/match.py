"""Closed public Match result projections with hidden ranking data omitted."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


PublicText = Annotated[str, Field(min_length=1, max_length=2_000)]
PublicReason = Annotated[str, Field(min_length=1, max_length=512)]


class PublicMatchModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True, hide_input_in_errors=True
    )


class MatchCreatorContact(PublicMatchModel):
    email: EmailStr
    source: str
    source_url: str | None
    validation_state: str


class MatchCreatorCard(PublicMatchModel):
    id: UUID
    name: str
    youtube_channel_id: str
    canonical_url: str
    avatar_url: str | None = None
    favorite: bool
    subscriber_count: Annotated[int, Field(ge=0)] | None = None
    recent_average_views: Annotated[int, Field(ge=0)] | None = None
    recent_median_views: Annotated[int, Field(ge=0)] | None = None
    performance_summary: (
        Annotated[str, Field(min_length=1, max_length=2_000)] | None
    ) = None
    contact_available: bool
    contact: MatchCreatorContact | None


class MatchBriefDimension(PublicMatchModel):
    analysis: PublicText
    evidence: Annotated[tuple[PublicReason, ...], Field(min_length=1, max_length=8)]


class MatchBrief(PublicMatchModel):
    content_fit: MatchBriefDimension
    audience_fit: MatchBriefDimension
    performance_fit: MatchBriefDimension
    promotion_fit: MatchBriefDimension
    brand_safety: MatchBriefDimension
    strengths: Annotated[tuple[PublicReason, ...], Field(min_length=1, max_length=8)]
    risks: Annotated[tuple[PublicReason, ...], Field(min_length=1, max_length=8)]
    evidence: Annotated[tuple[PublicReason, ...], Field(min_length=1, max_length=8)]
    match_reasons: Annotated[
        tuple[PublicReason, ...], Field(min_length=1, max_length=8)
    ]


class MatchDimensionOutcomes(PublicMatchModel):
    content_fit: PublicReason
    audience_fit: PublicReason
    performance_fit: PublicReason
    promotion_fit: PublicReason
    brand_safety: PublicReason


class MatchOutreachState(PublicMatchModel):
    send_state: Literal["not_sent", "queued", "sending", "sent", "failed"] = "not_sent"
    response_state: Literal["no_response", "accepted", "declined"] = "no_response"
    delivery_id: UUID | None = None


class MatchResultItem(PublicMatchModel):
    creator: MatchCreatorCard
    result_group: Literal["recommended", "other"]
    qualitative_label: Literal["Strong Match", "Good Match", "Limited Match"]
    dimension_outcomes: MatchDimensionOutcomes
    match_reasons: Annotated[
        tuple[PublicReason, ...], Field(min_length=1, max_length=8)
    ]
    match_brief: MatchBrief
    outreach: MatchOutreachState


__all__ = [
    "MatchBrief",
    "MatchCreatorCard",
    "MatchCreatorContact",
    "MatchDimensionOutcomes",
    "MatchOutreachState",
    "MatchResultItem",
]
