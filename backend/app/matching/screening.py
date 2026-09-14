"""Snapshot-only candidate screening orchestration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID
import hashlib
import json
import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.analysis.contracts import Message
from app.matching.prompts import (
    build_empty_screening_recheck,
    build_screening_prompt,
    build_screening_reduction_prompt,
)
from app.integrations.errors import PermanentIntegrationError
from app.repositories.match import MatchRepository
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import ScreeningOutput, ScreeningSelection


SCREENING_MODEL = "deepseek-flash"
SCREENING_BATCH_SIZE = 100
SCREENING_BATCH_BYTES = 400_000
_logger = logging.getLogger(__name__)


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

    def save_screening_checkpoint(
        self, match_task_id: UUID, key: str, selections: tuple[ScreeningSelection, ...]
    ) -> tuple[ScreeningSelection, ...]: ...


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
    checkpoints: dict[str, tuple[ScreeningSelection, ...]] = field(default_factory=dict)

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

        def leaf_prompt(group):
            return build_screening_prompt(
                locked.game_brief,
                [(creator.creator_id, creator.brief) for creator in group],
                game_manual_context=locked.game_manual_context,
                creator_manual_contexts={c.creator_id: c.manual_context for c in group},
            )

        selections = []
        for group, messages in _bounded_groups(locked.creators, leaf_prompt):
            allowed = {c.creator_id for c in group}
            found = self._call(locked, messages, allowed, 30)
            if not found:
                found = self._call(
                    locked, build_empty_screening_recheck(messages), allowed, 30
                )
            selections.extend(found)

        # Every leaf is considered before reductions. Each multi-item reduction
        # strictly shrinks its group, so large summaries cannot prevent progress.
        while len(selections) > 30:

            def reduction_prompt(group):
                return build_screening_reduction_prompt(
                    locked.game_brief,
                    group,
                    selection_limit=min(30, max(1, len(group) // 2)),
                    game_manual_context=locked.game_manual_context,
                )

            reduced = []
            for group, messages in _bounded_groups(selections, reduction_prompt):
                if len(group) == 1:
                    reduced.extend(group)
                    continue
                reduced.extend(
                    self._call(
                        locked,
                        messages,
                        {s.creator_id for s in group},
                        min(30, len(group) // 2),
                    )
                )
            if len(reduced) >= len(selections):
                raise PermanentIntegrationError("deepseek_input_invalid")
            selections = reduced

        with self._session_factory() as session, session.begin():
            repository = self._repository_factory(session)
            return repository.apply_screening_output(match_task_id, selections)

    def _call(self, locked, messages, allowed, limit):
        # Leave room for the bounded recheck instruction within the request cap.
        if _message_bytes(messages) > SCREENING_BATCH_BYTES:
            raise PermanentIntegrationError("deepseek_input_invalid")
        key = hashlib.sha256(
            json.dumps(
                {
                    "version": "screening-batches-v1",
                    "model": SCREENING_MODEL,
                    "limit": limit,
                    "messages": [(m.role, m.content) for m in messages],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if key in locked.checkpoints:
            raw = ScreeningOutput(
                english_language_check=True, selected=locked.checkpoints[key]
            )
        else:
            _logger.info(
                "match_screening_call task=%s key=%s candidates=%s bytes=%s",
                locked.task_id,
                key[:12],
                len(allowed),
                _message_bytes(messages),
            )
            raw = self._ai.complete_structured(
                SCREENING_MODEL, messages, ScreeningOutput
            )
        selections = self._validate_for_task(raw, locked=locked)
        if len(selections) > limit or not {s.creator_id for s in selections} <= allowed:
            raise InvalidScreeningOutput(
                "screening returned IDs outside this batch or its limit"
            )
        if key not in locked.checkpoints:
            with self._session_factory() as session, session.begin():
                selections = self._repository_factory(
                    session
                ).save_screening_checkpoint(locked.task_id, key, selections)
            locked.checkpoints[key] = tuple(selections)
            _logger.info(
                "match_screening_checkpoint task=%s key=%s selected=%s",
                locked.task_id,
                key[:12],
                len(selections),
            )
        return tuple(selections)

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


def _message_bytes(messages):
    return sum(len(message.content.encode("utf-8")) for message in messages)


def _bounded_groups(items, build):
    """Split on both count and complete request bytes without clipping any record."""

    def fit(group):
        try:
            messages = build(group)
            if _message_bytes(messages) <= SCREENING_BATCH_BYTES - 2_000:
                yield group, messages
                return
        except ValueError:
            pass
        if len(group) == 1:
            raise PermanentIntegrationError("deepseek_input_invalid")
        middle = len(group) // 2
        yield from fit(group[:middle])
        yield from fit(group[middle:])

    for start in range(0, len(items), SCREENING_BATCH_SIZE):
        yield from fit(items[start : start + SCREENING_BATCH_SIZE])


__all__ = [
    "InvalidScreeningOutput",
    "LockedScreeningCreator",
    "LockedScreeningInput",
    "SCREENING_MODEL",
    "ScreeningService",
]
