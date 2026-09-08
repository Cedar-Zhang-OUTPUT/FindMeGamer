"""Human Activity preparation; these endpoints never dispatch jobs or email."""

from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.routes.activity import _get, _write as write_once
from app.core.database import get_session
from app.db.models.discovery import Activity
from app.db.models.activity_outreach import ActivitySelection, RecipientBatch
from app.repositories.activity_preparation import (
    add_selection,
    get_selection,
    preparation,
    update_selection,
    cancel_selection,
)
from app.schemas.activity_outreach import (
    SelectionCreate,
    Preparation,
    SelectionPage,
    SelectionUpdate,
    SelectionRevision,
)
from app.schemas.activity_outreach import (
    RecipientBatchCreate,
    RecipientBatchDetail,
    RecipientBatchPage,
)
from app.repositories.recipient_batches import (
    freeze_batch,
    batch_detail,
    batch_summary,
    get_batch,
)
from app.repositories.activity_preparation import bulk_selection
from app.schemas.activity_outreach import SelectionBulkChange, SelectionBulkResult


def _write(session, *, operation, **kwargs):
    # Keep a rejected multi-member edit atomic even when the session is reused
    # by a caller. The outer v2 helper owns locking, idempotency and final commit.
    def atomic_operation():
        with session.begin_nested():
            return operation()

    return write_once(session, operation=atomic_operation, **kwargs)


def create_router(authenticate_workspace):
    router = APIRouter(
        prefix="/api/v2/activities/{activity_id}",
        tags=["activity-outreach"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.post(
        "/selections",
        status_code=201,
        response_model=Preparation,
        operation_id="addActivitySelectionV2",
    )
    def create(
        activity_id: UUID,
        value: SelectionCreate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/activities/{activity_id}/selections",
            payload=value.model_dump(mode="json"),
            status=201,
            operation=lambda: add_selection(session, activity_id, value.candidate_id),
        )
        return JSONResponse(status_code=status, content=body)

    @router.get(
        "/selections",
        response_model=SelectionPage,
        operation_id="listActivitySelectionsV2",
    )
    def listing(
        activity_id: UUID,
        include_cancelled: bool = False,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        _get(session, Activity, activity_id)
        statement = select(ActivitySelection).where(
            ActivitySelection.activity_id == activity_id
        )
        if not include_cancelled:
            statement = statement.where(ActivitySelection.active.is_(True))
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = session.scalars(
            statement.order_by(ActivitySelection.created_at, ActivitySelection.id)
            .offset(offset)
            .limit(limit)
        )
        return {
            "items": [preparation(session, r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.post(
        "/selections/bulk",
        response_model=SelectionBulkResult,
        operation_id="bulkActivitySelectionsV2",
    )
    def bulk(
        activity_id: UUID,
        value: SelectionBulkChange,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/activities/{activity_id}/selections/bulk",
            payload=value.model_dump(mode="json"),
            status=200,
            operation=lambda: bulk_selection(session, activity_id, value),
        )
        return JSONResponse(status_code=status, content=body)

    @router.get(
        "/selections/{selection_id}",
        response_model=Preparation,
        operation_id="getActivitySelectionV2",
    )
    def get(
        activity_id: UUID, selection_id: UUID, session: Session = Depends(get_session)
    ):
        return preparation(session, get_selection(session, activity_id, selection_id))

    @router.post(
        "/selections/{selection_id}/update",
        response_model=Preparation,
        operation_id="updateActivitySelectionV2",
    )
    def update(
        activity_id: UUID,
        selection_id: UUID,
        value: SelectionUpdate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/activities/{activity_id}/selections/{selection_id}/update",
            payload=value.model_dump(mode="json", exclude_unset=True),
            status=200,
            operation=lambda: update_selection(
                session, get_selection(session, activity_id, selection_id), value
            ),
        )
        return JSONResponse(status_code=status, content=body)

    @router.post(
        "/selections/{selection_id}/cancel",
        response_model=Preparation,
        operation_id="cancelActivitySelectionV2",
    )
    def cancel(
        activity_id: UUID,
        selection_id: UUID,
        value: SelectionRevision,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/activities/{activity_id}/selections/{selection_id}/cancel",
            payload=value.model_dump(mode="json"),
            status=200,
            operation=lambda: cancel_selection(
                session, get_selection(session, activity_id, selection_id), value
            ),
        )
        return JSONResponse(status_code=status, content=body)

    @router.post(
        "/recipient-batches",
        status_code=201,
        response_model=RecipientBatchDetail,
        operation_id="createActivityRecipientBatchV2",
    )
    def freeze(
        activity_id: UUID,
        value: RecipientBatchCreate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/activities/{activity_id}/recipient-batches",
            payload=value.model_dump(mode="json"),
            status=201,
            operation=lambda: freeze_batch(session, activity_id, value),
        )
        return JSONResponse(status_code=status, content=body)

    @router.get(
        "/recipient-batches",
        response_model=RecipientBatchPage,
        operation_id="listActivityRecipientBatchesV2",
    )
    def batches(
        activity_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        _get(session, Activity, activity_id)
        statement = select(RecipientBatch).where(
            RecipientBatch.activity_id == activity_id
        )
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = session.scalars(
            statement.order_by(RecipientBatch.created_at.desc(), RecipientBatch.id)
            .offset(offset)
            .limit(limit)
        )
        return {
            "items": [batch_summary(session, r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.get(
        "/recipient-batches/{batch_id}",
        response_model=RecipientBatchDetail,
        operation_id="getActivityRecipientBatchV2",
    )
    def batch(
        activity_id: UUID, batch_id: UUID, session: Session = Depends(get_session)
    ):
        return batch_detail(session, get_batch(session, activity_id, batch_id))

    return router
