"""Authenticated Activity endpoints. Provider execution happens only in workers."""

import hashlib
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.errors import APIError
from app.core.idempotency import (
    IDEMPOTENCY_RETENTION,
    request_hash,
    utc_now,
    validate_idempotency_key,
)
from app.db.models.discovery import (
    Activity,
    DiscoveryQuery,
    DiscoveryBatch,
    DiscoveryAttempt,
)
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import acquire_job_change_lock
from app.db.models.profiles import GameProfile
from app.repositories.discovery import DiscoveryConflict, start_batch, stop_query
from app.repositories.library_v2 import game_detail
from app.schemas.activity import (
    ActivityCreate,
    QueryCreate,
    ContinueDiscovery,
    ActivityView,
    ActivityPage,
    ActivityDetail,
    QueryView,
    DiscoveryAccepted,
    DiscoveryStopped,
    CandidatePage,
    CandidateEvidence,
    CandidateSort,
)


class CeleryDiscoveryDispatcher:
    def dispatch(self, batch_id: UUID):
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            "find_me_gamer.discovery.run_batch",
            args=[str(batch_id)],
            retry=False,
            ignore_result=True,
        )


def _error(status, code, message):
    return APIError(status_code=status, code=code, message=message)


def _get(session, model, identity):
    item = session.get(model, identity)
    if item is None:
        raise _error(404, "discovery_not_found", "The requested item was not found.")
    return item


def _activity(item):
    return {
        "id": item.id,
        "game_id": item.game_id,
        "name": item.name,
        "source_snapshot": item.source_snapshot,
        "created_at": item.created_at,
    }


def _batch(item):
    return {
        key: getattr(item, key)
        for key in (
            "id",
            "query_id",
            "ordinal",
            "status",
            "target_count",
            "initial_result_count",
            "requests_reserved",
            "scanned_reserved",
            "reason",
            "created_at",
        )
    }


def _query(session, item):
    batches = session.scalars(
        select(DiscoveryBatch)
        .where(DiscoveryBatch.query_id == item.id)
        .order_by(DiscoveryBatch.ordinal)
    ).all()
    sources = {
        platform: {key: value for key, value in state.items() if key != "cursor"}
        for platform, state in (item.provider_states or {}).items()
    }
    attempts = session.scalars(
        select(DiscoveryAttempt)
        .join(DiscoveryBatch)
        .where(DiscoveryBatch.query_id == item.id)
    ).all()
    requires_acknowledgement = any(
        a.status == "outcome_unknown"
        or (a.status == "in_flight" and a.lease_expires_at <= utc_now())
        for a in attempts
    )
    usage = {
        "requests_used": sum(
            (a.outcome or {}).get("requests_used", 0) for a in attempts
        ),
        "provider_items_received": sum(
            (a.outcome or {}).get("provider_items_received", 0) for a in attempts
        ),
        "unknown_requests_reserved": sum(
            a.requests_reserved
            for a in attempts
            if a.status in {"in_flight", "outcome_unknown", "acknowledged_unknown"}
        ),
    }
    return {
        "id": item.id,
        "activity_id": item.activity_id,
        "conditions": item.conditions,
        "source_snapshot": item.source_snapshot,
        "status": "outcome_unknown" if requires_acknowledgement else item.status,
        "requires_acknowledgement": requires_acknowledgement,
        "stop_requested": item.stop_requested,
        "result_count": item.result_count,
        "requests_reserved": item.requests_reserved,
        "scanned_reserved": item.scanned_reserved,
        "sources": sources,
        "batches": [_batch(b) for b in batches],
        "usage": usage,
        "created_at": item.created_at,
    }


def _write(session, *, key, path, payload, status, operation):
    try:
        validate_idempotency_key(key)
    except ValueError:
        raise _error(
            422, "request_invalid", "A valid Idempotency-Key is required."
        ) from None
    acquire_job_change_lock(session)
    # This app has one shared database/workspace. New Activity writes use a
    # database-scoped namespace; access-key rotation does not create a new tenant.
    record_key = "activity:" + hashlib.sha256(path.encode()).hexdigest() + ":" + key
    digest = request_hash(method="POST", path=path, canonical_request=payload)
    old = session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.key == record_key)
    )
    now = utc_now()
    if old and old.expires_at and old.expires_at <= now:
        session.delete(old)
        session.flush()
        old = None
    if old:
        if old.request_hash != digest:
            raise _error(
                409,
                "idempotency_key_conflict",
                "This key was used for another request.",
            )
        body, status = old.response_body, old.response_status
    else:
        body = jsonable_encoder(operation())
        session.add(
            IdempotencyRecord(
                key=record_key,
                request_hash=digest,
                method="POST",
                path=path,
                response_status=status,
                response_body=body,
                expires_at=now + IDEMPOTENCY_RETENTION,
            )
        )
    session.commit()
    return body, status


