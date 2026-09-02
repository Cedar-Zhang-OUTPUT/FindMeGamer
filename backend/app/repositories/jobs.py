from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.analysis.targets import CanonicalTarget
from app.db.models.enums import JobMode, JobStatus, TargetType
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile, GameProfile
from app.integrations.errors import PermanentIntegrationError


def require_valid_succeeded_job_result(session: Session, job: AnalysisJob) -> None:
    if job.status is not JobStatus.SUCCEEDED:
        return
    if job.profile_id is None or not isinstance(job.result_payload, dict):
        raise PermanentIntegrationError("analysis_job_result_invalid")
    if set(job.result_payload) != {"profile_id"}:
        raise PermanentIntegrationError("analysis_job_result_invalid")
    if job.result_payload.get("profile_id") != str(job.profile_id):
        raise PermanentIntegrationError("analysis_job_result_invalid")
    if job.target_type is TargetType.GAME:
        profile = session.get(GameProfile, job.profile_id)
        valid = bool(
            profile is not None
            and profile.steam_app_id == job.canonical_target_id
            and profile.canonical_url.rstrip("/") == job.canonical_url.rstrip("/")
        )
    elif job.target_type is TargetType.CREATOR:
        profile = session.get(CreatorProfile, job.profile_id)
        valid = bool(
            profile is not None
            and profile.youtube_channel_id == job.canonical_target_id
            and profile.canonical_url.rstrip("/") == job.canonical_url.rstrip("/")
        )
    else:
        valid = False
    if not valid:
        raise PermanentIntegrationError("analysis_job_result_invalid")


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
            select(IdempotencyRecord)
            .where(IdempotencyRecord.key == key)
            .with_for_update()
        )

    def delete_idempotency_record(self, record: IdempotencyRecord) -> None:
        self._session.delete(record)
        self._session.flush()

    def add_idempotency_record(
        self,
        *,
        key: str,
        request_hash: str,
        method: str,
        path: str,
        response_status: int,
        response_body: dict,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            IdempotencyRecord(
                key=key,
                request_hash=request_hash,
                method=method,
                path=path,
                response_status=response_status,
                response_body=response_body,
                expires_at=expires_at,
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

    def get_job_for_update(self, job_id: UUID) -> AnalysisJob | None:
        return self._session.scalar(
            select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
        )

    def list_changed_jobs(
        self,
        *,
        cursor: tuple[datetime, UUID] | None,
        status: JobStatus | None,
        limit: int,
    ) -> tuple[list[AnalysisJob], bool]:
        statement = select(AnalysisJob)
        if status is not None:
            statement = statement.where(AnalysisJob.status == status)
        if cursor is not None:
            statement = statement.where(
                tuple_(AnalysisJob.updated_at, AnalysisJob.id)
                > tuple_(cursor[0], cursor[1])
            )
        rows = self._session.scalars(
            statement.order_by(AnalysisJob.updated_at, AnalysisJob.id).limit(limit + 1)
        ).all()
        return list(rows[:limit]), len(rows) > limit

    def database_now(self) -> datetime:
        value = self._session.scalar(select(func.now()))
        if not isinstance(value, datetime):
            raise RuntimeError("database clock is unavailable")
        return value

    def update_idempotency_response(
        self,
        *,
        key: str,
        job_id: UUID,
        response_body: dict,
    ) -> None:
        record = self.get_idempotency_record(key)
        if record is None or record.response_body.get("id") != str(job_id):
            return
        record.response_body = response_body
        self._session.flush()

    def create_or_reuse_job(
        self,
        target: CanonicalTarget,
        *,
        mode: JobMode,
        correlation_id: str | None,
    ) -> JobCreationResult:
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
        active = self.active_job(target)
        if active is not None:
            return JobCreationResult(job=active)
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
