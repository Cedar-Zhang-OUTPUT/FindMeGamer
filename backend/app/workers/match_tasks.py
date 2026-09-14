"""Celery graph for screening and durable pairwise Match checkpoints."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Protocol
from uuid import UUID

from celery.exceptions import TaskPredicate
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.analysis.runtime import build_secret_provider
from app.core.config import get_settings
from app.core.database import session_scope
from app.db.models.match import (
    MatchCandidateInput,
    MatchPairwiseRecord,
    MatchScreeningRecord,
    MatchStage,
    MatchStatus,
    MatchTask,
    PairwiseState,
)
from app.integrations.deepseek import DeepSeekGateway
from app.integrations.errors import (
    InvalidModelOutput,
    TransientIntegrationError,
)
from app.matching.pairwise import (
    PairwiseCheckpointError,
    PairwiseService,
    recompute_pair_failure_task,
)
from app.matching.ranking import RankingCheckpointError, RankingService
from app.matching.screening import InvalidScreeningOutput, ScreeningService
from app.schemas.ai_match import PairwiseMatchBrief
from app.workers.analysis_tasks import RetryPolicy, get_retry_policy, random_jitter
from app.workers.celery_app import celery_app


START_MATCH_TASK_NAME = "find_me_gamer.match.start"
RUN_PAIRWISE_TASK_NAME = "find_me_gamer.match.pairwise"
ADVANCE_MATCH_TASK_NAME = "find_me_gamer.match.advance"
FINALIZE_MATCH_TASK_NAME = "find_me_gamer.match.finalize_ranking"

TEMPORARY_MATCH_FAILURE = "Match is temporarily unavailable. Please retry."
PERMANENT_MATCH_FAILURE = "Match could not be completed. Please retry."
INTERNAL_MATCH_FAILURE = "Match failed unexpectedly. Please retry."

_RETRYABLE_CODES = frozenset(
    {
        "deepseek_model_output_invalid",
        "deepseek_unavailable",
        "match_database_unavailable",
        "match_internal_error",
        "match_queue_unavailable",
    }
)
_PERMANENT_CODES = frozenset(
    {
        "deepseek_configuration_invalid",
        "deepseek_input_invalid",
        "deepseek_request_rejected",
        "deepseek_response_invalid",
        "deepseek_response_too_large",
        "locked_creator_identity_invalid",
        "locked_creator_profile_invalid",
        "locked_game_brief_invalid",
        "match_candidate_not_selected",
        "match_checkpoint_invalid",
        "match_clock_invalid",
        "match_pair_checkpoint_invalid",
        "match_pair_identity_invalid",
        "match_pair_not_found",
        "match_pair_not_runnable",
        "match_pair_not_running",
        "match_task_not_found",
        "match_task_not_preparable",
        "match_task_not_rankable",
        "match_publication_invalid",
        "match_ranking_checkpoint_invalid",
        "screening_output_invalid",
        "screening_output_unknown_creator",
    }
)


SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True, slots=True)
class PairwiseTerminalFailure:
    code: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        expected_code, expected_message, expected_retryable = _failure_shape(self.code)
        if (
            self.code != expected_code
            or self.message != expected_message
            or self.retryable is not expected_retryable
        ):
            raise ValueError("invalid safe Match failure")


class SafeMatchTaskError(RuntimeError):
    """Celery metadata containing only one allowlisted stable code."""

    def __init__(self, code: object) -> None:
        if code not in _RETRYABLE_CODES | _PERMANENT_CODES:
            code = "match_internal_error"
        self.code = str(code)
        super().__init__(self.code)


def advisory_lock_key(match_task_id: UUID) -> int:
    if type(match_task_id) is not UUID or match_task_id.int == 0:
        raise TypeError("match task id must be a nonzero UUID")
    digest = hashlib.blake2b(
        match_task_id.bytes,
        digest_size=8,
        person=b"fmgmatch",
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


class MatchDispatcher(Protocol):
    def dispatch_pairwise(self, task_id: UUID, creator_id: UUID) -> None: ...

    def dispatch_advance(self, task_id: UUID) -> None: ...

    def dispatch_ranking(self, task_id: UUID) -> None: ...


class CeleryMatchDispatcher:
    def dispatch_pairwise(self, task_id: UUID, creator_id: UUID) -> None:
        celery_app.send_task(
            RUN_PAIRWISE_TASK_NAME,
            args=[str(task_id), str(creator_id)],
        )

    def dispatch_advance(self, task_id: UUID) -> None:
        celery_app.send_task(ADVANCE_MATCH_TASK_NAME, args=[str(task_id)])

    def dispatch_ranking(self, task_id: UUID) -> None:
        celery_app.send_task(FINALIZE_MATCH_TASK_NAME, args=[str(task_id)])


class MatchTaskStore:
    """Short transactional state transitions for the Match worker graph."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        clock: Callable[[], datetime] | None = None,
        before_readiness_check: Callable[[], object] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._before_readiness_check = before_readiness_check or (lambda: None)

    @staticmethod
    def advisory_key(match_task_id: UUID) -> int:
        return advisory_lock_key(match_task_id)

    def prepare(self, task_id: UUID, creators: list[UUID]) -> list[UUID]:
        _require_uuid(task_id)
        if (
            not isinstance(creators, list)
            or any(type(value) is not UUID or value.int == 0 for value in creators)
            or len(creators) != len(set(creators))
            or not creators
        ):
            raise PairwiseCheckpointError("match_checkpoint_invalid")
        with self._session_factory() as session, session.begin():
            task = session.scalar(
                select(MatchTask).where(MatchTask.id == task_id).with_for_update()
            )
            if task is None:
                raise PairwiseCheckpointError("match_task_not_found")
            if task.status == MatchStatus.SUCCEEDED:
                return []
            ranking_redelivery = (
                task.status == MatchStatus.RUNNING
                and task.stage == MatchStage.RANKING
                and task.ranking_enqueued_at is not None
            )
            if not ranking_redelivery and (
                task.status != MatchStatus.RUNNING or task.stage != MatchStage.PAIRWISE
            ):
                raise PairwiseCheckpointError("match_task_not_preparable")
            selected_rows = session.scalars(
                select(MatchScreeningRecord)
                .where(
                    MatchScreeningRecord.match_task_id == task_id,
                    MatchScreeningRecord.selected.is_(True),
                )
                .order_by(MatchScreeningRecord.screening_order)
                .with_for_update()
            ).all()
            selected = [row.creator_id for row in selected_rows]
            candidate_ids = set(
                session.scalars(
                    select(MatchCandidateInput.creator_id)
                    .where(MatchCandidateInput.match_task_id == task_id)
                    .with_for_update()
                )
            )
            if selected != creators or candidate_ids != set(selected):
                raise PairwiseCheckpointError("match_checkpoint_invalid")
            records = {
                row.creator_id: row
                for row in session.scalars(
                    select(MatchPairwiseRecord)
                    .where(MatchPairwiseRecord.match_task_id == task_id)
                    .with_for_update()
                )
            }
            if not set(records) <= set(selected):
                raise PairwiseCheckpointError("match_checkpoint_invalid")
            if ranking_redelivery:
                if set(records) != set(selected) or any(
                    not _valid_succeeded_record(record) for record in records.values()
                ):
                    raise PairwiseCheckpointError("match_checkpoint_invalid")
                return []
            now = _aware_utc(self._clock)
            for creator_id in selected:
                if creator_id in records:
                    continue
                record = MatchPairwiseRecord(
                    match_task_id=task_id,
                    creator_id=creator_id,
                    state=PairwiseState.QUEUED,
                    attempt_count=0,
                    retryable=False,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
                records[creator_id] = record
            session.flush()
            return [
                creator_id
                for creator_id in selected
                if records[creator_id].state != PairwiseState.SUCCEEDED
            ]

    def fail_pair(
        self,
        task_id: UUID,
        creator_id: UUID,
        failure: PairwiseTerminalFailure,
    ) -> bool:
        _require_uuid(task_id)
        _require_uuid(creator_id)
        if not isinstance(failure, PairwiseTerminalFailure):
            raise TypeError("failure must be safe Match failure")
        with self._session_factory() as session, session.begin():
            task = session.scalar(
                select(MatchTask).where(MatchTask.id == task_id).with_for_update()
            )
            record = session.scalar(
                select(MatchPairwiseRecord)
                .where(
                    MatchPairwiseRecord.match_task_id == task_id,
                    MatchPairwiseRecord.creator_id == creator_id,
                )
                .with_for_update()
            )
            if task is None or record is None:
                return False
            if record.state == PairwiseState.SUCCEEDED:
                return False
            now = _aware_utc(self._clock)
            record.state = PairwiseState.FAILED
            record.attempt_count = max(record.attempt_count, 1)
            record.started_at = record.started_at or now
            record.completed_at = now
            record.match_brief = None
            record.error_code = failure.code
            record.error_message = failure.message
            record.retryable = failure.retryable
            record.updated_at = now
            if task.status not in (MatchStatus.SUCCEEDED, MatchStatus.SUPERSEDED):
                session.flush()
                recompute_pair_failure_task(session, task)
                task.updated_at = now
            session.flush()
            return True

    def fail_task(self, task_id: UUID, failure: PairwiseTerminalFailure) -> bool:
        _require_uuid(task_id)
        with self._session_factory() as session, session.begin():
            task = session.scalar(
                select(MatchTask).where(MatchTask.id == task_id).with_for_update()
            )
            if task is None or task.status in (
                MatchStatus.SUCCEEDED,
                MatchStatus.SUPERSEDED,
                MatchStatus.FAILED,
            ):
                return False
            now = _aware_utc(self._clock)
            task.status = MatchStatus.FAILED
            task.error_code = failure.code
            task.error_message = failure.message
            task.retryable = failure.retryable
            task.completed_at = now
            task.updated_at = now
            task.result_count = 0
            session.flush()
            return True

    def mark_ranking_enqueued(self, task_id: UUID) -> bool:
        _require_uuid(task_id)
        self._before_readiness_check()
        with self._session_factory() as session, session.begin():
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": advisory_lock_key(task_id)},
            )
            task = session.scalar(
                select(MatchTask).where(MatchTask.id == task_id).with_for_update()
            )
            if (
                task is None
                or task.status != MatchStatus.RUNNING
                or task.stage != MatchStage.PAIRWISE
                or task.ranking_enqueued_at is not None
            ):
                return False
            selected_ids = set(
                session.scalars(
                    select(MatchScreeningRecord.creator_id).where(
                        MatchScreeningRecord.match_task_id == task_id,
                        MatchScreeningRecord.selected.is_(True),
                    )
                )
            )
            candidate_ids = set(
                session.scalars(
                    select(MatchCandidateInput.creator_id).where(
                        MatchCandidateInput.match_task_id == task_id
                    )
                )
            )
            records = session.scalars(
                select(MatchPairwiseRecord).where(
                    MatchPairwiseRecord.match_task_id == task_id
                )
            ).all()
            if (
                not selected_ids
                or candidate_ids != selected_ids
                or {row.creator_id for row in records} != selected_ids
                or task.total_units != len(selected_ids) + 2
            ):
                return False
            for record in records:
                if record.state != PairwiseState.SUCCEEDED:
                    return False
                try:
                    brief = PairwiseMatchBrief.model_validate_json(
                        json.dumps(
                            record.match_brief,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                    )
                except Exception:
                    return False
                if brief.creator_id != record.creator_id:
                    return False
            now = _aware_utc(self._clock)
            task.stage = MatchStage.RANKING
            task.completed_units = len(selected_ids) + 1
            task.ranking_enqueued_at = now
            task.updated_at = now
            session.flush()
            return True

    def compensate_ranking_enqueue(self, task_id: UUID) -> bool:
        _require_uuid(task_id)
        with self._session_factory() as session, session.begin():
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": advisory_lock_key(task_id)},
            )
            task = session.scalar(
                select(MatchTask).where(MatchTask.id == task_id).with_for_update()
            )
            if (
                task is None
                or task.status != MatchStatus.RUNNING
                or task.stage != MatchStage.RANKING
                or task.ranking_enqueued_at is None
            ):
                return False
            succeeded = session.scalar(
                select(func.count())
                .select_from(MatchPairwiseRecord)
                .where(
                    MatchPairwiseRecord.match_task_id == task_id,
                    MatchPairwiseRecord.state == PairwiseState.SUCCEEDED,
                )
            )
            task.stage = MatchStage.PAIRWISE
            task.completed_units = min(1 + int(succeeded or 0), task.total_units)
            task.ranking_enqueued_at = None
            task.updated_at = _aware_utc(self._clock)
            session.flush()
            return True


