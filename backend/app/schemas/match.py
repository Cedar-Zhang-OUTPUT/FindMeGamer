"""Closed public Match result projections with hidden ranking data omitted."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.profiles import CreatorProfileCard


PublicText = Annotated[str, Field(min_length=1, max_length=2_000)]
PublicReason = Annotated[str, Field(min_length=1, max_length=512)]


class PublicMatchModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True, hide_input_in_errors=True
    )


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
    creator: CreatorProfileCard
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
    "MatchDimensionOutcomes",
    "MatchOutreachState",
    "MatchResultItem",
]
