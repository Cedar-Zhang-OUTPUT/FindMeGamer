"""Explicit Activity email qualification; final-send writes are a separate action."""

from uuid import UUID
from typing import Annotated
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.core.database import get_session
from app.outreach.activity_qualification import qualify
from app.schemas.activity_sending import QualificationRequest, Qualification
from app.schemas.activity_sending import FinalSendRequest, SendBatchView, SendBatchPage
from app.schemas.activity_sending import DeliveryRetry, DeliveryView, DeliveryResolution
from app.api.routes.activity import _get, _write
from app.db.models.discovery import Activity
from app.db.models.activity_sending import ActivitySendBatch, ActivityDelivery
from app.repositories.activity_sending import (
    final_send,
    batch_view,
    retry_delivery,
    resolve_delivery,
)
from app.db.models.jobs import acquire_job_change_lock
from app.workers.activity_send_tasks import CeleryActivitySendDispatcher
from app.api.routes.activity import _error


def create_router(authenticate_workspace, *, dispatcher=None):
    dispatcher = dispatcher or CeleryActivitySendDispatcher()
    router = APIRouter(
        prefix="/api/v2",
        tags=["activity-sending"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.post(
        "/outreach/compositions/{composition_id}/qualification",
        response_model=Qualification,
        operation_id="qualifyActivityOutreachV2",
    )
    def qualification(
        composition_id: UUID,
        value: QualificationRequest,
        session: Session = Depends(get_session),
    ):
        return qualify(session, composition_id, value.excluded)

    @router.post(
        "/outreach/compositions/{composition_id}/send-batches",
        response_model=SendBatchView,
        status_code=201,
        operation_id="confirmActivityOutreachSendV2",
    )
    def confirm(
        composition_id: UUID,
        value: FinalSendRequest,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/outreach/compositions/{composition_id}/send-batches",
            payload=value.model_dump(mode="json"),
            status=201,
            operation=lambda: final_send(session, composition_id, value),
        )
        queued = session.scalars(
            select(ActivityDelivery)
            .where(
                ActivityDelivery.send_batch_id == UUID(body["id"]),
                ActivityDelivery.state == "queued",
            )
            .order_by(ActivityDelivery.input_order)
        ).all()
        for row in queued:
            dispatch(row.id)
        return JSONResponse(status_code=status, content=body)

    @router.get(
        "/outreach/send-batches/{batch_id}",
        response_model=SendBatchView,
        operation_id="getActivitySendBatchV2",
    )
    def get_batch(batch_id: UUID, session: Session = Depends(get_session)):
        return batch_view(session, _get(session, ActivitySendBatch, batch_id))

    @router.get(
        "/activities/{activity_id}/send-batches",
        response_model=SendBatchPage,
        operation_id="listActivitySendBatchesV2",
    )
    def list_batches(
        activity_id: UUID,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        _get(session, Activity, activity_id)
        condition = ActivitySendBatch.activity_id == activity_id
        rows = session.scalars(
            select(ActivitySendBatch)
            .where(condition)
            .order_by(ActivitySendBatch.created_at.desc(), ActivitySendBatch.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [batch_view(session, row) for row in rows],
            "total": session.scalar(
                select(func.count()).select_from(ActivitySendBatch).where(condition)
            ),
            "limit": limit,
            "offset": offset,
        }

    @router.post(
        "/outreach/deliveries/{delivery_id}/retry",
        response_model=DeliveryView,
        operation_id="retryActivityDeliveryV2",
    )
    def retry(
        delivery_id: UUID, value: DeliveryRetry, session: Session = Depends(get_session)
    ):
        acquire_job_change_lock(session)
        body = retry_delivery(session, delivery_id, value)
        session.commit()
        dispatch(delivery_id)
        return body

    @router.post(
        "/outreach/deliveries/{delivery_id}/resolve",
        response_model=DeliveryView,
        operation_id="resolveActivityDeliveryV2",
    )
    def resolve(
        delivery_id: UUID,
        value: DeliveryResolution,
        session: Session = Depends(get_session),
    ):
        acquire_job_change_lock(session)
        body = resolve_delivery(session, delivery_id, value)
        session.commit()
        return body

    def dispatch(identity):
        try:
            dispatcher.dispatch(identity)
        except Exception:
            raise _error(
                503,
                "send_queue_unavailable",
                "Final sending record saved. Retry the same request to dispatch existing queued recipients.",
            ) from None

    return router
