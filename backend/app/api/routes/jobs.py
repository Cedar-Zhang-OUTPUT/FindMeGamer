from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Annotated, Any, ContextManager, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy import literal, select, tuple_, union_all
from sqlalchemy.orm import Session

from app.analysis.targets import (
    CanonicalTarget,
    ChannelResolutionUnavailable,
    ChannelResolver,
    InvalidTarget,
    UnavailableChannelResolver,
    resolve_target,
)
from app.core.errors import APIError, safe_correlation_id
from app.core.analysis_job_contract import (
    INTEGRATION_ERROR_CODES,
    public_job_failure,
    valid_analysis_job_state,
)
from app.core.idempotency import (
    IDEMPOTENCY_RETENTION,
    InvalidIdempotencyKey,
    request_hash,
    validate_idempotency_key,
)
from app.db.models.enums import JobStatus, TargetType
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob
from app.db.models.jobs import acquire_job_change_lock
from app.db.models.match import MatchStatus, MatchTask
from app.integrations.errors import PermanentIntegrationError
from app.repositories.jobs import (
    JobCreationResult,
    JobsRepository,
    require_valid_succeeded_job_result,
)
from app.schemas.jobs import (
    AnalysisJobCreate,
    AnalysisJobError,
    AnalysisJobOutcome,
    AnalysisJobResponse,
    ChangedAnalysisJobResponse,
    ChangedMatchJobResponse,
    ChangedJobsResponse,
    ExistingProfileResponse,
    RetryAnalysisJobRequest,
)
from app.api.routes.match import _failure as _match_failure


SessionFactory = Callable[[], ContextManager[Session]]
IdempotencyClock = Callable[[], datetime]
FailureClock = Callable[[], datetime]
_ZERO_UUID = UUID(int=0)
_CURSOR_MAX_LENGTH = 2_048
_GENERIC_FAILURE = AnalysisJobError(
    code="analysis_internal_error",
    message="Analysis failed unexpectedly. Please retry.",
)


class JobDispatcher(Protocol):
    def dispatch(self, job_id: UUID) -> None: ...


class CeleryJobDispatcher:
    def __init__(self, *, app=None, queue: str | None = None) -> None:
        self._app = app
        self._queue = queue

    def dispatch(self, job_id: UUID) -> None:
        if not isinstance(job_id, UUID) or job_id.int == 0:
            raise ValueError("invalid Analysis Job ID")
        options: dict[str, object] = {
            "retry": False,
            "ignore_result": True,
        }
        if self._queue is not None:
            options["queue"] = self._queue
        if self._app is not None:
            from app.workers.analysis_tasks import ANALYSIS_TASK_NAME

            self._app.send_task(
                ANALYSIS_TASK_NAME,
                args=[str(job_id)],
                **options,
            )
            return
        from app.workers.analysis_tasks import run_analysis_job

        run_analysis_job.apply_async(
            args=[str(job_id)],
            **options,
        )


@dataclass(frozen=True, slots=True)
class CommittedResponse:
    status_code: int
    body: dict[str, Any]


def _safe_error(job: AnalysisJob) -> AnalysisJobError | None:
    if job.status is not JobStatus.FAILED:
        return None
    failure = public_job_failure(job.error_code)
    if failure is None:
        return _GENERIC_FAILURE
    return AnalysisJobError(code=job.error_code, message=failure.message)


def _invalid_job_result() -> APIError:
    return APIError(
        status_code=500,
        code="analysis_job_result_invalid",
        message="The Analysis Job result is invalid.",
    )


def _invalid_job_state() -> APIError:
    return APIError(
        status_code=500,
        code="analysis_job_state_invalid",
        message="The Analysis Job state is invalid.",
    )


def _require_safe_public_job_state(
    job: AnalysisJob, error: AnalysisJobError | None, retryable: bool
) -> None:
    if not valid_analysis_job_state(
        status=job.status,
        stage=job.stage,
        completed_units=job.completed_units,
        total_units=job.total_units,
        error_code=error.code if error is not None else None,
        error_message=error.message if error is not None else None,
        retryable=retryable,
        profile_id=job.profile_id,
        result_present=job.result_payload is not None,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    ):
        raise _invalid_job_state()


