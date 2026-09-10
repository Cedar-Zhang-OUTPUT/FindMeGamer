from typing import Annotated
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from app.api.routes.activity import _get, _error, _write
from app.core.database import get_session
from app.core.errors import APIError
from app.db.models.creator_search import CreatorSearch, CreatorSearchUnit
from app.db.models.discovery import Activity, DiscoveryCandidate, DiscoveryQuery
from app.db.models.discovery_plan import DiscoveryPlan
from app.discovery.activity_context import activity_context
from app.repositories.creator_search import (
    ACTIVE,
    lock_search,
    search_expired,
    search_view,
    unit_view,
    units_for,
)
from app.schemas.creator_search import (
    CreatorSearchCreate,
    CreatorSearchRetry,
    CreatorSearchEmpty,
    CreatorSearchAccepted,
    CreatorSearchView,
    CreatorSearchPage,
    CreatorSearchUnitPage,
)


def dispatch_search(identity):
    from app.workers.celery_app import celery_app

    celery_app.send_task(
        "find_me_gamer.creator_search.run",
        args=[str(identity)],
        retry=False,
        ignore_result=True,
    )


def create_router(authenticate_workspace):
    router = APIRouter(
        prefix="/api/v2",
        tags=["creator-search"],
        dependencies=[Depends(authenticate_workspace)],
    )

    def send(request, body, status):
        try:
            getattr(request.app.state, "creator_search_dispatch", dispatch_search)(
                UUID(body["search_id"])
            )
        except Exception:
            raise APIError(
                status_code=503,
                code="search_queue_unavailable",
                message="Saved, but dispatch is unavailable. Retry with the same Idempotency-Key.",
                retryable=True,
            ) from None
        return JSONResponse(status_code=status, content=body)

    @router.post(
        "/activities/{activity_id}/creator-searches",
        status_code=202,
        response_model=CreatorSearchAccepted,
    )
    def create(
        activity_id: UUID,
        value: CreatorSearchCreate,
        request: Request,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session=Depends(get_session),
    ):
        def operation():
            activity = _get(session, Activity, activity_id)
            if session.scalar(
                select(CreatorSearch.id)
                .where(
                    CreatorSearch.activity_id == activity_id,
                    CreatorSearch.status.in_(ACTIVE),
                )
                .limit(1)
            ):
                raise _error(
                    409,
                    "search_running",
                    "Wait for or stop the current search before starting another.",
                )
            plan = DiscoveryPlan(
                id=uuid4(),
                activity_id=activity_id,
                source_snapshot=activity_context(activity),
                conditions=value.model_dump(mode="json"),
                model="deepseek-v4-flash",
            )
            session.add(plan)
            session.flush()
            task = CreatorSearch(id=uuid4(), activity_id=activity_id, plan_id=plan.id)
            session.add(task)
            session.flush()
            return {"search_id": task.id, "status": task.status}

        return send(
            request,
            *_write(
                session,
                key=key,
                path=f"/api/v2/activities/{activity_id}/creator-searches",
                payload=value.model_dump(mode="json"),
                status=202,
                operation=operation,
            ),
        )

    @router.get(
        "/activities/{activity_id}/creator-searches", response_model=CreatorSearchPage
    )
    def listing(
        activity_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session=Depends(get_session),
    ):
        _get(session, Activity, activity_id)
        statement = select(CreatorSearch).where(
            CreatorSearch.activity_id == activity_id
        )
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = session.scalars(
            statement.order_by(CreatorSearch.created_at.desc(), CreatorSearch.id)
            .offset(offset)
            .limit(limit)
        )
        return {
            "items": [search_view(session, row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.get("/creator-searches/{identity}", response_model=CreatorSearchView)
    def detail(identity: UUID, session=Depends(get_session)):
        return search_view(session, _get(session, CreatorSearch, identity))

    @router.get(
        "/creator-searches/{identity}/creators", response_model=CreatorSearchUnitPage
    )
    def creators(
        identity: UUID,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session=Depends(get_session),
    ):
        _get(session, CreatorSearch, identity)
        rows = units_for(session, identity)
        return {
            "items": [unit_view(row) for row in rows[offset : offset + limit]],
            "total": len(rows),
            "limit": limit,
            "offset": offset,
        }

    @router.post(
        "/creator-searches/{identity}/stop",
        status_code=202,
        response_model=CreatorSearchAccepted,
    )
    def stop(
        identity: UUID,
        value: CreatorSearchEmpty,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session=Depends(get_session),
    ):
        def operation():
            task = lock_search(session, identity)
            if task is None:
                raise _error(404, "search_not_found", "Search not found.")
            if task.status in ACTIVE:
                task.stop_requested = True
                task.status = "stopping" if task.lease_token else "stopped"
                if task.query_id and task.stage == "discovery":
                    session.get(DiscoveryQuery, task.query_id).stop_requested = True
            return {"search_id": task.id, "status": task.status}

        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/creator-searches/{identity}/stop",
            payload={},
            status=202,
            operation=operation,
        )
        return JSONResponse(status_code=status, content=body)

    @router.post(
        "/creator-searches/{identity}/retry",
        status_code=202,
        response_model=CreatorSearchAccepted,
    )
    def retry(
        identity: UUID,
        value: CreatorSearchRetry,
        request: Request,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session=Depends(get_session),
    ):
        def operation():
            task = lock_search(session, identity)
            if task is None:
                raise _error(404, "search_not_found", "Search not found.")
            view = search_view(session, task)
            if task.status == "queued":
                return {"search_id": task.id, "status": task.status}
            if not view["retryable"] or (
                task.status in ACTIVE and not search_expired(task)
            ):
                raise _error(
                    409,
                    "search_not_retryable",
                    "Wait for current work or retry a failed/stopped search.",
                )
            if view["outcome_unknown"] and not value.acknowledge_unknown:
                raise _error(
                    409,
                    "search_outcome_unknown",
                    "An interrupted call may have incurred a charge. Acknowledge before retrying.",
                )
            # Worker reconciles linked completed jobs before retrying failed units.
            task.status = "queued"
            task.stop_requested = False
            task.error_code = None
            task.acknowledge_unknown = value.acknowledge_unknown
            task.lease_token = None
            task.lease_expires_at = None
            return {"search_id": task.id, "status": task.status}

        return send(
            request,
            *_write(
                session,
                key=key,
                path=f"/api/v2/creator-searches/{identity}/retry",
                payload=value.model_dump(mode="json"),
                status=202,
                operation=operation,
            ),
        )

    @router.post(
        "/creator-searches/{identity}/append",
        status_code=202,
        response_model=CreatorSearchAccepted,
    )
    def append(
        identity: UUID,
        value: CreatorSearchEmpty,
        request: Request,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session=Depends(get_session),
    ):
        def operation():
            parent = lock_search(session, identity)
            if parent is None:
                raise _error(404, "search_not_found", "Search not found.")
            if not parent.query_id or parent.status in ACTIVE:
                raise _error(
                    409,
                    "search_running",
                    "Wait for this batch before appending an independent batch.",
                )
            if session.scalar(
                select(CreatorSearch.id)
                .where(
                    CreatorSearch.query_id == parent.query_id,
                    CreatorSearch.status.in_(ACTIVE),
                )
                .limit(1)
            ):
                raise _error(
                    409, "search_running", "Another batch for this query is active."
                )
            excluded = [
                str(i)
                for i in session.scalars(
                    select(DiscoveryCandidate.id).where(
                        DiscoveryCandidate.query_id == parent.query_id
                    )
                )
            ]
            task = CreatorSearch(
                id=uuid4(),
                activity_id=parent.activity_id,
                plan_id=parent.plan_id,
                query_id=parent.query_id,
                parent_search_id=parent.id,
                stage="discovery",
                excluded_candidate_ids=excluded,
                acknowledge_unknown=parent.acknowledge_unknown,
            )
            session.add(task)
            session.flush()
            return {"search_id": task.id, "status": task.status}

        return send(
            request,
            *_write(
                session,
                key=key,
                path=f"/api/v2/creator-searches/{identity}/append",
                payload={},
                status=202,
                operation=operation,
            ),
        )

    return router