class MatchTaskExecutor:
    def __init__(
        self,
        *,
        screening,
        pairwise_factory: Callable[[], AbstractContextManager[PairwiseService]],
        store: MatchTaskStore,
        dispatcher: MatchDispatcher,
        ranking_factory: (
            Callable[[], AbstractContextManager[RankingService]] | None
        ) = None,
    ) -> None:
        self.screening = screening
        self._pairwise_factory = pairwise_factory
        self.store = store
        self.dispatcher = dispatcher
        self._ranking_factory = ranking_factory

    def start(self, task_id: UUID) -> None:
        selected = self.screening.run(task_id)
        if not selected:
            return
        for creator_id in self.store.prepare(task_id, selected):
            self.dispatcher.dispatch_pairwise(task_id, creator_id)

    def run_pair(self, task_id: UUID, creator_id: UUID) -> PairwiseMatchBrief | None:
        with self._pairwise_factory() as service:
            try:
                result = service.run(task_id, creator_id)
            except PairwiseCheckpointError as error:
                if error.code == "match_pair_terminal":
                    return None
                raise
        self.dispatcher.dispatch_advance(task_id)
        return result

    def advance(self, task_id: UUID) -> bool:
        if not self.store.mark_ranking_enqueued(task_id):
            return False
        try:
            self.dispatcher.dispatch_ranking(task_id)
        except Exception:
            self.store.compensate_ranking_enqueue(task_id)
            raise TransientIntegrationError("match_queue_unavailable") from None
        return True

    def finalize(self, task_id: UUID) -> int:
        if self._ranking_factory is None:
            raise RankingCheckpointError("match_ranking_checkpoint_invalid")
        with self._ranking_factory() as service:
            return service.run(task_id)