_SUCCEEDED_PROFILE_NOT_PROVIDED = object()


def project_analysis_job(
    database_session: Session,
    job: AnalysisJob,
    *,
    succeeded_profile: object = _SUCCEEDED_PROFILE_NOT_PROVIDED,
) -> AnalysisJobResponse:
    error = _safe_error(job)
    failure = public_job_failure(error.code) if error is not None else None
    retryable = failure.retryable if failure is not None else job.retryable
    _require_safe_public_job_state(job, error, retryable)
    try:
        if succeeded_profile is _SUCCEEDED_PROFILE_NOT_PROVIDED:
            require_valid_succeeded_job_result(database_session, job)
        else:
            require_valid_succeeded_job_result(
                database_session, job, succeeded_profile=succeeded_profile
            )
    except PermanentIntegrationError as error:
        if error.code == "analysis_job_result_invalid":
            raise _invalid_job_result() from None
        raise
    from app.repositories.collection_settings import analysis_waiting_state

    waiting_reason, resume_available = analysis_waiting_state(database_session, job)
    return AnalysisJobResponse(
        id=job.id,
        target_type=job.target_type,
        canonical_target_id=job.canonical_target_id,
        canonical_url=job.canonical_url,
        mode=job.mode,
        status=job.status,
        stage=job.stage,
        completed_units=job.completed_units,
        total_units=job.total_units,
        retryable=retryable,
        error=error,
        correlation_id=safe_correlation_id(job.correlation_id),
        profile_id=job.profile_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        waiting_reason=waiting_reason,
        resume_available=resume_available,
    )


def _public_result(
    database_session: Session, result: JobCreationResult, target
) -> tuple[int, dict[str, Any]]:
    if result.job is not None:
        response = project_analysis_job(database_session, result.job)
        return (201 if result.created else 200), response.model_dump(mode="json")
    response = ExistingProfileResponse(
        existing_profile_id=result.existing_profile_id,
        target_type=target.target_type,
        canonical_target_id=target.canonical_id,
        canonical_url=target.canonical_url,
    )
    return 200, response.model_dump(mode="json")


def _idempotency_conflict() -> APIError:
    return APIError(
        status_code=409,
        code="idempotency_key_conflict",
        message="The Idempotency-Key was already used for another request.",
    )


def _stored_response(
    repository: JobsRepository,
    key: str,
    digest: str,
    *,
    now: datetime,
) -> tuple[CommittedResponse | None, IdempotencyRecord | None]:
    record = repository.get_idempotency_record(key)
    if record is None:
        return None, None
    if record.expires_at is None or record.expires_at <= now:
        return None, record
    if record.request_hash != digest:
        raise _idempotency_conflict()
    return CommittedResponse(record.response_status, dict(record.response_body)), None


def _validated_idempotency_key(value: str | None) -> str:
    try:
        return validate_idempotency_key(value)
    except InvalidIdempotencyKey:
        raise APIError(
            status_code=400,
            code="idempotency_key_invalid",
            message="A valid Idempotency-Key is required.",
        ) from None


def _execute_idempotent(
    *,
    session_factory: SessionFactory,
    key: str,
    digest: str,
    method: str,
    path: str,
    build_result: Callable[[JobsRepository], tuple[JobCreationResult, Any]],
    now: datetime,
) -> CommittedResponse:
    with session_factory() as database_session:
        repository = JobsRepository(database_session)
        for _attempt in range(3):
            stored, expired_record = _stored_response(repository, key, digest, now=now)
            if stored is not None:
                database_session.commit()
                return stored
            try:
                result, target = build_result(repository)
                status, body = _public_result(database_session, result, target)
                if expired_record is not None:
                    repository.delete_idempotency_record(expired_record)
                repository.add_idempotency_record(
                    key=key,
                    request_hash=digest,
                    method=method,
                    path=path,
                    response_status=status,
                    response_body=body,
                    expires_at=now + IDEMPOTENCY_RETENTION,
                )
                database_session.commit()
                return CommittedResponse(status, body)
            except IntegrityError:
                database_session.rollback()
        stored, _expired_record = _stored_response(repository, key, digest, now=now)
        if stored is not None:
            database_session.commit()
            return stored
        raise APIError(
            status_code=503,
            code="analysis_job_creation_conflict",
            message="The analysis request could not be committed safely.",
            retryable=True,
        )


