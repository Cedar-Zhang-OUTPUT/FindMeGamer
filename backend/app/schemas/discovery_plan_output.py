"""Strict structured-output contract for game-driven discovery planning."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator
from app.schemas.discovery import Platform


def _bounded_narrative(value: str) -> str:
    if value != value.strip() or not value:
        raise ValueError("text must be nonblank without surrounding whitespace")
    if any(ord(character) < 32 for character in value):
        raise ValueError("text contains control characters")
    return value


def _safe_keyword_phrase(value: str) -> str:
    value = _bounded_narrative(value)
    if not any(character.isalnum() for character in value):
        raise ValueError("keyword phrase must contain a letter or digit")
    if any(
        not (character.isalnum() or character in {" ", "'", "-"}) for character in value
    ):
        raise ValueError("keyword phrase contains unsafe query syntax")
    return value


Narrative = Annotated[
    str,
    Field(min_length=1, max_length=1_500),
    AfterValidator(_bounded_narrative),
]
KeywordPhrase = Annotated[
    str,
    Field(min_length=1, max_length=100),
    AfterValidator(_safe_keyword_phrase),
]


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchPlanQuery(_StrictOutput):
    platform: Platform
    terms: list[KeywordPhrase] = Field(min_length=1, max_length=3)

    @field_validator("terms")
    @classmethod
    def reject_duplicate_terms(cls, terms: list[str]) -> list[str]:
        if len({term.casefold() for term in terms}) != len(terms):
            raise ValueError("query terms must be unique")
        return terms


class SearchPlanOutput(_StrictOutput):
    summary: Narrative
    rationale: Narrative
    queries: list[SearchPlanQuery] = Field(min_length=1, max_length=4)
