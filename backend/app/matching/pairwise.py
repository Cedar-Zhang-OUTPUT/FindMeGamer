"""Durable, snapshot-only pairwise Match comparisons."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.contracts import Message
from app.db.models.match import (
    MatchCandidateInput,
    MatchPairwiseRecord,
    MatchScreeningRecord,
    MatchStage,
    MatchStatus,
    MatchTask,
    PairwiseState,
)
from app.integrations.errors import InvalidModelOutput, PermanentIntegrationError
from app.matching.prompts import build_pairwise_prompt
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import PairwiseMatchBrief


PAIRWISE_MODEL = "deepseek-v4-pro"


class PairwiseCheckpointError(PermanentIntegrationError):
    """Persisted Match state cannot safely support this pairwise operation."""

    def __init__(self, code: str = "match_checkpoint_invalid") -> None:
        super().__init__(code)


class InvalidPairwiseOutput(InvalidModelOutput):
    """The model result is not one valid brief for the requested Creator."""

    def __init__(self) -> None:
        super().__init__("deepseek_model_output_invalid")


class StructuredPairwiseAI(Protocol):
    def complete_structured(
        self,
        model: str,
        messages: list[Message],
        schema: type[PairwiseMatchBrief],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class LockedPairwiseInput:
    match_task_id: UUID
    creator_id: UUID
    game_brief: GameBrief | None
    creator_profile: Mapping[str, object] | None
    completed_brief: PairwiseMatchBrief | None

    def __post_init__(self) -> None:
        if type(self.match_task_id) is not UUID or type(self.creator_id) is not UUID:
            raise TypeError("pairwise identities must be UUID values")
        completed = self.completed_brief is not None
        if completed:
            if (
                not isinstance(self.completed_brief, PairwiseMatchBrief)
                or self.completed_brief.creator_id != self.creator_id
                or self.game_brief is not None
                or self.creator_profile is not None
            ):
                raise ValueError("completed pairwise input is invalid")
        elif not isinstance(self.game_brief, GameBrief) or not isinstance(
            self.creator_profile, Mapping
        ):
            raise ValueError("claimed pairwise input is invalid")


class PairwiseRepository(Protocol):
    def claim(self, match_task_id: UUID, creator_id: UUID) -> LockedPairwiseInput: ...

    def apply_success(
        self,
        match_task_id: UUID,
        creator_id: UUID,
        brief: PairwiseMatchBrief,
    ) -> PairwiseMatchBrief: ...


def recompute_pair_failure_task(session: Session, task: MatchTask) -> bool:
    failed_records = session.scalars(
        select(MatchPairwiseRecord)
        .where(
            MatchPairwiseRecord.match_task_id == task.id,
            MatchPairwiseRecord.state == PairwiseState.FAILED,
        )
        .order_by(
            MatchPairwiseRecord.retryable,
            MatchPairwiseRecord.creator_id,
        )
    ).all()
    if not failed_records:
        return False
    aggregate_failure = failed_records[0]
    task.status = MatchStatus.FAILED
    task.error_code = aggregate_failure.error_code
    task.error_message = aggregate_failure.error_message
    task.retryable = all(row.retryable for row in failed_records)
    task.completed_at = max(
        row.completed_at for row in failed_records if row.completed_at is not None
    )
    task.result_count = 0
    return True


class SQLPairwiseRepository:
    """Own row-locked claim/apply work inside caller-owned short transactions."""

    def __init__(
        self,
        session: Session,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._clock = clock or (lambda: datetime.now(UTC))

    def claim(self, match_task_id: UUID, creator_id: UUID) -> LockedPairwiseInput:
        _require_uuid(match_task_id, "match task")
        _require_uuid(creator_id, "creator")
        task = self._session.scalar(
            select(MatchTask).where(MatchTask.id == match_task_id).with_for_update()
        )
        record = self._session.scalar(
            select(MatchPairwiseRecord)
            .where(
                MatchPairwiseRecord.match_task_id == match_task_id,
                MatchPairwiseRecord.creator_id == creator_id,
            )
            .with_for_update()
        )
        if task is None or record is None:
            raise PairwiseCheckpointError("match_pair_not_found")
        if record.state == PairwiseState.SUCCEEDED:
            return LockedPairwiseInput(
                match_task_id=task.id,
                creator_id=creator_id,
                game_brief=None,
                creator_profile=None,
                completed_brief=_validated_brief(
                    record.match_brief, expected_creator_id=creator_id
                ),
            )
        if task.status == MatchStatus.FAILED and record.state == PairwiseState.FAILED:
            raise PairwiseCheckpointError("match_pair_terminal")
        if (
            task.status != MatchStatus.RUNNING
            or task.stage != MatchStage.PAIRWISE
            or record.state
            not in (
                PairwiseState.QUEUED,
                PairwiseState.RUNNING,
                PairwiseState.FAILED,
            )
            or (record.state == PairwiseState.FAILED and not record.retryable)
        ):
            raise PairwiseCheckpointError("match_pair_not_runnable")

        screening = self._session.scalar(
            select(MatchScreeningRecord)
            .where(
                MatchScreeningRecord.match_task_id == match_task_id,
                MatchScreeningRecord.creator_id == creator_id,
            )
            .with_for_update()
        )
        candidate = self._session.scalar(
            select(MatchCandidateInput)
            .where(
                MatchCandidateInput.match_task_id == match_task_id,
                MatchCandidateInput.creator_id == creator_id,
            )
            .with_for_update()
        )
        if screening is None or not screening.selected or candidate is None:
            raise PairwiseCheckpointError("match_candidate_not_selected")
        game_brief = _validated_game_brief(task.locked_game_brief)
        creator_profile = _validated_creator_profile(
            candidate.locked_creator_profile,
            expected_creator_id=creator_id,
        )
        try:
            build_pairwise_prompt(game_brief, creator_profile)
        except (TypeError, ValueError):
            raise PairwiseCheckpointError("locked_creator_profile_invalid") from None

        now = _aware_utc(self._clock)
        record.state = PairwiseState.RUNNING
        record.attempt_count += 1
        record.started_at = record.started_at or now
        record.completed_at = None
        record.match_brief = None
        record.error_code = None
        record.error_message = None
        record.retryable = False
        record.updated_at = now
        self._session.flush()
        return LockedPairwiseInput(
            match_task_id=task.id,
            creator_id=creator_id,
            game_brief=game_brief,
            creator_profile=creator_profile,
            completed_brief=None,
        )

    def apply_success(
        self,
        match_task_id: UUID,
        creator_id: UUID,
        brief: PairwiseMatchBrief,
    ) -> PairwiseMatchBrief:
        _require_uuid(match_task_id, "match task")
        _require_uuid(creator_id, "creator")
        validated = _validated_brief(brief, expected_creator_id=creator_id)
        task = self._session.scalar(
            select(MatchTask).where(MatchTask.id == match_task_id).with_for_update()
        )
        record = self._session.scalar(
            select(MatchPairwiseRecord)
            .where(
                MatchPairwiseRecord.match_task_id == match_task_id,
                MatchPairwiseRecord.creator_id == creator_id,
            )
            .with_for_update()
        )
        if task is None:
            raise PairwiseCheckpointError("match_task_not_found")
        if record is None:
            raise PairwiseCheckpointError("match_pair_not_found")
        if record.state == PairwiseState.SUCCEEDED:
            return _validated_brief(record.match_brief, expected_creator_id=creator_id)
        if (
            record.state not in (PairwiseState.RUNNING, PairwiseState.FAILED)
            or task.status not in (MatchStatus.RUNNING, MatchStatus.FAILED)
            or task.stage != MatchStage.PAIRWISE
        ):
            raise PairwiseCheckpointError("match_pair_not_running")
        failed_task_matches_record = (
            task.status == MatchStatus.FAILED
            and record.state == PairwiseState.FAILED
            and task.error_code == record.error_code
            and task.error_message == record.error_message
            and task.retryable is record.retryable
            and task.completed_at == record.completed_at
        )
        now = _aware_utc(self._clock)
        record.state = PairwiseState.SUCCEEDED
        record.match_brief = validated.model_dump(mode="json")
        record.error_code = None
        record.error_message = None
        record.retryable = False
        record.completed_at = now
        record.updated_at = now

        self._session.flush()
        has_failed_sibling = recompute_pair_failure_task(self._session, task)
        if failed_task_matches_record and not has_failed_sibling:
            task.status = MatchStatus.RUNNING
            task.stage = MatchStage.PAIRWISE
            task.error_code = None
            task.error_message = None
            task.retryable = False
            task.completed_at = None
        succeeded_count = self._session.scalar(
            select(func.count())
            .select_from(MatchPairwiseRecord)
            .where(
                MatchPairwiseRecord.match_task_id == match_task_id,
                MatchPairwiseRecord.state == PairwiseState.SUCCEEDED,
            )
        )
        task.completed_units = min(1 + int(succeeded_count or 0), task.total_units)
        task.updated_at = now
        self._session.flush()
        return validated


class PairwiseService:
    """Claim, call Pro without a transaction, then checkpoint validated output."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]],
        ai: StructuredPairwiseAI,
        clock: Callable[[], datetime] | None = None,
        repository_factory: Callable[[Session], PairwiseRepository] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._ai = ai
        self._clock = clock or (lambda: datetime.now(UTC))
        self._repository_factory = repository_factory or (
            lambda session: SQLPairwiseRepository(session, clock=self._clock)
        )

    def run(self, match_task_id: UUID, creator_id: UUID) -> PairwiseMatchBrief:
        _require_uuid(match_task_id, "match task")
        _require_uuid(creator_id, "creator")
        with self._session_factory() as session, session.begin():
            claimed = self._repository_factory(session).claim(match_task_id, creator_id)
        if claimed.completed_brief is not None:
            return claimed.completed_brief
        assert claimed.game_brief is not None
        assert claimed.creator_profile is not None
        messages = build_pairwise_prompt(
            claimed.game_brief,
            claimed.creator_profile,
        )
        raw_output = self._ai.complete_structured(
            PAIRWISE_MODEL,
            messages,
            PairwiseMatchBrief,
        )
        validated = _provider_brief(raw_output, expected_creator_id=creator_id)
        with self._session_factory() as session, session.begin():
            return self._repository_factory(session).apply_success(
                match_task_id,
                creator_id,
                validated,
            )