def _json_response(committed: CommittedResponse) -> JSONResponse:
    return JSONResponse(status_code=committed.status_code, content=committed.body)


def _dispatch_committed_job(
    committed: CommittedResponse,
    *,
    key: str,
    dispatcher: JobDispatcher,
    session_factory: SessionFactory,
    failure_clock: FailureClock,
    allow_running: bool = False,
    fresh_resume: bool = False,
) -> JSONResponse:
    body = committed.body
    if body.get("outcome") != "job":
        return _json_response(committed)
    try:
        job_id = UUID(body["id"])
        if str(job_id) != body["id"] or job_id.int == 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise APIError(
            status_code=500,
            code="analysis_job_result_invalid",
            message="The Analysis Job result is invalid.",
        ) from None
    with session_factory() as database_session:
        repository = JobsRepository(database_session)
        persisted = repository.get_job_for_update(job_id)
        if persisted is None:
            raise APIError(
                status_code=500,
                code="analysis_job_result_invalid",
                message="The Analysis Job result is invalid.",
            )
        if allow_running and persisted.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            if not fresh_resume and not persisted.collection_paused:
                current = project_analysis_job(database_session, persisted).model_dump(
                    mode="json"
                )
                database_session.commit()
                return _json_response(CommittedResponse(committed.status_code, current))
            from app.repositories.collection_settings import require_collection

            require_collection(database_session, "youtube")
            persisted.collection_paused = False
            database_session.flush()
        current_body = project_analysis_job(database_session, persisted).model_dump(
            mode="json"
        )
        repository.update_idempotency_response(
            key=key,
            job_id=job_id,
            response_body=current_body,
        )
        if persisted.status is not JobStatus.QUEUED and not (
            allow_running and persisted.status is JobStatus.RUNNING
        ):
            database_session.commit()
            return _json_response(
                CommittedResponse(committed.status_code, current_body)
            )
        database_session.commit()
        committed = CommittedResponse(committed.status_code, current_body)
    try:
        dispatcher.dispatch(job_id)
        return _json_response(committed)
    except Exception:
        if allow_running:
            with session_factory() as paused_session:
                paused = JobsRepository(paused_session).get_job_for_update(job_id)
                if paused is not None and paused.status in (
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                ):
                    paused.collection_paused = True
                paused_session.commit()
            raise APIError(
                status_code=503,
                code="analysis_queue_unavailable",
                message="Analysis could not be queued. Please resume again.",
                retryable=True,
            ) from None
        from app.workers.analysis_tasks import (
            QUEUE_FAILURE_MESSAGE,
            TerminalFailure,
            write_queued_publication_failure,
        )

        try:
            write_queued_publication_failure(
                job_id,
                TerminalFailure(
                    code="analysis_queue_unavailable",
                    message=QUEUE_FAILURE_MESSAGE,
                    retryable=True,
                ),
                session_factory=session_factory,
                clock=failure_clock,
            )
            with session_factory() as database_session:
                repository = JobsRepository(database_session)
                job = repository.get_job_for_update(job_id)
                if job is None:
                    raise APIError(
                        status_code=500,
                        code="analysis_job_result_invalid",
                        message="The Analysis Job result is invalid.",
                    )
                failed_body = project_analysis_job(database_session, job).model_dump(
                    mode="json"
                )
                repository.update_idempotency_response(
                    key=key, job_id=job_id, response_body=failed_body
                )
                database_session.commit()
            return _json_response(CommittedResponse(committed.status_code, failed_body))
        except APIError:
            raise
        except PermanentIntegrationError as error:
            if error.code == "analysis_job_result_invalid":
                raise _invalid_job_result() from None
            raise
        except Exception:
            raise APIError(
                status_code=503,
                code="analysis_queue_unavailable",
                message="Analysis could not be queued. Please retry.",
                retryable=True,
            ) from None


