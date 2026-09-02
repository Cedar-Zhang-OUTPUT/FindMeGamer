from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Annotated, Any, ContextManager, Protocol
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.targets import (
    CanonicalTarget,
    ChannelResolutionUnavailable,
    ChannelResolver,
    InvalidTarget,
    UnavailableChannelResolver,
    resolve_target,
)
from app.core.errors import APIError
from app.core.idempotency import (
    IDEMPOTENCY_RETENTION,
    InvalidIdempotencyKey,
    request_hash,
    validate_idempotency_key,
)
from app.db.models.enums import JobStatus
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob
from app.repositories.jobs import JobCreationResult, JobsRepository
from app.schemas.jobs import (
    AnalysisJobCreate,
    AnalysisJobError,
    AnalysisJobOutcome,
    AnalysisJobResponse,
    ChangedJobsResponse,
    ExistingProfileResponse,
    RetryAnalysisJobRequest,
)


SessionFactory = Callable[[], ContextManager[Session]]
IdempotencyClock = Callable[[], datetime]
FailureClock = Callable[[], datetime]
_ZERO_UUID = UUID(int=0)
_CURSOR_MAX_LENGTH = 2_048
_GENERIC_FAILURE = AnalysisJobError(
    code="analysis_internal_error",
    message="Analysis failed unexpectedly. Please retry.",
)
_SPECIAL_ERRORS = {
    "analysis_internal_error": _GENERIC_FAILURE,
    "analysis_queue_unavailable": AnalysisJobError(
        code="analysis_queue_unavailable",
        message="Analysis could not be queued. Please retry.",
    ),
}
_KNOWN_INTEGRATION_CODES = frozenset(
    {
        "analysis_clock_invalid",
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
    if job.error_code in _SPECIAL_ERRORS:
        return _SPECIAL_ERRORS[job.error_code]
    if job.error_code in _KNOWN_INTEGRATION_CODES:
        message = (
            "Analysis is temporarily unavailable. Please retry."
            if job.retryable
            else "Analysis could not be completed for this target."
        )
        return AnalysisJobError(code=job.error_code, message=message)
    return _GENERIC_FAILURE


def project_analysis_job(job: AnalysisJob) -> AnalysisJobResponse:
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
        retryable=job.retryable,
        error=_safe_error(job),
        correlation_id=job.correlation_id,
        profile_id=job.profile_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _public_result(result: JobCreationResult, target) -> tuple[int, dict[str, Any]]:
    if result.job is not None:
        response = project_analysis_job(result.job)
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
                status, body = _public_result(result, target)
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
) -> JSONResponse:
    body = committed.body
    if body.get("outcome") != "job" or body.get("status") != JobStatus.QUEUED.value:
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
        if persisted.status is not JobStatus.QUEUED:
            current_body = project_analysis_job(persisted).model_dump(mode="json")
            repository.update_idempotency_response(
                key=key,
                job_id=job_id,
                response_body=current_body,
            )
            database_session.commit()
            return _json_response(
                CommittedResponse(committed.status_code, current_body)
            )
        database_session.commit()
    try:
        dispatcher.dispatch(job_id)
        return _json_response(committed)
    except Exception:
        from app.workers.analysis_tasks import (
            QUEUE_FAILURE_MESSAGE,
            TerminalFailure,
            write_terminal_failure,
        )

        try:
            write_terminal_failure(
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
                failed_body = project_analysis_job(job).model_dump(mode="json")
                repository.update_idempotency_response(
                    key=key, job_id=job_id, response_body=failed_body
                )
                database_session.commit()
            return _json_response(CommittedResponse(committed.status_code, failed_body))
        except APIError:
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


def _status_scope(status: JobStatus | None) -> str | None:
    return status.value if status is not None else None


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
    value: tuple[datetime, UUID], *, status: JobStatus | None, signing_key: bytes
) -> str:
    signed: dict[str, object] = {
        "v": 1,
        "key": [_cursor_timestamp(value[0]), str(value[1])],
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
    status: JobStatus | None,
    signing_key: bytes,
) -> tuple[datetime, UUID] | None:
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
            or value["v"] != 1
            or type(value["v"]) is not int
            or not isinstance(value["key"], list)
            or len(value["key"]) != 2
            or not all(isinstance(item, str) for item in value["key"])
            or value["scope"] != {"status": _status_scope(status)}
            or not isinstance(value["signature"], str)
            or len(value["signature"]) != 64
        ):
            raise ValueError("invalid cursor shape")
        signed = {"v": value["v"], "key": value["key"], "scope": value["scope"]}
        expected = _cursor_signature(signed, signing_key=signing_key)
        if not hmac.compare_digest(value["signature"], expected):
            raise ValueError("invalid signature")
        timestamp_text, job_id_text = value["key"]
        if not timestamp_text.endswith("Z"):
            raise ValueError("naive timestamp")
        timestamp = datetime.fromisoformat(timestamp_text[:-1] + "+00:00")
        if _cursor_timestamp(timestamp) != timestamp_text:
            raise ValueError("noncanonical timestamp")
        job_id = UUID(job_id_text)
        if str(job_id) != job_id_text:
            raise ValueError("noncanonical UUID")
        return timestamp, job_id
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

    @router.get("", response_model=ChangedJobsResponse)
    def list_changed_jobs(
        changed_after: str | None = None,
        status: JobStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> ChangedJobsResponse:
        decoded = _decode_cursor(
            changed_after, status=status, signing_key=cursor_signing_key
        )
        with session_factory() as database_session:
            repository = JobsRepository(database_session)
            jobs, has_more = repository.list_changed_jobs(
                cursor=decoded, status=status, limit=limit
            )
            if jobs:
                next_value = (jobs[-1].updated_at, jobs[-1].id)
                cursor = _encode_cursor(
                    next_value, status=status, signing_key=cursor_signing_key
                )
            elif changed_after is not None:
                cursor = changed_after
            else:
                cursor = _encode_cursor(
                    (repository.database_now(), _ZERO_UUID),
                    status=status,
                    signing_key=cursor_signing_key,
                )
            items = [project_analysis_job(job) for job in jobs]
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

    @router.get("/{job_id}", response_model=AnalysisJobResponse)
    def read_job(job_id: UUID) -> AnalysisJobResponse:
        with session_factory() as database_session:
            job = JobsRepository(database_session).get_job(job_id)
            if job is None:
                raise APIError(
                    status_code=404,
                    code="analysis_job_not_found",
                    message="The Analysis Job was not found.",
                )
            response = project_analysis_job(job)
            database_session.commit()
            return response

    @router.post(
        "/analysis",
        response_model=AnalysisJobOutcome,
        responses={201: {"model": AnalysisJobOutcome}},
    )
    def create_analysis_job(
        payload: AnalysisJobCreate,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> JSONResponse:
        key = _validated_idempotency_key(idempotency_key)
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

    return router
