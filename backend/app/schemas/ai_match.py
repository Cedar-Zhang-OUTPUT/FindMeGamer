"""Strict structured-output contracts for progressive Creator matching."""

from collections.abc import Iterable
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    Strict,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from app.schemas.ai_game import StageOutput, StrictAIModel


def _bounded_text(value: str) -> str:
    if value != value.strip() or not value.strip():
        raise ValueError("text must be nonblank without surrounding whitespace")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError("text contains unsupported control characters")
    return value


def _unique_texts(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) != len({value.casefold() for value in values}):
        raise ValueError("values must be unique")
    return values


CreatorID = Annotated[UUID, Strict()]
AnalysisText = Annotated[
    str,
    Field(min_length=1, max_length=2_000),
    AfterValidator(_bounded_text),
]
ReasonText = Annotated[
    str,
    Field(min_length=1, max_length=512),
    AfterValidator(_bounded_text),
]
EvidenceItems = Annotated[
    tuple[ReasonText, ...],
    Field(min_length=1, max_length=8),
    AfterValidator(_unique_texts),
]
ReasonItems = Annotated[
    tuple[ReasonText, ...],
    Field(min_length=1, max_length=8),
    AfterValidator(_unique_texts),
]
HiddenScore = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
BackendOrder = Annotated[StrictInt, Field(ge=0)]
ResultGroup = Literal["recommended", "other"]
QualitativeLabel = Literal["Strong Match", "Good Match", "Limited Match"]


class _StrictMatchModel(StrictAIModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        allow_inf_nan=False,
    )


class _MatchStageOutput(StageOutput):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        allow_inf_nan=False,
    )


class ScreeningSelection(_StrictMatchModel):
    """One evidence-backed screening decision; tuple order is not a rank."""

    creator_id: CreatorID
    screening_reason: ReasonText
    evidence: EvidenceItems


class ScreeningOutput(_MatchStageOutput):
    """Flash output containing zero through thirty unique candidates."""

    selected: Annotated[tuple[ScreeningSelection, ...], Field(max_length=30)]

    @field_validator("selected")
    @classmethod
    def _require_unique_creator_ids(
        cls, selected: tuple[ScreeningSelection, ...]
    ) -> tuple[ScreeningSelection, ...]:
        creator_ids = [item.creator_id for item in selected]
        if len(creator_ids) != len(set(creator_ids)):
            raise ValueError("screening creator IDs must be unique")
        return selected


class MatchDimensionAnalysis(_StrictMatchModel):
    analysis: AnalysisText
    evidence: EvidenceItems


class PairwiseMatchBrief(_MatchStageOutput):
    """One qualitative, evidence-backed Game/Creator comparison."""

    creator_id: CreatorID
    content_fit: MatchDimensionAnalysis
    audience_fit: MatchDimensionAnalysis
    performance_fit: MatchDimensionAnalysis
    promotion_fit: MatchDimensionAnalysis
    brand_safety: MatchDimensionAnalysis
    strengths: ReasonItems
    risks: ReasonItems
    evidence: EvidenceItems
    match_reasons: ReasonItems


class MatchDimensionScores(_StrictMatchModel):
    content_fit: HiddenScore
    audience_fit: HiddenScore
    performance_fit: HiddenScore
    promotion_fit: HiddenScore
    brand_safety: HiddenScore


class MatchDimensionOutcomes(_StrictMatchModel):
    content_fit: ReasonText
    audience_fit: ReasonText
    performance_fit: ReasonText
    promotion_fit: ReasonText
    brand_safety: ReasonText


class RankingItem(_StrictMatchModel):
    """Internal ranking row; numeric fields are never a public API contract."""

    creator_id: CreatorID
    total_score: HiddenScore
    dimension_scores: MatchDimensionScores
    backend_order: BackendOrder
    result_group: ResultGroup
    qualitative_label: QualitativeLabel
    dimension_outcomes: MatchDimensionOutcomes
    match_reasons: ReasonItems


class FinalRankingOutput(_MatchStageOutput):
    """Complete internal ranking output for all successful pairwise briefs."""

    items: Annotated[tuple[RankingItem, ...], Field(max_length=30)]

    @model_validator(mode="after")
    def _require_unique_identities_and_orders(self) -> Self:
        creator_ids = [item.creator_id for item in self.items]
        if len(creator_ids) != len(set(creator_ids)):
            raise ValueError("ranking creator IDs must be unique")
        backend_orders = [item.backend_order for item in self.items]
        if len(backend_orders) != len(set(backend_orders)):
            raise ValueError("ranking backend orders must be unique")
        return self

    def validate_expected_creator_ids(
        self,
        expected_creator_ids: Iterable[UUID],
    ) -> Self:
        """Require an exact one-to-one result for the selected Creator IDs."""

        if isinstance(expected_creator_ids, str | bytes | bytearray):
            raise TypeError("expected creator IDs must be UUID values")
        expected = tuple(expected_creator_ids)
        if any(type(creator_id) is not UUID for creator_id in expected):
            raise TypeError("expected creator IDs must be UUID values")
        if len(expected) != len(set(expected)):
            raise ValueError("expected creator IDs must be unique")
        actual = {item.creator_id for item in self.items}
        if actual != set(expected):
            raise ValueError("ranking must exactly match expected creator IDs")
        return self


__all__ = [
    "FinalRankingOutput",
    "PairwiseMatchBrief",
    "RankingItem",
    "ScreeningOutput",
]