def _invalid_cursor() -> APIError:
    return APIError(
        status_code=400,
        code="analysis_job_cursor_invalid",
        message="The Analysis Job cursor is invalid.",
    )


ChangedStatus = Literal["queued", "running", "succeeded", "failed", "superseded"]


def _status_scope(status: ChangedStatus | JobStatus | None) -> str | None:
    return status.value if isinstance(status, JobStatus) else status


def _cursor_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cursor timestamp must be aware")
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _cursor_signature(payload: dict[str, object], *, signing_key: bytes) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(signing_key, canonical, hashlib.sha256).hexdigest()


def _encode_cursor(
    value: tuple[datetime, str, UUID],
    *,
    status: ChangedStatus | None,
    signing_key: bytes,
) -> str:
    signed: dict[str, object] = {
        "v": 2,
        "key": [_cursor_timestamp(value[0]), value[1], str(value[2])],
        "scope": {"status": _status_scope(status)},
    }
    payload = {
        **signed,
        "signature": _cursor_signature(signed, signing_key=signing_key),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(
    raw_cursor: str | None,
    *,
    status: ChangedStatus | None,
    signing_key: bytes,
) -> tuple[datetime, str, UUID] | None:
    if raw_cursor is None:
        return None
    if not raw_cursor or len(raw_cursor) > _CURSOR_MAX_LENGTH:
        raise _invalid_cursor()
    try:
        padded = raw_cursor + "=" * (-len(raw_cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode().rstrip("=") != raw_cursor:
            raise ValueError("noncanonical base64")
        value = json.loads(raw.decode())
        if (
            not isinstance(value, dict)
            or set(value) != {"v", "key", "scope", "signature"}
            or value["v"] != 2
            or type(value["v"]) is not int
            or not isinstance(value["key"], list)
            or len(value["key"]) != 3
            or not all(isinstance(item, str) for item in value["key"])
            or value["scope"] != {"status": _status_scope(status)}
            or not isinstance(value["signature"], str)
            or len(value["signature"]) != 64
        ):
            raise ValueError("invalid cursor shape")
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        if raw != canonical:
            raise ValueError("noncanonical JSON")
        signed = {"v": value["v"], "key": value["key"], "scope": value["scope"]}
        expected = _cursor_signature(signed, signing_key=signing_key)
        if not hmac.compare_digest(value["signature"], expected):
            raise ValueError("invalid signature")
        timestamp_text, kind, job_id_text = value["key"]
        if not timestamp_text.endswith("Z"):
            raise ValueError("naive timestamp")
        timestamp = datetime.fromisoformat(timestamp_text[:-1] + "+00:00")
        if _cursor_timestamp(timestamp) != timestamp_text:
            raise ValueError("noncanonical timestamp")
        job_id = UUID(job_id_text)
        if str(job_id) != job_id_text:
            raise ValueError("noncanonical UUID")
        if kind not in {"analysis", "match"} and not (
            kind == "" and job_id == _ZERO_UUID
        ):
            raise ValueError("invalid kind")
        return timestamp, kind, job_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        raise _invalid_cursor() from None


def create_router(
    authenticate_workspace: Callable,
    *,
    session_factory: SessionFactory,
    channel_resolver: ChannelResolver | None = None,
    idempotency_clock: IdempotencyClock,
    dispatcher: JobDispatcher | None = None,
    failure_clock: FailureClock,
    cursor_signing_secret: str,
) -> APIRouter:
    resolver = channel_resolver or UnavailableChannelResolver()
    effective_dispatcher = dispatcher or CeleryJobDispatcher()
    cursor_signing_key = hashlib.sha256(
        b"find-me-gamer/job-cursor/v1\0" + cursor_signing_secret.encode()
    ).digest()
    router = APIRouter(
        prefix="/api/v1/jobs",
        tags=["jobs"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get("", response_model=ChangedJobsResponse, operation_id="listJobs")
    def list_changed_jobs(
        changed_after: str | None = None,
        status: ChangedStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> ChangedJobsResponse:
        decoded = _decode_cursor(
            changed_after, status=status, signing_key=cursor_signing_key
        )
        with session_factory() as database_session:
            acquire_job_change_lock(database_session)
            repository = JobsRepository(database_session)
            analysis_keys = select(
                AnalysisJob.updated_at.label("updated_at"),
                literal("analysis").label("kind"),
                AnalysisJob.id.label("resource_id"),
            )
            match_keys = select(
                MatchTask.updated_at.label("updated_at"),
                literal("match").label("kind"),
                MatchTask.id.label("resource_id"),
            )
            if status is not None:
                if status == "superseded":
                    analysis_keys = analysis_keys.where(literal(False))
                else:
                    analysis_keys = analysis_keys.where(AnalysisJob.status == status)
                match_keys = match_keys.where(MatchTask.status == status)
            changed = union_all(analysis_keys, match_keys).subquery()
            statement = select(
                changed.c.updated_at, changed.c.kind, changed.c.resource_id
            )
            if decoded is not None:
                statement = statement.where(
                    tuple_(
                        changed.c.updated_at,
                        changed.c.kind,
                        changed.c.resource_id,
                    )
                    > tuple_(decoded[0], decoded[1], decoded[2])
                )
            keys = database_session.execute(
                statement.order_by(
                    changed.c.updated_at,
                    changed.c.kind,
                    changed.c.resource_id,
                ).limit(limit + 1)
            ).all()
            page = list(keys[:limit])
            has_more = len(keys) > limit
            analysis_ids = [row.resource_id for row in page if row.kind == "analysis"]
            match_ids = [row.resource_id for row in page if row.kind == "match"]
            analysis_by_id = (
                {
                    value.id: value
                    for value in database_session.scalars(
                        select(AnalysisJob).where(AnalysisJob.id.in_(analysis_ids))
                    )
                }
                if analysis_ids
                else {}
            )
            match_by_id = (
                {
                    value.id: value
                    for value in database_session.scalars(
                        select(MatchTask).where(MatchTask.id.in_(match_ids))
                    )
                }
                if match_ids
                else {}
            )
            jobs = [
                analysis_by_id[row.resource_id]
                for row in page
                if row.kind == "analysis"
            ]
            succeeded_profiles = repository.load_succeeded_profiles(jobs)
            if page:
                next_value = (
                    page[-1].updated_at,
                    page[-1].kind,
                    page[-1].resource_id,
                )
                cursor = _encode_cursor(
                    next_value, status=status, signing_key=cursor_signing_key
                )
            elif changed_after is not None:
                cursor = changed_after
            else:
                cursor = _encode_cursor(
                    (repository.database_now(), "", _ZERO_UUID),
                    status=status,
                    signing_key=cursor_signing_key,
                )
            items = []
            for row in page:
                if row.kind == "analysis":
                    job = analysis_by_id[row.resource_id]
                    projected = project_analysis_job(
                        database_session,
                        job,
                        succeeded_profile=succeeded_profiles.get(
                            (job.target_type, job.profile_id)
                        ),
                    )
                    items.append(
                        ChangedAnalysisJobResponse(
                            **projected.model_dump(), resource_id=job.id
                        )
                    )
                else:
                    task = match_by_id[row.resource_id]
                    error, retryable = _match_failure(task)
                    items.append(
                        ChangedMatchJobResponse(
                            resource_id=task.id,
                            status=task.status.value,
                            stage=task.stage.value,
                            completed_units=task.completed_units,
                            total_units=task.total_units,
                            result_count=task.result_count,
                            retryable=retryable and bool(task.retryable),
                            error=error,
                            correlation_id=safe_correlation_id(task.correlation_id),
                            game_id=task.game_id,
                            supersedes_id=task.supersedes_id,
                            created_at=task.created_at,
                            updated_at=task.updated_at,
                            started_at=task.started_at,
                            completed_at=task.completed_at,
                        )
                    )
            affected_profile_ids = list(
                dict.fromkeys(
                    job.profile_id
                    for job in jobs
                    if job.status is JobStatus.SUCCEEDED and job.profile_id is not None
                )
            )
            database_session.commit()
        return ChangedJobsResponse(
            items=items,
            cursor=cursor,
            has_more=has_more,
            affected_profile_ids=affected_profile_ids,
        )

    @router.get(
        "/{job_id}", response_model=AnalysisJobResponse, operation_id="getAnalysisJob"
    )
    def read_job(job_id: UUID) -> AnalysisJobResponse:
        with session_factory() as database_session:
            job = JobsRepository(database_session).get_job(job_id)
            if job is None:
                raise APIError(
                    status_code=404,
                    code="analysis_job_not_found",
                    message="The Analysis Job was not found.",
                )
            response = project_analysis_job(database_session, job)
            database_session.commit()
            return response

    @router.post(
        "/analysis",
        response_model=AnalysisJobOutcome,
        responses={201: {"model": AnalysisJobOutcome}},
        operation_id="createAnalysisJob",
    )
    def create_analysis_job(
        payload: AnalysisJobCreate,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> JSONResponse:
        key = _validated_idempotency_key(idempotency_key)
        if payload.target_type is TargetType.CREATOR:
            from app.repositories.collection_settings import require_collection

            with session_factory() as collection_session:
                require_collection(collection_session, "youtube")
                collection_session.commit()
        try:
            target = resolve_target(payload.target_type, payload.url, resolver)
        except InvalidTarget:
            raise APIError(
                status_code=422,
                code="analysis_target_invalid",
                message="The analysis target URL is invalid or unsupported.",
            ) from None
        except ChannelResolutionUnavailable:
            raise APIError(
                status_code=503,
                code="channel_resolution_unavailable",
                message="YouTube Handle resolution is temporarily unavailable.",
                retryable=True,
            ) from None
        except PermanentIntegrationError as error:
            if error.code in {
                "youtube_channel_not_found",
                "youtube_target_invalid",
                "youtube_channel_id_invalid",
            }:
                raise APIError(
                    status_code=422,
                    code="analysis_target_invalid",
                    message="The analysis target URL is invalid or unsupported.",
                ) from None
            if error.code in {
                "analysis_configuration_invalid",
                "youtube_configuration_invalid",
            }:
                raise APIError(
                    status_code=503,
                    code="analysis_configuration_invalid",
                    message="Analysis service configuration is unavailable.",
                    retryable=False,
                ) from None
            if error.code == "analysis_cleanup_failed":
                raise APIError(
                    status_code=500,
                    code="analysis_cleanup_failed",
                    message="Analysis resources could not be closed safely.",
                    retryable=False,
                ) from None
            if error.code in INTEGRATION_ERROR_CODES:
                raise APIError(
                    status_code=502,
                    code=error.code,
                    message="YouTube Handle resolution could not be completed.",
                    retryable=False,
                ) from None
            raise APIError(
                status_code=500,
                code="analysis_internal_error",
                message="Analysis failed unexpectedly.",
                retryable=False,
            ) from None
        path = "/api/v1/jobs/analysis"
        digest = request_hash(
            method="POST",
            path=path,
            canonical_request={
                "target_type": target.target_type.value,
                "canonical_target_id": target.canonical_id,
                "mode": payload.mode.value,
            },
        )

        def build_result(repository: JobsRepository):
            return (
                repository.create_or_reuse_job(
                    target,
                    mode=payload.mode,
                    correlation_id=request.state.correlation_id,
                ),
                target,
            )

        committed = _execute_idempotent(
            session_factory=session_factory,
            key=key,
            digest=digest,
            method="POST",
            path=path,
            build_result=build_result,
            now=idempotency_clock(),
        )
        return _dispatch_committed_job(
            committed,
            key=key,
            dispatcher=effective_dispatcher,
            session_factory=session_factory,
            failure_clock=failure_clock,
        )

    @router.post(
        "/analysis/{job_id}/retry",
        response_model=AnalysisJobResponse,
        responses={201: {"model": AnalysisJobResponse}},
        operation_id="retryAnalysisJob",
    )
    def retry_analysis_job(
        job_id: UUID,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        payload: RetryAnalysisJobRequest = Body(
            default_factory=RetryAnalysisJobRequest
        ),
    ) -> JSONResponse:
        key = _validated_idempotency_key(idempotency_key)
        path = f"/api/v1/jobs/analysis/{job_id}/retry"
        digest = request_hash(
            method="POST",
            path=path,
            canonical_request={"source_job_id": str(job_id)},
        )

        def build_result(repository: JobsRepository):
            source = repository.get_job(job_id)
            if source is None:
                raise APIError(
                    status_code=404,
                    code="analysis_job_not_found",
                    message="The failed Analysis Job was not found.",
                )
            if source.status is not JobStatus.FAILED:
                raise APIError(
                    status_code=409,
                    code="analysis_job_not_failed",
                    message="Only failed Analysis Jobs can be retried.",
                )
            if not source.retryable:
                raise APIError(
                    status_code=409,
                    code="analysis_job_not_retryable",
                    message="This Analysis Job cannot be retried.",
                )
            target = CanonicalTarget(
                target_type=source.target_type,
                canonical_id=source.canonical_target_id,
                canonical_url=source.canonical_url,
            )
            return (
                repository.retry_or_reuse_job(
                    source, correlation_id=request.state.correlation_id
                ),
                target,
            )

        committed = _execute_idempotent(
            session_factory=session_factory,
            key=key,
            digest=digest,
            method="POST",
            path=path,
            build_result=build_result,
            now=idempotency_clock(),
        )
        return _dispatch_committed_job(
            committed,
            key=key,
            dispatcher=effective_dispatcher,
            session_factory=session_factory,
            failure_clock=failure_clock,
        )

    @router.post(
        "/analysis/{job_id}/resume",
        response_model=AnalysisJobResponse,
        operation_id="resumeCollectionAnalysisJob",
    )
    def resume_collection_job(
        job_id: UUID, idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]
    ):
        key = _validated_idempotency_key(idempotency_key)
        path = f"/api/v1/jobs/analysis/{job_id}/resume"
        digest = request_hash(
            method="POST", path=path, canonical_request={"job_id": str(job_id)}
        )
        fresh_resume = False

        def build_result(repository):
            nonlocal fresh_resume
            from app.repositories.collection_settings import require_collection

            job = repository.get_job_for_update(job_id)
            if job is None:
                raise APIError(
                    status_code=404,
                    code="analysis_job_not_found",
                    message="The Analysis Job was not found.",
                )
            if (
                job.target_type is not TargetType.CREATOR
                or not job.collection_paused
                or job.status not in (JobStatus.QUEUED, JobStatus.RUNNING)
            ):
                raise APIError(
                    status_code=409,
                    code="analysis_not_paused",
                    message="This Analysis Job is not paused for collection.",
                )
            require_collection(repository._session, "youtube")
            job.collection_paused = False
            fresh_resume = True
            repository._session.flush()
            target = CanonicalTarget(
                target_type=job.target_type,
                canonical_id=job.canonical_target_id,
                canonical_url=job.canonical_url,
            )
            return JobCreationResult(job=job), target

        committed = _execute_idempotent(
            session_factory=session_factory,
            key=key,
            digest=digest,
            method="POST",
            path=path,
            build_result=build_result,
            now=idempotency_clock(),
        )
        return _dispatch_committed_job(
            committed,
            key=key,
            dispatcher=effective_dispatcher,
            session_factory=session_factory,
            failure_clock=failure_clock,
            allow_running=True,
            fresh_resume=fresh_resume,
        )

    return router
