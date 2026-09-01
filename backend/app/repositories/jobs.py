from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.targets import CanonicalTarget
from app.db.models.enums import JobMode, JobStatus, TargetType
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile, GameProfile


@dataclass(frozen=True)
class JobCreationResult:
    job: AnalysisJob | None = None
    existing_profile_id: UUID | None = None
    created: bool = False


class JobsRepository:
    def __init__(self, database_session: Session) -> None:
        self._session = database_session

    def get_idempotency_record(self, key: str) -> IdempotencyRecord | None:
        return self._session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        )

    def add_idempotency_record(
        self,
        *,
        key: str,
        request_hash: str,
        method: str,
        path: str,
        response_status: int,
        response_body: dict,
    ) -> None:
        self._session.add(
            IdempotencyRecord(
                key=key,
                request_hash=request_hash,
                method=method,
                path=path,
                response_status=response_status,
                response_body=response_body,
            )
        )

    def active_job(self, target: CanonicalTarget) -> AnalysisJob | None:
        return self._session.scalar(
            select(AnalysisJob).where(
                AnalysisJob.target_type == target.target_type,
                AnalysisJob.canonical_target_id == target.canonical_id,
                AnalysisJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
            )
        )

    def get_job(self, job_id: UUID) -> AnalysisJob | None:
        return self._session.get(AnalysisJob, job_id)

    def create_or_reuse_job(
        self,
        target: CanonicalTarget,
        *,
        mode: JobMode,
        correlation_id: str | None,
    ) -> JobCreationResult:
        active = self.active_job(target)
        if active is not None:
            return JobCreationResult(job=active)
        if mode is JobMode.CREATE:
            if target.target_type is TargetType.GAME:
                profile_id = self._session.scalar(
                    select(GameProfile.id).where(
                        GameProfile.steam_app_id == target.canonical_id
                    )
                )
            else:
                profile_id = self._session.scalar(
                    select(CreatorProfile.id).where(
                        CreatorProfile.youtube_channel_id == target.canonical_id
                    )
                )
            if profile_id is not None:
                return JobCreationResult(existing_profile_id=profile_id)
        job = AnalysisJob(
            target_type=target.target_type,
            canonical_target_id=target.canonical_id,
            canonical_url=target.canonical_url,
            mode=mode,
            status=JobStatus.QUEUED,
            correlation_id=correlation_id,
        )
        self._session.add(job)
        self._session.flush()
        return JobCreationResult(job=job, created=True)

    def retry_or_reuse_job(
        self,
        source: AnalysisJob,
        *,
        correlation_id: str | None,
    ) -> JobCreationResult:
        target = CanonicalTarget(
            target_type=source.target_type,
            canonical_id=source.canonical_target_id,
            canonical_url=source.canonical_url,
        )
        active = self.active_job(target)
        if active is not None:
            return JobCreationResult(job=active)
        job = AnalysisJob(
            target_type=source.target_type,
            canonical_target_id=source.canonical_target_id,
            canonical_url=source.canonical_url,
            mode=source.mode,
            status=JobStatus.QUEUED,
            correlation_id=correlation_id,
        )
        self._session.add(job)
        self._session.flush()
        return JobCreationResult(job=job, created=True)
