"""Strict structured outputs for bounded Discovery candidate evaluation."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _nonblank(value: str) -> str:
    if value != value.strip() or not value:
        raise ValueError("text must be nonblank without surrounding whitespace")
    if any(ord(character) < 32 for character in value):
        raise ValueError("text contains control characters")
    return value


Narrative = Annotated[
    str,
    Field(min_length=1, max_length=1_200),
    AfterValidator(_nonblank),
]
Limitation = Annotated[
    str,
    Field(min_length=1, max_length=500),
    AfterValidator(_nonblank),
]


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationScreenOutput(_StrictOutput):
    selected_ids: list[UUID] = Field(max_length=20)


class EvaluationMatchBrief(_StrictOutput):
    candidate_id: UUID
    summary: Narrative
    content_fit: Narrative
    audience_fit: Narrative
    limitations: list[Limitation] = Field(min_length=1, max_length=6)
    cited_work_ids: list[UUID] = Field(max_length=20)
    confidence: Literal["limited", "supported"]


class EvaluationRankItem(_StrictOutput):
    candidate_id: UUID
    score: int = Field(ge=0, le=100)


class EvaluationRankOutput(_StrictOutput):
    items: list[EvaluationRankItem] = Field(max_length=20)