def create_router(authenticate_workspace, *, dispatcher=None):
    dispatcher = dispatcher or CeleryDiscoveryDispatcher()
    router = APIRouter(
        prefix="/api/v2",
        tags=["activities-discovery"],
        dependencies=[Depends(authenticate_workspace)],
    )

    def send(body, status):
        if body.get("batch_id"):
            try:
                dispatcher.dispatch(UUID(body["batch_id"]))
            except Exception:
                raise APIError(
                    status_code=503,
                    code="discovery_queue_unavailable",
                    message="Saved, but dispatch is unavailable. Retry with the same Idempotency-Key.",
                    retryable=True,
                ) from None
        return JSONResponse(status_code=status, content=body)

    @router.post(
        "/activities",
        status_code=201,
        response_model=ActivityView,
        operation_id="createActivityV2",
    )
    def create_activity(
        value: ActivityCreate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        def operation():
            game = _get(session, GameProfile, value.game_id)
            detail = game_detail(game).model_dump(mode="json")
            references = {str(r["id"]): r for r in detail["reference_works"]}
            wanted = list(dict.fromkeys(str(i) for i in value.reference_work_ids))
            if any(i not in references for i in wanted):
                raise _error(
                    422,
                    "activity_reference_invalid",
                    "Select references belonging to this game.",
                )
            item = Activity(
                id=uuid4(),
                game_id=game.id,
                name=value.name,
                source_snapshot={
                    "game": detail,
                    "references": [references[i] for i in wanted],
                },
            )
            session.add(item)
            session.flush()
            return _activity(item)

        body, status = _write(
            session,
            key=key,
            path="/api/v2/activities",
            payload=value.model_dump(mode="json"),
            status=201,
            operation=operation,
        )
        return send(body, status)

    @router.get(
        "/activities", response_model=ActivityPage, operation_id="listActivitiesV2"
    )
    def list_activities(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        session: Session = Depends(get_session),
    ):
        items = session.scalars(
            select(Activity)
            .order_by(Activity.created_at.desc(), Activity.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [_activity(i) for i in items],
            "total": session.scalar(select(func.count()).select_from(Activity)),
            "limit": limit,
            "offset": offset,
        }

    @router.get(
        "/activities/{activity_id}",
        response_model=ActivityDetail,
        operation_id="getActivityV2",
    )
    def get_activity(activity_id: UUID, session: Session = Depends(get_session)):
        item = _get(session, Activity, activity_id)
        queries = session.scalars(
            select(DiscoveryQuery)
            .where(DiscoveryQuery.activity_id == item.id)
            .order_by(DiscoveryQuery.created_at, DiscoveryQuery.id)
        ).all()
        return _activity(item) | {"queries": [_query(session, q) for q in queries]}

    @router.post(
        "/activities/{activity_id}/queries",
        status_code=202,
        response_model=DiscoveryAccepted,
        operation_id="createDiscoveryQueryV2",
    )
    def create_query(
        activity_id: UUID,
        value: QueryCreate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        def operation():
            activity = _get(session, Activity, activity_id)
            item = DiscoveryQuery(
                id=uuid4(),
                activity_id=activity.id,
                conditions=value.model_dump(mode="json"),
                source_snapshot=activity.source_snapshot,
            )
            session.add(item)
            session.flush()
            batch = start_batch(session, item)
            session.flush()
            return {"query_id": item.id, "batch_id": batch.id, "status": item.status}

        try:
            body, status = _write(
                session,
                key=key,
                path=f"/api/v2/activities/{activity_id}/queries",
                payload=value.model_dump(mode="json"),
                status=202,
                operation=operation,
            )
        except DiscoveryConflict:
            raise _error(
                409, "discovery_not_runnable", "This query cannot be started."
            ) from None
        return send(body, status)

    @router.get(
        "/discovery/queries/{query_id}",
        response_model=QueryView,
        operation_id="getDiscoveryQueryV2",
    )
    def get_query(query_id: UUID, session: Session = Depends(get_session)):
        return _query(session, _get(session, DiscoveryQuery, query_id))

    @router.post(
        "/discovery/queries/{query_id}/continue",
        status_code=202,
        response_model=DiscoveryAccepted,
        operation_id="continueDiscoveryV2",
    )
    def continue_query(
        query_id: UUID,
        value: ContinueDiscovery,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        def operation():
            item = _get(session, DiscoveryQuery, query_id)
            batch = start_batch(
                session, item, acknowledge_unknown=value.acknowledge_unknown
            )
            session.flush()
            return {"query_id": item.id, "batch_id": batch.id, "status": item.status}

        try:
            body, status = _write(
                session,
                key=key,
                path=f"/api/v2/discovery/queries/{query_id}/continue",
                payload=value.model_dump(mode="json"),
                status=202,
                operation=operation,
            )
        except DiscoveryConflict as error:
            raise _error(
                409,
                "discovery_not_runnable",
                "Discovery is active, exhausted, or requires acknowledgement of an unknown request outcome.",
            ) from None
        return send(body, status)

    @router.post(
        "/discovery/queries/{query_id}/stop",
        response_model=DiscoveryStopped,
        operation_id="stopDiscoveryV2",
    )
    def stop(
        query_id: UUID,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        def operation():
            item = _get(session, DiscoveryQuery, query_id)
            stop_query(session, item)
            return {
                "query_id": item.id,
                "status": item.status,
                "stop_requested": item.stop_requested,
            }

        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/discovery/queries/{query_id}/stop",
            payload={},
            status=200,
            operation=operation,
        )
        return send(body, status)

    @router.get(
        "/discovery/queries/{query_id}/results",
        response_model=CandidatePage,
        operation_id="getDiscoveryResultsV2",
    )
    def results(
        query_id: UUID,
        evidence: CandidateEvidence = "all",
        sort: CandidateSort = "added",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        session: Session = Depends(get_session),
    ):
        from app.repositories.candidate_queries import candidate_page

        query = _get(session, DiscoveryQuery, query_id)
        return candidate_page(
            session, query, evidence=evidence, sort=sort, limit=limit, offset=offset
        )

    return router
