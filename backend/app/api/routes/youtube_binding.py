"""Resolve an explicit first YouTube source binding before requesting Analyze."""

from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_session
from app.core.errors import APIError
from app.core.idempotency import (
    validate_idempotency_key,
    request_hash,
    utc_now,
    IDEMPOTENCY_RETENTION,
)
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import acquire_job_change_lock
from app.db.models.enums import TargetType
from app.analysis.targets import (
    canonicalize_target,
    resolve_target,
    InvalidTarget,
    ChannelResolutionUnavailable,
)
from app.integrations.errors import TransientIntegrationError, PermanentIntegrationError
from app.repositories.creator_library import CreatorLibraryRepository, detail
from app.repositories.collection_settings import require_collection
from app.schemas.creator_library import CreatorDetail, IdentityUpdate
from app.schemas.youtube_binding import YouTubeBinding


def cached(session, key, digest):
    record = session.scalar(
        select(IdempotencyRecord)
        .where(IdempotencyRecord.key == key)
        .execution_options(populate_existing=True)
    )
    if record is None or (record.expires_at and record.expires_at <= utc_now()):
        return None
    if record.request_hash != digest:
        raise APIError(
            status_code=409,
            code="idempotency_key_conflict",
            message="This key was used for another request.",
        )
    return record.response_body


def selected_creator(session, creator_id, value, target, *, lock=False):
    repository = CreatorLibraryRepository(session)
    creator = repository.get(creator_id, lock=lock)
    repository._revision(creator, value.expected_revision)
    if creator.platform != "youtube":
        raise APIError(
            status_code=422,
            code="youtube_binding_platform_invalid",
            message="This source-binding action is for YouTube Creators only.",
        )
    account = creator.platform_account_id or creator.youtube_channel_id
    if account and not target.requires_resolution and account != target.canonical_id:
        raise APIError(
            status_code=409,
            code="creator_source_identity_conflict",
            message="This Creator already has a different YouTube channel. Use explicit identity correction instead.",
        )
    return creator


def create_router(authenticate_workspace):
    router = APIRouter(
        prefix="/api/v2/library/creators",
        tags=["creator-library"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.post(
        "/{creator_id}/youtube-binding",
        response_model=CreatorDetail,
        operation_id="bindYouTubeCreatorSourceV2",
    )
    def bind(
        creator_id: UUID,
        value: YouTubeBinding,
        request: Request,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        try:
            validate_idempotency_key(key)
        except ValueError:
            raise APIError(
                status_code=422,
                code="request_invalid",
                message="A valid Idempotency-Key is required.",
            ) from None
        path = f"/api/v2/library/creators/{creator_id}/youtube-binding"
        record_key = f"youtube-binding:{creator_id}:{key}"
        digest = request_hash(
            method="POST", path=path, canonical_request=value.model_dump(mode="json")
        )
        body = cached(session, record_key, digest)
        if body is not None:
            session.commit()
            return JSONResponse(content=body)
        target = canonicalize_target(TargetType.CREATOR, value.url)
        selected_creator(session, creator_id, value, target)
        if target.requires_resolution:
            require_collection(session, "youtube")
        session.commit()
        try:
            target = resolve_target(
                TargetType.CREATOR,
                value.url,
                request.app.state.youtube_binding_resolver,
            )
        except (ChannelResolutionUnavailable, TransientIntegrationError):
            raise APIError(
                status_code=503,
                code="channel_resolution_unavailable",
                message="YouTube channel resolution is temporarily unavailable. Retry without creating another Creator.",
                retryable=True,
            ) from None
        except InvalidTarget:
            raise APIError(
                status_code=422,
                code="youtube_binding_target_invalid",
                message="The YouTube channel could not be resolved to a supported identity.",
            ) from None
        except PermanentIntegrationError as error:
            if error.code == "youtube_channel_not_found":
                raise APIError(
                    status_code=404,
                    code="youtube_channel_not_found",
                    message="This YouTube channel was not found.",
                ) from None
            raise APIError(
                status_code=502,
                code="youtube_binding_unavailable",
                message="YouTube channel resolution is not available with the current connection.",
            ) from None
        acquire_job_change_lock(session)
        body = cached(session, record_key, digest)
        if body is None:
            selected_creator(session, creator_id, value, target, lock=True)
            creator = CreatorLibraryRepository(session).rebind(
                creator_id,
                IdentityUpdate(
                    expected_revision=value.expected_revision,
                    platform="youtube",
                    account_id=target.canonical_id,
                    profile_url=target.canonical_url,
                    confirmed=True,
                ),
            )
            body = detail(creator).model_dump(mode="json")
            old = session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == record_key)
            )
            if old is not None:
                session.delete(old)
                session.flush()
            session.add(
                IdempotencyRecord(
                    key=record_key,
                    request_hash=digest,
                    method="POST",
                    path=path,
                    response_status=200,
                    response_body=body,
                    expires_at=utc_now() + IDEMPOTENCY_RETENTION,
                )
            )
        session.commit()
        return JSONResponse(content=body)

    return router