class _ProductionScreening:
    def run(self, task_id: UUID) -> list[UUID]:
        # Only the advisory lock lives in this transaction. All checkpoints use
        # separate short transactions; duplicate Celery deliveries do not pay for
        # the same in-flight batches. Worker loss releases the lock automatically.
        with session_scope() as guard, guard.begin():
            acquired = guard.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": advisory_lock_key(task_id)},
            )
            if not acquired:
                return []
            with _production_gateway() as ai:
                return ScreeningService(session_factory=session_scope, ai=ai).run(
                    task_id
                )


@contextmanager
def _production_pairwise_service():
    with _production_gateway() as ai:
        yield PairwiseService(session_factory=session_scope, ai=ai)


@contextmanager
def _production_ranking_service():
    with _production_gateway() as ai:
        yield RankingService(session_factory=session_scope, ai=ai)


@contextmanager
def _production_gateway():
    settings = get_settings()
    loaded: dict[str, str] = {}
    try:
        provider = build_secret_provider(settings=settings)
        loaded = provider.load(("deepseek",))
        with DeepSeekGateway(
            api_key=loaded["deepseek"],
            base_url=settings.deepseek_api_base_url,
        ) as gateway:
            yield gateway
    finally:
        loaded.clear()


def get_match_executor() -> MatchTaskExecutor:
    return MatchTaskExecutor(
        screening=_ProductionScreening(),
        pairwise_factory=_production_pairwise_service,
        store=MatchTaskStore(session_factory=session_scope),
        dispatcher=CeleryMatchDispatcher(),
        ranking_factory=_production_ranking_service,
    )


