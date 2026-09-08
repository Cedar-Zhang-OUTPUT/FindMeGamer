"""Durable Analysis Job execution and terminal failure convergence."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
import re
import secrets
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from celery.exceptions import TaskPredicate

from app.core.analysis_job_contract import (
    INTEGRATION_ERROR_CODES,
    INTERNAL_FAILURE_MESSAGE,
    QUEUE_FAILURE_MESSAGE,
    public_job_failure,
    valid_analysis_job_state,
)
from app.core.config import get_settings
from app.core.database import session_scope
from app.db.models.enums import AnalysisStage, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob, acquire_job_change_lock
from app.integrations.errors import (
    InvalidModelOutput,
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.repositories.jobs import require_valid_succeeded_job_result
from app.workers.celery_app import celery_app


ANALYSIS_TASK_NAME = "find_me_gamer.analysis.run"
TOTAL_ANALYSIS_UNITS = 5
_safe_code = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class Pipeline(Protocol):
    def run(self, job_id: UUID) -> UUID: ...


PipelineFactory = Callable[[TargetType], AbstractContextManager[Pipeline]]
SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay_seconds: int = 2
    max_delay_seconds: int = 60

    def __post_init__(self) -> None:
        if (
            type(self.max_retries) is not int
            or not 0 <= self.max_retries <= 10
            or type(self.base_delay_seconds) is not int
            or not 1 <= self.base_delay_seconds <= 300
            or type(self.max_delay_seconds) is not int
            or not self.base_delay_seconds <= self.max_delay_seconds <= 3_600
        ):
            raise ValueError("invalid Analysis retry policy")

    def countdown(self, retries: int, *, jitter: int) -> int:
        if type(retries) is not int or retries < 0:
            raise ValueError("invalid retry count")
        if type(jitter) is not int or not 0 <= jitter <= self.base_delay_seconds:
            raise ValueError("invalid retry jitter")
        delay = min(self.base_delay_seconds * (2**retries), self.max_delay_seconds)
        return min(delay + jitter, self.max_delay_seconds)


@dataclass(frozen=True, slots=True)
class TerminalFailure:
    code: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        expected = public_job_failure(self.code)
        if (
            not isinstance(self.code, str)
            or not _safe_code.fullmatch(self.code)
            or expected is None
            or self.message != expected.message
            or type(self.retryable) is not bool
            or self.retryable is not expected.retryable
        ):
            raise ValueError("invalid safe terminal failure")


class SafeTaskError(RuntimeError):
    """Celery metadata containing only an allowlisted stable code."""

    def __init__(self, code: str) -> None:
        if (
            code not in INTEGRATION_ERROR_CODES
            and code != "analysis_database_unavailable"
        ):
            code = "analysis_internal_error"
        self.code = code
        super().__init__(code)


def random_jitter(ceiling: int) -> int:
    return secrets.randbelow(ceiling + 1)


def get_retry_policy() -> RetryPolicy:
    settings = get_settings()
    return RetryPolicy(
        max_retries=settings.analysis_task_max_retries,
        base_delay_seconds=settings.analysis_retry_base_delay_seconds,
        max_delay_seconds=settings.analysis_retry_max_delay_seconds,
    )


def _aware_utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise PermanentIntegrationError("analysis_clock_invalid")
    return value.astimezone(UTC)


def _parse_job_id(raw_job_id: object) -> UUID | None:
    if not isinstance(raw_job_id, str) or len(raw_job_id) != 36:
        return None
    try:
        value = UUID(raw_job_id)
    except ValueError:
        return None
    if value.int == 0 or str(value) != raw_job_id:
        return None
    return value


def _require_valid_job_state(job: AnalysisJob) -> None:
    if not valid_analysis_job_state(
        status=job.status,
        stage=job.stage,
        completed_units=job.completed_units,
        total_units=job.total_units,
        error_code=job.error_code,
        error_message=job.error_message,
        retryable=job.retryable,
        profile_id=job.profile_id,
        result_present=job.result_payload is not None,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    ):
        raise PermanentIntegrationError("analysis_job_state_invalid")


def write_terminal_failure(
    job_id: UUID,
    failure: TerminalFailure,
    *,
    session_factory: SessionFactory,
    clock: Callable[[], datetime],
) -> bool:
    return _write_terminal_failure(
        job_id,
        failure,
        session_factory=session_factory,
        clock=clock,
        preserve_running=False,
    )


def write_queued_publication_failure(
    job_id: UUID,
    failure: TerminalFailure,
    *,
    session_factory: SessionFactory,
    clock: Callable[[], datetime],
) -> bool:
    return _write_terminal_failure(
        job_id,
        failure,
        session_factory=session_factory,
        clock=clock,
        preserve_running=True,
    )


def _write_terminal_failure(
    job_id: UUID,
    failure: TerminalFailure,
    *,
    session_factory: SessionFactory,
    clock: Callable[[], datetime],
    preserve_running: bool,
) -> bool:
    with session_factory() as session:
        try:
            acquire_job_change_lock(session)
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job is None:
                session.commit()
                return False
            if job.status is JobStatus.FAILED:
                _require_valid_job_state(job)
                session.commit()
                return False
            if job.status is JobStatus.SUCCEEDED:
                require_valid_succeeded_job_result(session, job)
                _require_valid_job_state(job)
                session.commit()
                return False
            if job.status is JobStatus.RUNNING and preserve_running:
                _require_valid_job_state(job)
                session.commit()
                return False
            if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                raise PermanentIntegrationError("analysis_job_state_invalid")
            _require_valid_job_state(job)
            completed_at = _aware_utc(clock)
            job.error_code = failure.code
            job.error_message = failure.message
            job.retryable = failure.retryable
            job.profile_id = None
            job.result_payload = None
            job.status = JobStatus.FAILED
            job.completed_at = completed_at
            _require_valid_job_state(job)
            session.flush()
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise


class AnalysisJobExecutor:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        pipeline_factory: PipelineFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._pipeline_factory = pipeline_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(self, job_id: UUID) -> None:
        target_type = self._claim(job_id)
        if target_type is None:
            return
        from app.repositories.collection_settings import CollectionPaused

        try:
            with self._pipeline_factory(target_type) as pipeline:
                pipeline.run(job_id)
        except CollectionPaused:
            with self._session_factory() as session:
                acquire_job_change_lock(session)
                job = session.get(AnalysisJob, job_id)
                if job is not None and job.status in (
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                ):
                    job.collection_paused = True
                session.commit()

    def fail(self, job_id: UUID, failure: TerminalFailure) -> bool:
        return write_terminal_failure(
            job_id,
            failure,
            session_factory=self._session_factory,
            clock=self._clock,
        )

    def _claim(self, job_id: UUID) -> TargetType | None:
        with self._session_factory() as session:
            try:
                acquire_job_change_lock(session)
                job = session.scalar(
                    select(AnalysisJob)
                    .where(AnalysisJob.id == job_id)
                    .with_for_update()
                )
                if job is None:
                    session.commit()
                    return None
                if job.status is JobStatus.FAILED:
                    _require_valid_job_state(job)
                    session.commit()
                    return None
                if job.status is JobStatus.SUCCEEDED:
                    require_valid_succeeded_job_result(session, job)
                    _require_valid_job_state(job)
                    session.commit()
                    return None
                if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                    raise PermanentIntegrationError("analysis_job_state_invalid")
                if job.target_type not in (TargetType.GAME, TargetType.CREATOR):
                    raise PermanentIntegrationError("analysis_job_target_invalid")
                _require_valid_job_state(job)
                if job.target_type is TargetType.CREATOR:
                    from app.repositories.collection_settings import collection_enabled

                    if job.collection_paused or not collection_enabled(
                        session, "youtube"
                    ):
                        job.collection_paused = True
                        session.commit()
                        return None
                if job.status is JobStatus.QUEUED:
                    now = _aware_utc(self._clock)
                    job.status = JobStatus.RUNNING
                    job.stage = AnalysisStage.FETCHING_DATA
                    job.completed_units = 0
                    job.total_units = TOTAL_ANALYSIS_UNITS
                    job.started_at = now
                target_type = job.target_type
                _require_valid_job_state(job)
                session.flush()
                session.commit()
                return target_type
            except Exception:
                session.rollback()
                raise


def get_analysis_executor() -> AnalysisJobExecutor:
    from app.analysis.runtime import build_production_runtime

    runtime = build_production_runtime()
    return AnalysisJobExecutor(
        session_factory=session_scope,
        pipeline_factory=runtime.pipeline_for,
    )


def _failure_for(code: object) -> TerminalFailure:
    failure = public_job_failure(code)
    if failure is None:
        code = "analysis_internal_error"
        failure = public_job_failure(code)
        assert failure is not None
    return TerminalFailure(
        code=code,
        message=failure.message,
        retryable=failure.retryable,
    )


def _retry(task, code: str, policy: RetryPolicy):
    countdown = policy.countdown(
        task.request.retries,
        jitter=random_jitter(policy.base_delay_seconds),
    )
    raise task.retry(
        exc=SafeTaskError(code),
        countdown=countdown,
        max_retries=policy.max_retries,
    )


@celery_app.task(
    bind=True,
    name=ANALYSIS_TASK_NAME,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_analysis_job(task, job_id: str) -> None:
    parsed_job_id = _parse_job_id(job_id)
    if parsed_job_id is None:
        return
    policy = get_retry_policy()
    executor = get_analysis_executor()
    try:
        executor.execute(parsed_job_id)
    except (TransientIntegrationError, InvalidModelOutput) as error:
        failure = _failure_for(error.code)
        if failure.retryable and task.request.retries < policy.max_retries:
            _retry(task, failure.code, policy)
        try:
            executor.fail(parsed_job_id, failure)
        except SQLAlchemyError:
            raise SafeTaskError("analysis_database_unavailable") from None
    except PermanentIntegrationError as error:
        failure = _failure_for(error.code)
        if failure.retryable and task.request.retries < policy.max_retries:
            _retry(task, failure.code, policy)
        try:
            executor.fail(parsed_job_id, failure)
        except SQLAlchemyError:
            if task.request.retries < policy.max_retries:
                _retry(task, "analysis_database_unavailable", policy)
            raise SafeTaskError("analysis_database_unavailable") from None
    except SQLAlchemyError:
        if task.request.retries < policy.max_retries:
            _retry(task, "analysis_database_unavailable", policy)
        raise SafeTaskError("analysis_database_unavailable") from None
    except TaskPredicate:
        raise
    except Exception:
        failure = TerminalFailure(
            code="analysis_internal_error",
            message=INTERNAL_FAILURE_MESSAGE,
            retryable=True,
        )
        try:
            executor.fail(parsed_job_id, failure)
        except SQLAlchemyError:
            if task.request.retries < policy.max_retries:
                _retry(task, "analysis_database_unavailable", policy)
            raise SafeTaskError("analysis_database_unavailable") from None
