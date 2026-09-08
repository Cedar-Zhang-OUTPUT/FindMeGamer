from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.activity import _error, _get, _write
from app.core.database import get_session
from app.core.errors import APIError
from app.db.models.discovery import Activity
from app.db.models.discovery_plan import DiscoveryPlan
from app.repositories.discovery_plan import expired, lock_plan, plan_view
from app.schemas.discovery_planning import PlanAccepted, PlanCreate, PlanPage, PlanView

PLANNING_MODEL = "deepseek-v4-flash"


class CeleryPlanningDispatcher:
    def dispatch(self, plan_id):
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            "find_me_gamer.discovery.plan",
            args=[str(plan_id)],
            retry=False,
            ignore_result=True,
        )


def create_router(authenticate_workspace, *, dispatcher=None):
    dispatcher = dispatcher or CeleryPlanningDispatcher()
    router = APIRouter(
        prefix="/api/v2",
        tags=["discovery-planning"],
        dependencies=[Depends(authenticate_workspace)],
    )

    def send(body, status):
        try:
            dispatcher.dispatch(UUID(body["plan_id"]))
        except Exception:
            raise APIError(
                status_code=503,
                code="planning_queue_unavailable",
                message="Saved, but dispatch is unavailable. Retry with the same Idempotency-Key.",
                retryable=True,
            ) from None
        return JSONResponse(status_code=status, content=body)

    @router.post(
        "/activities/{activity_id}/discovery-plans",
        status_code=202,
        response_model=PlanAccepted,
        operation_id="createDiscoveryPlanV2",
    )
    def create_plan(
        activity_id: UUID,
        value: PlanCreate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        def operation():
            activity = _get(session, Activity, activity_id)
            plan = DiscoveryPlan(
                id=uuid4(),
                activity_id=activity.id,
                source_snapshot=activity.source_snapshot,
                conditions=value.model_dump(mode="json"),
                model=PLANNING_MODEL,
            )
            session.add(plan)
            session.flush()
            return {"plan_id": plan.id, "status": plan.status}

        return send(
            *_write(
                session,
                key=key,
                path=f"/api/v2/activities/{activity_id}/discovery-plans",
                payload=value.model_dump(mode="json"),
                status=202,
                operation=operation,
            )
        )

    @router.get(
        "/activities/{activity_id}/discovery-plans",
        response_model=PlanPage,
        operation_id="listDiscoveryPlansV2",
    )
    def list_plans(
        activity_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        _get(session, Activity, activity_id)
        statement = select(DiscoveryPlan).where(
            DiscoveryPlan.activity_id == activity_id
        )
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = session.scalars(
            statement.order_by(DiscoveryPlan.created_at.desc(), DiscoveryPlan.id)
            .limit(limit)
            .offset(offset)
        )
        return {
            "items": [plan_view(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.get(
        "/discovery/plans/{plan_id}",
        response_model=PlanView,
        operation_id="getDiscoveryPlanV2",
    )
    def get_plan(plan_id: UUID, session: Session = Depends(get_session)):
        return plan_view(_get(session, DiscoveryPlan, plan_id))

    @router.post(
        "/discovery/plans/{plan_id}/retry",
        status_code=202,
        response_model=PlanAccepted,
        operation_id="retryDiscoveryPlanV2",
    )
    def retry_plan(
        plan_id: UUID,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        def operation():
            plan = lock_plan(session, plan_id)
            if plan is None:
                raise _error(
                    404, "discovery_not_found", "The requested plan was not found."
                )
            if plan.status in {"ready", "queued"}:
                return {"plan_id": plan.id, "status": plan.status}
            if not expired(plan) and (plan.status != "failed" or not plan.retryable):
                raise _error(
                    409,
                    "planning_not_retryable",
                    "Wait for this plan or submit corrected input as a new plan.",
                )
            plan.status, plan.error_code, plan.retryable = "queued", None, False
            plan.lease_token, plan.lease_expires_at = None, None
            session.flush()
            return {"plan_id": plan.id, "status": plan.status}

        return send(
            *_write(
                session,
                key=key,
                path=f"/api/v2/discovery/plans/{plan_id}/retry",
                payload={},
                status=202,
                operation=operation,
            )
        )

    return router