def _failure_shape(code: object) -> tuple[str, str, bool]:
    if code in _RETRYABLE_CODES:
        message = (
            INTERNAL_MATCH_FAILURE
            if code == "match_internal_error"
            else TEMPORARY_MATCH_FAILURE
        )
        return str(code), message, True
    if code in _PERMANENT_CODES:
        return str(code), PERMANENT_MATCH_FAILURE, False
    return (
        "match_internal_error",
        INTERNAL_MATCH_FAILURE,
        True,
    )


def _make_failure(code: object) -> PairwiseTerminalFailure:
    return PairwiseTerminalFailure(*_failure_shape(code))


def _retry(task, code: str, policy: RetryPolicy):
    countdown = policy.countdown(
        task.request.retries,
        jitter=random_jitter(policy.base_delay_seconds),
    )
    raise task.retry(
        exc=SafeMatchTaskError(code),
        countdown=countdown,
        max_retries=policy.max_retries,
    )


def _handle_failure(
    task,
    *,
    task_id: UUID,
    creator_id: UUID | None,
    error: Exception,
    executor: MatchTaskExecutor,
) -> None:
    policy = get_retry_policy()
    code = (
        "deepseek_model_output_invalid"
        if isinstance(error, (InvalidModelOutput, InvalidScreeningOutput))
        else getattr(error, "code", "match_internal_error")
    )
    failure = _make_failure(code)
    if failure.retryable and task.request.retries < policy.max_retries:
        _retry(task, failure.code, policy)
    try:
        if creator_id is None:
            executor.store.fail_task(task_id, failure)
        else:
            executor.store.fail_pair(task_id, creator_id, failure)
    except SQLAlchemyError:
        if task.request.retries < policy.max_retries:
            _retry(task, "match_database_unavailable", policy)
        raise SafeMatchTaskError("match_database_unavailable") from None


