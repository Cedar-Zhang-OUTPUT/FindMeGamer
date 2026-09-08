from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedWorkspace
from app.core.database import get_session
from app.core.errors import APIError
from app.core.idempotency import (
    IDEMPOTENCY_RETENTION,
    InvalidIdempotencyKey,
    request_hash,
    utc_now,
    validate_idempotency_key,
)
from app.db.models.jobs import acquire_job_change_lock
from app.repositories.jobs import JobsRepository
from app.repositories.library_v2 import LibraryGamesRepository, game_detail
from app.schemas.library_v2 import GameCreate, GameDetail, GamePage, GamePatch


def create_router(authenticate_workspace: Callable) -> APIRouter:
    router = APIRouter(
        prefix="/api/v2/library/games",
        tags=["library-v2"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get("", response_model=GamePage, operation_id="listLibraryGamesV2")
    def list_games(
        query: Annotated[str, Query(max_length=255)] = "",
        only_collection: bool = False,
        website_status: Literal["all", "available", "missing"] = "all",
        sort: Literal["name", "recent_updated", "recent_added"] = "name",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        session: Session = Depends(get_session),
    ) -> GamePage:
        return LibraryGamesRepository(session).list(
            query=query,
            only_collection=only_collection,
            limit=limit,
            offset=offset,
            website_status=website_status,
            sort=sort,
        )

    @router.post(
        "",
        response_model=GameDetail,
        status_code=201,
        operation_id="createLibraryGameV2",
    )
    def create_game(
        value: GameCreate,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        workspace: AuthenticatedWorkspace = Depends(authenticate_workspace),
        session: Session = Depends(get_session),
    ) -> JSONResponse:
        try:
            key = validate_idempotency_key(idempotency_key)
        except InvalidIdempotencyKey:
            raise APIError(
                status_code=422,
                code="request_invalid",
                message="The request is invalid.",
            ) from None
        path = "/api/v2/library/games"
        key = f"library-game:{workspace.key_digest}:{key}"
        digest = request_hash(
            method="POST",
            path=path,
            canonical_request=value.model_dump(mode="json", exclude_unset=True),
        )
        acquire_job_change_lock(session)
        records = JobsRepository(session)
        record = records.get_idempotency_record(key)
        now = utc_now()
        if (
            record is not None
            and record.expires_at is not None
            and record.expires_at <= now
        ):
            records.delete_idempotency_record(record)
            record = None
        if record is not None:
            if record.request_hash != digest:
                raise APIError(
                    status_code=409,
                    code="idempotency_key_conflict",
                    message="This idempotency key was used for another request.",
                )
            body, status = record.response_body, record.response_status
            session.commit()
            return JSONResponse(status_code=status, content=body)
        profile = LibraryGamesRepository(session).create(value)
        body = game_detail(profile).model_dump(mode="json")
        records.add_idempotency_record(
            key=key,
            request_hash=digest,
            method="POST",
            path=path,
            response_status=201,
            response_body=body,
            expires_at=now + IDEMPOTENCY_RETENTION,
        )
        session.commit()
        return JSONResponse(status_code=201, content=body)

    @router.get(
        "/{game_id}", response_model=GameDetail, operation_id="getLibraryGameV2"
    )
    def get_game(game_id: UUID, session: Session = Depends(get_session)) -> GameDetail:
        return game_detail(LibraryGamesRepository(session).get(game_id))

    @router.patch(
        "/{game_id}", response_model=GameDetail, operation_id="updateLibraryGameV2"
    )
    def patch_game(
        game_id: UUID, value: GamePatch, session: Session = Depends(get_session)
    ) -> GameDetail:
        profile = LibraryGamesRepository(session).patch(game_id, value)
        result = game_detail(profile)
        session.commit()
        return result

    return router
