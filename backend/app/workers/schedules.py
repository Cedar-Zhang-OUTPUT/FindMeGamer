"""Mandatory, database-coordinated scheduled Profile re-analysis."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.targets import CanonicalTarget
from app.core.database import session_scope
from app.db.models.enums import JobMode
from app.db.models.jobs import acquire_job_change_lock
from app.repositories.jobs import JobsRepository
from app.repositories.profiles import ProfilesRepository
from app.workers.celery_app import celery_app


SCHEDULE_TASK_NAME = "find_me_gamer.reanalysis.enqueue_due"
SCHEDULER_LOCK_ID = 7_188_291_260_937_040_069
DEFAULT_BATCH_SIZE = 20
MAX_BATCH_SIZE = 100


class JobDispatcher(Protocol):
    def dispatch(self, job_id: UUID) -> None: ...


SessionFactory = Callable[[], AbstractContextManager[Session]]


def _validated_batch_size(batch_size: object) -> int:
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError("scheduled re-analysis batch size must be from 1 to 100")
    return batch_size


def _aware_utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("scheduled re-analysis clock must return aware UTC time")
    return value.astimezone(UTC)


class ScheduledReanalysisService:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dispatcher: JobDispatcher,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._clock = clock or (lambda: datetime.now(UTC))

    def run(self, *, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
        batch_size = _validated_batch_size(batch_size)
        now = _aware_utc(self._clock)
        created_job_ids: list[UUID] = []
        with self._session_factory() as session:
            try:
                session.execute(select(func.pg_advisory_xact_lock(SCHEDULER_LOCK_ID)))
                acquire_job_change_lock(session)
                profiles = ProfilesRepository(session)
                profiles.mark_stale_creators(now)
                due_profiles = profiles.list_due_profiles(
                    now=now,
                    limit=batch_size,
                )
                jobs = JobsRepository(session)
                for profile in due_profiles:
                    target = CanonicalTarget(
                        target_type=profile.target_type,
                        canonical_id=profile.canonical_target_id,
                        canonical_url=profile.canonical_url,
                    )
                    result = jobs.create_or_reuse_job(
                        target,
                        mode=JobMode.REANALYZE,
                        correlation_id=str(uuid4()),
                    )
                    if result.created and result.job is not None:
                        created_job_ids.append(result.job.id)
                session.commit()
            except Exception:
                session.rollback()
                raise

        accepted = 0
        for job_id in created_job_ids:
            try:
                self._dispatcher.dispatch(job_id)
            except Exception:
                from app.core.analysis_job_contract import QUEUE_FAILURE_MESSAGE
                from app.workers.analysis_tasks import (
                    TerminalFailure,
                    write_queued_publication_failure,
                )

                write_queued_publication_failure(
                    job_id,
                    TerminalFailure(
                        code="analysis_queue_unavailable",
                        message=QUEUE_FAILURE_MESSAGE,
                        retryable=True,
                    ),
                    session_factory=self._session_factory,
                    clock=lambda: now,
                )
                continue
            accepted += 1
        return accepted


def mark_stale_creators(
    now: datetime, *, session_factory: SessionFactory = session_scope
) -> int:
    normalized_now = _aware_utc(lambda: now)
    with session_factory() as session:
        try:
            acquire_job_change_lock(session)
            changed = ProfilesRepository(session).mark_stale_creators(normalized_now)
            session.commit()
            return changed
        except Exception:
            session.rollback()
            raise


def get_scheduled_reanalysis_service() -> ScheduledReanalysisService:
    from app.api.routes.jobs import CeleryJobDispatcher

    return ScheduledReanalysisService(
        session_factory=session_scope,
        dispatcher=CeleryJobDispatcher(),
    )


@celery_app.task(
    name=SCHEDULE_TASK_NAME,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def enqueue_due_reanalysis(batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    validated_batch_size = _validated_batch_size(batch_size)
    return get_scheduled_reanalysis_service().run(batch_size=validated_batch_size)


__all__ = [
    "enqueue_due_reanalysis",
    "get_scheduled_reanalysis_service",
    "mark_stale_creators",
    "ScheduledReanalysisService",
    "SCHEDULE_TASK_NAME",
]