@celery_app.task(
    bind=True,
    name=START_MATCH_TASK_NAME,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def start_match_task(task, match_task_id: str) -> None:
    parsed = _parse_uuid(match_task_id)
    if parsed is None:
        return
    executor = get_match_executor()
    try:
        executor.start(parsed)
    except TaskPredicate:
        raise
    except Exception as error:
        _handle_failure(
            task,
            task_id=parsed,
            creator_id=None,
            error=error,
            executor=executor,
        )


@celery_app.task(
    bind=True,
    name=RUN_PAIRWISE_TASK_NAME,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_pairwise_match(task, match_task_id: str, creator_id: str) -> None:
    parsed_task = _parse_uuid(match_task_id)
    parsed_creator = _parse_uuid(creator_id)
    if parsed_task is None or parsed_creator is None:
        return
    executor = get_match_executor()
    try:
        executor.run_pair(parsed_task, parsed_creator)
    except TaskPredicate:
        raise
    except Exception as error:
        _handle_failure(
            task,
            task_id=parsed_task,
            creator_id=parsed_creator,
            error=error,
            executor=executor,
        )


@celery_app.task(
    bind=True,
    name=ADVANCE_MATCH_TASK_NAME,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def advance_match_task(task, match_task_id: str) -> None:
    parsed = _parse_uuid(match_task_id)
    if parsed is None:
        return
    executor = get_match_executor()
    try:
        executor.advance(parsed)
    except TaskPredicate:
        raise
    except Exception as error:
        _handle_failure(
            task,
            task_id=parsed,
            creator_id=None,
            error=error,
            executor=executor,
        )


@celery_app.task(
    bind=True,
    name=FINALIZE_MATCH_TASK_NAME,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def finalize_match_ranking(task, match_task_id: str) -> None:
    parsed = _parse_uuid(match_task_id)
    if parsed is None:
        return
    executor = get_match_executor()
    try:
        executor.finalize(parsed)
    except TaskPredicate:
        raise
    except Exception as error:
        _handle_failure(
            task,
            task_id=parsed,
            creator_id=None,
            error=error,
            executor=executor,
        )


def _parse_uuid(value: object) -> UUID | None:
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    if parsed.int == 0 or str(parsed) != value:
        return None
    return parsed


def _valid_succeeded_record(record: MatchPairwiseRecord) -> bool:
    if record.state != PairwiseState.SUCCEEDED:
        return False
    try:
        brief = PairwiseMatchBrief.model_validate_json(
            json.dumps(
                record.match_brief,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except Exception:
        return False
    return brief.creator_id == record.creator_id


def _require_uuid(value: object) -> UUID:
    if type(value) is not UUID or value.int == 0:
        raise TypeError("identity must be a nonzero UUID")
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
    "ADVANCE_MATCH_TASK_NAME",
    "FINALIZE_MATCH_TASK_NAME",
    "MatchTaskExecutor",
    "MatchTaskStore",
    "PairwiseTerminalFailure",
    "RUN_PAIRWISE_TASK_NAME",
    "START_MATCH_TASK_NAME",
    "advisory_lock_key",
    "advance_match_task",
    "finalize_match_ranking",
    "run_pairwise_match",
    "start_match_task",
]
