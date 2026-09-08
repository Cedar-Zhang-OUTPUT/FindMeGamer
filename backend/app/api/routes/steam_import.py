"""Explicit source-only fetch with short atomic publication, never a model job."""

from typing import Annotated
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
from app.schemas.steam_import import SteamImport
from app.schemas.library_v2 import GameDetail
from app.analysis.targets import canonicalize_target
from app.db.models.enums import TargetType
from app.repositories.steam_import import import_target, publish_source
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError

PATH = "/api/v2/library/games/steam-import"


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


def create_router(authenticate_workspace):
    router = APIRouter(
        tags=["library-v2"], dependencies=[Depends(authenticate_workspace)]
    )

    @router.post(
        PATH, response_model=GameDetail, operation_id="importSteamGameSourceV2"
    )
    def import_steam(
        value: SteamImport,
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
        record_key = "steam-import:" + key
        digest = request_hash(
            method="POST", path=PATH, canonical_request=value.model_dump(mode="json")
        )
        body = cached(session, record_key, digest)
        if body is not None:
            session.commit()
            return JSONResponse(content=body)
        target = canonicalize_target(TargetType.GAME, value.url)
        import_target(session, value, target.canonical_id)
        # Release the read transaction before Steam's network I/O. Publication
        # rechecks identity, revision and request replay under the shared write lock.
        session.commit()
        try:
            with request.app.state.steam_gateway_factory() as gateway:
                source = gateway.fetch_game(target.canonical_id)
        except TransientIntegrationError:
            raise APIError(
                status_code=503,
                code="steam_unavailable",
                message="Steam source is unavailable. Retry or enter the game details manually.",
                retryable=True,
            ) from None
        except PermanentIntegrationError as error:
            if error.code == "steam_game_not_found":
                raise APIError(
                    status_code=404,
                    code="steam_game_not_found",
                    message="This Steam game was not found. Check the link or enter details manually.",
                ) from None
            raise APIError(
                status_code=502,
                code="steam_source_invalid",
                message="Steam did not return usable game details. Existing data is unchanged.",
            ) from None
        if (
            source.app_id != target.canonical_id
            or source.canonical_url != target.canonical_url
        ):
            raise APIError(
                status_code=502,
                code="steam_source_invalid",
                message="Steam returned an unexpected game identity.",
            )
        acquire_job_change_lock(session)
        body = cached(session, record_key, digest)
        if body is None:
            old = session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == record_key)
            )
            if old is not None:
                session.delete(old)
                session.flush()
            body = publish_source(session, value, source)
            session.add(
                IdempotencyRecord(
                    key=record_key,
                    request_hash=digest,
                    method="POST",
                    path=PATH,
                    response_status=200,
                    response_body=body,
                    expires_at=utc_now() + IDEMPOTENCY_RETENTION,
                )
            )
        session.commit()
        return JSONResponse(content=body)

    return router
