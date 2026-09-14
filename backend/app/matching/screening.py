"""Snapshot-only candidate screening orchestration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.analysis.contracts import Message
from app.matching.prompts import build_empty_screening_recheck, build_screening_prompt
from app.repositories.match import MatchRepository
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import ScreeningOutput, ScreeningSelection


SCREENING_MODEL = "deepseek-v4-flash"


class InvalidScreeningOutput(ValueError):
    """The provider output cannot be applied to this locked Match task."""


class StructuredMatchAI(Protocol):
    def complete_structured(
        self,
        model: str,
        messages: list[Message],
        schema: type[ScreeningOutput],
    ) -> object: ...


class ScreeningRepository(Protocol):
    def load_locked_screening_input(
        self,
        match_task_id: UUID,
    ) -> LockedScreeningInput: ...

    def apply_screening_output(
        self,
        match_task_id: UUID,
        selections: tuple[ScreeningSelection, ...],
    ) -> list[UUID]: ...


@dataclass(frozen=True, slots=True)
class LockedScreeningCreator:
    creator_id: UUID
    brief: CreatorBrief
    manual_context: dict | None = None

    def __post_init__(self) -> None:
        if type(self.creator_id) is not UUID:
            raise TypeError("locked creator id must be a UUID")
        if not isinstance(self.brief, CreatorBrief):
            raise TypeError("locked creator brief must be validated")


@dataclass(frozen=True, slots=True)
class LockedScreeningInput:
    task_id: UUID
    game_brief: GameBrief
    creators: tuple[LockedScreeningCreator, ...]
    applied_creator_ids: tuple[UUID, ...] | None
    game_manual_context: dict | None = None

    def __post_init__(self) -> None:
        if type(self.task_id) is not UUID:
            raise TypeError("locked task id must be a UUID")
        if not isinstance(self.game_brief, GameBrief):
            raise TypeError("locked game brief must be validated")
        creator_ids = [creator.creator_id for creator in self.creators]
        if len(creator_ids) != len(set(creator_ids)):
            raise ValueError("locked screening creator IDs must be unique")
        if self.applied_creator_ids is not None and (
            any(type(value) is not UUID for value in self.applied_creator_ids)
            or len(self.applied_creator_ids) != len(set(self.applied_creator_ids))
        ):
            raise ValueError("applied screening creator IDs must be unique UUIDs")


class ScreeningService:
    """Call Flash outside transactions and atomically apply validated output."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]],
        ai: StructuredMatchAI,
        clock: Callable[[], datetime] | None = None,
        repository_factory: Callable[[Session], ScreeningRepository] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._ai = ai
        self._clock = clock or (lambda: datetime.now(UTC))
        self._repository_factory = repository_factory or (
            lambda session: MatchRepository(session, clock=self._clock)
        )

    def run(self, match_task_id: UUID) -> list[UUID]:
        if type(match_task_id) is not UUID:
            raise TypeError("match task id must be a UUID")

        with self._session_factory() as session, session.begin():
            repository = self._repository_factory(session)
            locked = repository.load_locked_screening_input(match_task_id)
        if locked.applied_creator_ids is not None:
            return list(locked.applied_creator_ids)

        if not locked.creators:
            with self._session_factory() as session, session.begin():
                repository = self._repository_factory(session)
                return repository.apply_screening_output(match_task_id, ())

        messages = build_screening_prompt(
            locked.game_brief,
            [(creator.creator_id, creator.brief) for creator in locked.creators],
            game_manual_context=locked.game_manual_context,
            creator_manual_contexts={
                creator.creator_id: creator.manual_context
                for creator in locked.creators
            },
        )
        raw_output = self._ai.complete_structured(
            SCREENING_MODEL,
            messages,
            ScreeningOutput,
        )
        selections = self._validate_for_task(raw_output, locked=locked)
        if not selections:
            # Recheck once before applying an empty result. Both passes use the
            # complete locked input; a second valid empty result remains valid.
            raw_output = self._ai.complete_structured(
                SCREENING_MODEL,
                build_empty_screening_recheck(messages),
                ScreeningOutput,
            )
            selections = self._validate_for_task(raw_output, locked=locked)

        with self._session_factory() as session, session.begin():
            repository = self._repository_factory(session)
            return repository.apply_screening_output(match_task_id, selections)

    @staticmethod
    def _validate_for_task(
        raw_output: object,
        *,
        locked: LockedScreeningInput,
    ) -> tuple[ScreeningSelection, ...]:
        if not isinstance(raw_output, ScreeningOutput):
            raise InvalidScreeningOutput("screening provider returned the wrong type")
        raw_selected = raw_output.selected
        if not isinstance(raw_selected, tuple | list) or len(raw_selected) > 30:
            raise InvalidScreeningOutput("screening selected more than 30 creators")
        creator_ids: list[UUID] = []
        for item in raw_selected:
            if (
                not isinstance(item, ScreeningSelection)
                or type(item.creator_id) is not UUID
            ):
                raise InvalidScreeningOutput("screening selection is malformed")
            creator_ids.append(item.creator_id)
        if len(creator_ids) != len(set(creator_ids)):
            raise InvalidScreeningOutput("screening creator IDs must be unique")
        locked_ids = {creator.creator_id for creator in locked.creators}
        if not set(creator_ids) <= locked_ids:
            raise InvalidScreeningOutput("screening returned an unknown creator ID")
        try:
            validated = ScreeningOutput.model_validate(raw_output.model_dump())
        except (ValidationError, TypeError, ValueError):
            raise InvalidScreeningOutput(
                "screening provider output is malformed"
            ) from None
        return validated.selected


__all__ = [
    "InvalidScreeningOutput",
    "LockedScreeningCreator",
    "LockedScreeningInput",
    "SCREENING_MODEL",
    "ScreeningService",
]
