from collections.abc import Callable
from typing import Annotated, Any, ContextManager
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request
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
    InvalidIdempotencyKey,
    request_hash,
    validate_idempotency_key,
)
from app.db.models.enums import JobStatus
from app.repositories.jobs import JobCreationResult, JobsRepository
from app.schemas.jobs import (
    AnalysisJobCreate,
    AnalysisJobOutcome,
    AnalysisJobResponse,
    ExistingProfileResponse,
    RetryAnalysisJobRequest,
)


SessionFactory = Callable[[], ContextManager[Session]]


def _public_result(result: JobCreationResult, target) -> tuple[int, dict[str, Any]]:
    if result.job is not None:
        response = AnalysisJobResponse.model_validate(result.job, from_attributes=True)
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


def _stored_response(repository: JobsRepository, key: str, digest: str):
    record = repository.get_idempotency_record(key)
    if record is None:
        return None
    if record.request_hash != digest:
        raise _idempotency_conflict()
    return JSONResponse(
        status_code=record.response_status,
        content=record.response_body,
    )


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
) -> JSONResponse:
    with session_factory() as database_session:
        repository = JobsRepository(database_session)
        for _attempt in range(3):
            stored = _stored_response(repository, key, digest)
            if stored is not None:
                return stored
            try:
                result, target = build_result(repository)
                status, body = _public_result(result, target)
                repository.add_idempotency_record(
                    key=key,
                    request_hash=digest,
                    method=method,
                    path=path,
                    response_status=status,
                    response_body=body,
                )
                database_session.commit()
                return JSONResponse(status_code=status, content=body)
            except IntegrityError:
                database_session.rollback()
        stored = _stored_response(repository, key, digest)
        if stored is not None:
            return stored
        raise APIError(
            status_code=503,
            code="analysis_job_creation_conflict",
            message="The analysis request could not be committed safely.",
            retryable=True,
        )


def create_router(
    authenticate_workspace: Callable,
    *,
    session_factory: SessionFactory,
    channel_resolver: ChannelResolver | None = None,
) -> APIRouter:
    resolver = channel_resolver or UnavailableChannelResolver()
    router = APIRouter(
        prefix="/api/v1/jobs",
        tags=["jobs"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.post(
        "/analysis",
        response_model=AnalysisJobOutcome,
        responses={201: {"model": AnalysisJobOutcome}},
    )
    def create_analysis_job(
        payload: AnalysisJobCreate,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key")
        ],
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

        return _execute_idempotent(
            session_factory=session_factory,
            key=key,
            digest=digest,
            method="POST",
            path=path,
            build_result=build_result,
        )

    @router.post(
        "/analysis/{job_id}/retry",
        response_model=AnalysisJobResponse,
        responses={201: {"model": AnalysisJobResponse}},
    )
    def retry_analysis_job(
        job_id: UUID,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key")
        ],
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
                    source,
                    correlation_id=request.state.correlation_id,
                ),
                target,
            )

        return _execute_idempotent(
            session_factory=session_factory,
            key=key,
            digest=digest,
            method="POST",
            path=path,
            build_result=build_result,
        )

    return router
