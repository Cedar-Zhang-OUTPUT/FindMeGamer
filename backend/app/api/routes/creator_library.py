from hashlib import sha256
from typing import Annotated
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
from app.repositories.creator_library import CreatorLibraryRepository, detail
from app.schemas.creator_library import (
    CreatorCreate,
    CreatorPatch,
    CreatorDetail,
    CreatorPage,
    Platform,
    IdentityUpdate,
    ContactCreate,
    ContactPatch,
    WorkCreate,
    WorkPatch,
    WorkDetail,
    WorkPage,
)


def create_router(authenticate_workspace):
    router = APIRouter(
        prefix="/api/v2/library/creators",
        tags=["library-v2"],
        dependencies=[Depends(authenticate_workspace)],
    )

    def once(session, workspace, key, path, value, create):
        try:
            key = validate_idempotency_key(key)
        except InvalidIdempotencyKey:
            raise APIError(
                status_code=422,
                code="request_invalid",
                message="The request is invalid.",
            ) from None
        scope = sha256(f"{workspace.key_digest}:{path}".encode()).hexdigest()
        key = f"creator:{scope}:{key}"
        digest = request_hash(
            method="POST",
            path=path,
            canonical_request=value.model_dump(mode="json", exclude_unset=True),
        )
        acquire_job_change_lock(session)
        records = JobsRepository(session)
        record = records.get_idempotency_record(key)
        now = utc_now()
        if record and record.expires_at and record.expires_at <= now:
            records.delete_idempotency_record(record)
            record = None
        if record:
            if record.request_hash != digest:
                raise APIError(
                    status_code=409,
                    code="idempotency_key_conflict",
                    message="This idempotency key was used for another request.",
                )
            body = record.response_body
            status = record.response_status
            session.commit()
            return JSONResponse(status_code=status, content=body)
        body = create().model_dump(mode="json")
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

    @router.get("", response_model=CreatorPage, operation_id="listLibraryCreatorsV2")
    def list_creators(
        query: Annotated[str, Query(max_length=255)] = "",
        platform: Platform | None = None,
        language: Annotated[str, Query(max_length=255)] = "",
        only_collection: bool = False,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        session: Session = Depends(get_session),
    ):
        return CreatorLibraryRepository(session).list(
            query=query,
            platform=platform,
            language=language,
            only_collection=only_collection,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "",
        response_model=CreatorDetail,
        status_code=201,
        operation_id="createLibraryCreatorV2",
    )
    def create_creator(
        value: CreatorCreate,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        workspace: AuthenticatedWorkspace = Depends(authenticate_workspace),
        session: Session = Depends(get_session),
    ):
        return once(
            session,
            workspace,
            idempotency_key,
            "/api/v2/library/creators",
            value,
            lambda: detail(CreatorLibraryRepository(session).create(value)),
        )

    @router.get(
        "/{creator_id}",
        response_model=CreatorDetail,
        operation_id="getLibraryCreatorV2",
    )
    def get_creator(creator_id: UUID, session: Session = Depends(get_session)):
        return detail(CreatorLibraryRepository(session).get(creator_id))

    @router.patch(
        "/{creator_id}",
        response_model=CreatorDetail,
        operation_id="updateLibraryCreatorV2",
    )
    def update_creator(
        creator_id: UUID, value: CreatorPatch, session: Session = Depends(get_session)
    ):
        result = detail(CreatorLibraryRepository(session).patch(creator_id, value))
        session.commit()
        return result

    @router.put(
        "/{creator_id}/identity",
        response_model=CreatorDetail,
        operation_id="rebindLibraryCreatorIdentityV2",
    )
    def rebind_identity(
        creator_id: UUID, value: IdentityUpdate, session: Session = Depends(get_session)
    ):
        result = detail(CreatorLibraryRepository(session).rebind(creator_id, value))
        session.commit()
        return result

    @router.post(
        "/{creator_id}/contacts",
        response_model=CreatorDetail,
        status_code=201,
        operation_id="addLibraryCreatorContactV2",
    )
    def add_contact(
        creator_id: UUID,
        value: ContactCreate,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        workspace: AuthenticatedWorkspace = Depends(authenticate_workspace),
        session: Session = Depends(get_session),
    ):
        return once(
            session,
            workspace,
            idempotency_key,
            f"/api/v2/library/creators/{creator_id}/contacts",
            value,
            lambda: detail(
                CreatorLibraryRepository(session).add_contact(creator_id, value)
            ),
        )

    @router.patch(
        "/{creator_id}/contacts/{contact_id}",
        response_model=CreatorDetail,
        operation_id="updateLibraryCreatorContactV2",
    )
    def patch_contact(
        creator_id: UUID,
        contact_id: UUID,
        value: ContactPatch,
        session: Session = Depends(get_session),
    ):
        result = detail(
            CreatorLibraryRepository(session).patch_contact(
                creator_id, contact_id, value
            )
        )
        session.commit()
        return result

    @router.get(
        "/{creator_id}/works",
        response_model=WorkPage,
        operation_id="listLibraryCreatorWorksV2",
    )
    def list_works(
        creator_id: UUID,
        include_previous_identity: bool = False,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        session: Session = Depends(get_session),
    ):
        return CreatorLibraryRepository(session).works(
            creator_id,
            include_previous_identity=include_previous_identity,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/{creator_id}/works",
        response_model=WorkDetail,
        status_code=201,
        operation_id="addLibraryCreatorWorkV2",
    )
    def add_work(
        creator_id: UUID,
        value: WorkCreate,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        workspace: AuthenticatedWorkspace = Depends(authenticate_workspace),
        session: Session = Depends(get_session),
    ):
        return once(
            session,
            workspace,
            idempotency_key,
            f"/api/v2/library/creators/{creator_id}/works",
            value,
            lambda: CreatorLibraryRepository(session).add_work(creator_id, value),
        )

    @router.patch(
        "/{creator_id}/works/{work_id}",
        response_model=WorkDetail,
        operation_id="updateLibraryCreatorWorkV2",
    )
    def patch_work(
        creator_id: UUID,
        work_id: UUID,
        value: WorkPatch,
        session: Session = Depends(get_session),
    ):
        result = CreatorLibraryRepository(session).patch_work(
            creator_id, work_id, value
        )
        session.commit()
        return result

    return router