def _provider_brief(value: object, *, expected_creator_id: UUID) -> PairwiseMatchBrief:
    if not isinstance(value, PairwiseMatchBrief):
        raise InvalidPairwiseOutput()
    try:
        validated = PairwiseMatchBrief.model_validate(value.model_dump())
    except (ValidationError, TypeError, ValueError):
        raise InvalidPairwiseOutput() from None
    if validated.creator_id != expected_creator_id:
        raise InvalidPairwiseOutput()
    return validated


def _validated_brief(value: object, *, expected_creator_id: UUID) -> PairwiseMatchBrief:
    try:
        if isinstance(value, PairwiseMatchBrief):
            validated = PairwiseMatchBrief.model_validate(value.model_dump())
        else:
            validated = PairwiseMatchBrief.model_validate_json(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
    except (ValidationError, TypeError, ValueError):
        raise PairwiseCheckpointError("match_pair_checkpoint_invalid") from None
    if validated.creator_id != expected_creator_id:
        raise PairwiseCheckpointError("match_pair_identity_invalid")
    return validated


def _validated_game_brief(value: object) -> GameBrief:
    try:
        return GameBrief.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        raise PairwiseCheckpointError("locked_game_brief_invalid") from None


def _validated_creator_profile(
    value: object,
    *,
    expected_creator_id: UUID,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PairwiseCheckpointError("locked_creator_profile_invalid")
    raw_creator_id = value.get("id")
    try:
        creator_id = UUID(raw_creator_id) if isinstance(raw_creator_id, str) else None
    except ValueError:
        creator_id = None
    if creator_id != expected_creator_id or raw_creator_id != str(expected_creator_id):
        raise PairwiseCheckpointError("locked_creator_identity_invalid")
    try:
        if not isinstance(value.get("current_facts"), Mapping) or not isinstance(
            value.get("analysis"), Mapping
        ):
            raise TypeError
        CreatorBrief.model_validate(value.get("brief"))
    except (ValidationError, TypeError, ValueError):
        raise PairwiseCheckpointError("locked_creator_profile_invalid") from None
    return deepcopy(value)


def _require_uuid(value: object, label: str) -> UUID:
    if type(value) is not UUID or value.int == 0:
        raise TypeError(f"{label} id must be a nonzero UUID")
    return value


def _aware_utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise PairwiseCheckpointError("match_clock_invalid")
    return value.astimezone(UTC)


__all__ = [
    "InvalidPairwiseOutput",
    "LockedPairwiseInput",
    "PAIRWISE_MODEL",
    "PairwiseCheckpointError",
    "PairwiseService",
    "recompute_pair_failure_task",
]
