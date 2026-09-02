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

from app.core.config import get_settings
from app.core.database import session_scope
from app.db.models.enums import AnalysisStage, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
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

TEMPORARY_FAILURE_MESSAGE = "Analysis is temporarily unavailable. Please retry."
PERMANENT_FAILURE_MESSAGE = "Analysis could not be completed for this target."
INTERNAL_FAILURE_MESSAGE = "Analysis failed unexpectedly. Please retry."
QUEUE_FAILURE_MESSAGE = "Analysis could not be queued. Please retry."

_INTEGRATION_CODES = frozenset(
    {
        "analysis_clock_invalid",
        "analysis_cleanup_failed",
        "analysis_configuration_invalid",
        "analysis_job_identity_changed",
        "analysis_job_not_found",
        "analysis_job_result_invalid",
        "analysis_job_stage_invalid",
        "analysis_job_state_invalid",
        "analysis_job_target_invalid",
        "artifact_job_id_invalid",
        "artifact_name_invalid",
        "artifact_payload_invalid",
        "artifact_payload_too_large",
        "creator_interval_invalid",
        "deepseek_configuration_invalid",
        "deepseek_input_invalid",
        "deepseek_model_contacts_invalid",
        "deepseek_model_evidence_invalid",
        "deepseek_model_output_invalid",
        "deepseek_request_rejected",
        "deepseek_response_invalid",
        "deepseek_response_too_large",
        "deepseek_unavailable",
        "game_interval_invalid",
        "public_page_address_rejected",
        "public_page_content_type_invalid",
        "public_page_redirect_invalid",
        "public_page_redirect_limit",
        "public_page_request_rejected",
        "public_page_response_invalid",
        "public_page_too_large",
        "public_page_unavailable",
        "public_page_url_invalid",
        "s3_configuration_invalid",
        "s3_request_rejected",
        "s3_unavailable",
        "shared_settings_missing",
        "steam_app_id_invalid",
        "steam_game_not_found",
        "steam_request_rejected",
        "steam_response_invalid",
        "steam_response_too_large",
        "steam_source_identity_mismatch",
        "steam_unavailable",
        "youtube_channel_id_invalid",
        "youtube_channel_not_found",
        "youtube_configuration_invalid",
        "youtube_quota_unavailable",
        "youtube_request_rejected",
        "youtube_response_invalid",
        "youtube_response_too_large",
        "youtube_source_identity_mismatch",
        "youtube_target_invalid",
        "youtube_unavailable",
        "youtube_video_limit_invalid",
    }
)
_SPECIAL_FAILURES = {
    "analysis_internal_error": INTERNAL_FAILURE_MESSAGE,
    "analysis_queue_unavailable": QUEUE_FAILURE_MESSAGE,
}
_ALLOWED_MESSAGES = frozenset(
    {
        TEMPORARY_FAILURE_MESSAGE,
        PERMANENT_FAILURE_MESSAGE,
        INTERNAL_FAILURE_MESSAGE,
        QUEUE_FAILURE_MESSAGE,
    }
)


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
        if (
            not isinstance(self.code, str)
            or not _safe_code.fullmatch(self.code)
            or self.code not in _INTEGRATION_CODES | _SPECIAL_FAILURES.keys()
            or self.message not in _ALLOWED_MESSAGES
            or type(self.retryable) is not bool
        ):
            raise ValueError("invalid safe terminal failure")


class SafeTaskError(RuntimeError):
    """Celery metadata containing only an allowlisted stable code."""

    def __init__(self, code: str) -> None:
        if code not in _INTEGRATION_CODES and code != "analysis_database_unavailable":
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
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job is None or job.status is JobStatus.FAILED:
                session.commit()
                return False
            if job.status is JobStatus.SUCCEEDED:
                require_valid_succeeded_job_result(session, job)
                session.commit()
                return False
            if job.status is JobStatus.RUNNING and preserve_running:
                session.commit()
                return False
            if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                raise PermanentIntegrationError("analysis_job_state_invalid")
            completed_at = _aware_utc(clock)
            job.status = JobStatus.FAILED
            job.error_code = failure.code
            job.error_message = failure.message
            job.retryable = failure.retryable
            job.completed_at = completed_at
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
        with self._pipeline_factory(target_type) as pipeline:
            pipeline.run(job_id)

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
                job = session.scalar(
                    select(AnalysisJob)
                    .where(AnalysisJob.id == job_id)
                    .with_for_update()
                )
                if job is None or job.status is JobStatus.FAILED:
                    session.commit()
                    return None
                if job.status is JobStatus.SUCCEEDED:
                    require_valid_succeeded_job_result(session, job)
                    session.commit()
                    return None
                if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                    raise PermanentIntegrationError("analysis_job_state_invalid")
                if job.target_type not in (TargetType.GAME, TargetType.CREATOR):
                    raise PermanentIntegrationError("analysis_job_target_invalid")
                now = _aware_utc(self._clock)
                if job.status is JobStatus.QUEUED:
                    job.status = JobStatus.RUNNING
                if job.stage is None:
                    job.stage = AnalysisStage.FETCHING_DATA
                job.completed_units = min(
                    max(job.completed_units, 0), TOTAL_ANALYSIS_UNITS
                )
                if job.total_units <= 0:
                    job.total_units = TOTAL_ANALYSIS_UNITS
                else:
                    job.total_units = max(job.total_units, job.completed_units)
                if job.started_at is None:
                    job.started_at = now
                target_type = job.target_type
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


def _failure_for(code: object, *, retryable: bool) -> TerminalFailure:
    if not isinstance(code, str) or code not in _INTEGRATION_CODES:
        return TerminalFailure(
            code="analysis_internal_error",
            message=INTERNAL_FAILURE_MESSAGE,
            retryable=True,
        )
    return TerminalFailure(
        code=code,
        message=TEMPORARY_FAILURE_MESSAGE if retryable else PERMANENT_FAILURE_MESSAGE,
        retryable=retryable,
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
        failure = _failure_for(error.code, retryable=True)
        if task.request.retries >= policy.max_retries:
            try:
                executor.fail(parsed_job_id, failure)
            except SQLAlchemyError:
                raise SafeTaskError("analysis_database_unavailable") from None
            return
        _retry(task, failure.code, policy)
    except PermanentIntegrationError as error:
        failure = _failure_for(error.code, retryable=False)
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
