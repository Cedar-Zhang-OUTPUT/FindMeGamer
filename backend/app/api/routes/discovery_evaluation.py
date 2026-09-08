from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.activity import _error, _get, _write
from app.core.database import get_session
from app.core.errors import APIError
from app.db.models.discovery import DiscoveryCandidate, DiscoveryQuery
from app.db.models.discovery_evaluation import EvaluationRun, EvaluationItem
from app.db.models.profiles import CreatorProfile
from app.discovery.evaluation_snapshot import (
    creator_snapshot,
    digest,
    game_brief,
    game_data,
)
from app.repositories.discovery_evaluation import (
    CHUNK_SIZE,
    METHOD_VERSION,
    MODELS,
    add_step,
    expired,
    items_for,
    lock_run,
    result_rows,
    run_view,
    steps_for,
)
from app.schemas.discovery_evaluation import (
    EvaluationAccepted,
    EvaluationCreate,
    EvaluationPage,
    EvaluationResultPage,
    EvaluationRetry,
    EvaluationView,
)


class CeleryEvaluationDispatcher:
    def dispatch(self, run_id):
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            "find_me_gamer.discovery.evaluate",
            args=[str(run_id)],
            retry=False,
            ignore_result=True,
        )


def create_router(authenticate_workspace, *, dispatcher=None):
    dispatcher = dispatcher or CeleryEvaluationDispatcher()
    router = APIRouter(
        prefix="/api/v2",
        tags=["discovery-evaluation"],
        dependencies=[Depends(authenticate_workspace)],
    )

    def send(body, status):
        try:
            dispatcher.dispatch(UUID(body["evaluation_id"]))
        except Exception:
            raise APIError(
                status_code=503,
                code="evaluation_queue_unavailable",
                message="Saved, but dispatch is unavailable. Retry with the same Idempotency-Key.",
                retryable=True,
            ) from None
        return JSONResponse(status_code=status, content=body)

    @router.post(
        "/discovery/queries/{query_id}/evaluations",
        status_code=202,
        response_model=EvaluationAccepted,
        operation_id="createDiscoveryEvaluationV2",
    )
    def create_evaluation(
        query_id: UUID,
        value: EvaluationCreate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        def operation():
            query = _get(session, DiscoveryQuery, query_id)
            statement = (
                select(DiscoveryCandidate)
                .where(DiscoveryCandidate.query_id == query_id)
                .order_by(DiscoveryCandidate.ordinal)
            )
            if value.candidate_ids is not None:
                statement = statement.where(
                    DiscoveryCandidate.id.in_(value.candidate_ids)
                )
            candidates = list(session.scalars(statement))
            if (
                not candidates
                or len(candidates) > 600
                or (value.candidate_ids and len(candidates) != len(value.candidate_ids))
            ):
                raise _error(
                    422,
                    "evaluation_candidates_invalid",
                    "Choose one through 600 existing candidates from this query.",
                )
            run = EvaluationRun(
                id=uuid4(),
                query_id=query_id,
                source_snapshot=query.source_snapshot,
                conditions=query.conditions,
                game_brief=game_brief(query.source_snapshot),
                game_fingerprint=digest(game_data(query.source_snapshot)),
                method_version=METHOD_VERSION,
                models=MODELS,
            )
            session.add(run)
            session.flush()
            eligible = []
            for index, candidate in enumerate(candidates):
                creator = _get(session, CreatorProfile, candidate.creator_id)
                snapshot, fingerprint = creator_snapshot(creator, candidate.id)
                frozen_identity = {
                    "platform": candidate.platform,
                    "account_id": candidate.account_id,
                    "revision": candidate.identity_revision,
                }
                changed = snapshot["identity"] != frozen_identity
                if changed:
                    snapshot = {
                        "candidate_id": str(candidate.id),
                        "identity": frozen_identity,
                        "creator_brief": {},
                        "creator_detail": {},
                        "analysis": {},
                        "works": [],
                        "analysis_available": False,
                    }
                item = EvaluationItem(
                    id=uuid4(),
                    run_id=run.id,
                    candidate_id=candidate.id,
                    creator_id=creator.id,
                    input_order=index,
                    snapshot=snapshot,
                    fingerprint=fingerprint,
                    identity_changed=changed,
                )
                session.add(item)
                if not changed:
                    eligible.append(item.id)
            for index in range(0, len(eligible), CHUNK_SIZE):
                add_step(
                    session,
                    run.id,
                    f"screening:{index:04d}",
                    "screening",
                    eligible[index : index + CHUNK_SIZE],
                )
            session.flush()
            return {"evaluation_id": run.id, "status": run.status}

        return send(
            *_write(
                session,
                key=key,
                path=f"/api/v2/discovery/queries/{query_id}/evaluations",
                payload=value.model_dump(mode="json"),
                status=202,
                operation=operation,
            )
        )

    @router.get(
        "/discovery/queries/{query_id}/evaluations",
        response_model=EvaluationPage,
        operation_id="listDiscoveryEvaluationsV2",
    )
    def list_evaluations(
        query_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        _get(session, DiscoveryQuery, query_id)
        statement = select(EvaluationRun).where(EvaluationRun.query_id == query_id)
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = session.scalars(
            statement.order_by(EvaluationRun.created_at.desc(), EvaluationRun.id)
            .limit(limit)
            .offset(offset)
        )
        return {
            "items": [run_view(session, r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.get(
        "/discovery/evaluations/{run_id}",
        response_model=EvaluationView,
        operation_id="getDiscoveryEvaluationV2",
    )
    def get_evaluation(run_id: UUID, session: Session = Depends(get_session)):
        return run_view(session, _get(session, EvaluationRun, run_id))

    @router.get(
        "/discovery/evaluations/{run_id}/results",
        response_model=EvaluationResultPage,
        operation_id="getDiscoveryEvaluationResultsV2",
    )
    def get_results(
        run_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        run = _get(session, EvaluationRun, run_id)
        statement = select(EvaluationItem).where(EvaluationItem.run_id == run_id)
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        items = list(
            session.scalars(
                statement.order_by(
                    EvaluationItem.score.desc().nullslast(), EvaluationItem.input_order
                )
                .limit(limit)
                .offset(offset)
            )
        )
        return {
            "items": result_rows(session, run, items),
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.post(
        "/discovery/evaluations/{run_id}/retry",
        status_code=202,
        response_model=EvaluationAccepted,
        operation_id="retryDiscoveryEvaluationV2",
    )
    def retry_evaluation(
        run_id: UUID,
        value: EvaluationRetry,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        def operation():
            run = lock_run(session, run_id)
            if run is None:
                raise _error(404, "evaluation_not_found", "Evaluation not found.")
            steps = steps_for(session, run.id)
            if any(s.status == "running" and not expired(s) for s in steps):
                raise _error(
                    409,
                    "evaluation_running",
                    "Wait for active evaluation steps to finish.",
                )
            wanted = (
                set(value.step_ids)
                if value.step_ids is not None
                else {s.id for s in steps if s.status == "failed" or expired(s)}
            )
            selected = [s for s in steps if s.id in wanted]
            if len(selected) != len(wanted) or any(
                s.status != "failed" and not expired(s) for s in selected
            ):
                raise _error(
                    422,
                    "evaluation_retry_invalid",
                    "Retry only failed steps from this evaluation.",
                )
            if not selected and run.status not in {
                "queued",
                "running",
                "completed",
                "no_matches",
            }:
                raise _error(
                    409,
                    "evaluation_not_retryable",
                    "Create a new evaluation with current source identities.",
                )
            for step in selected:
                step.status, step.error_code = "pending", None
                step.lease_token, step.lease_expires_at = None, None
            if selected or run.status in {"queued", "running"}:
                run.status = "queued"
            session.flush()
            return {"evaluation_id": run.id, "status": run.status}

        return send(
            *_write(
                session,
                key=key,
                path=f"/api/v2/discovery/evaluations/{run_id}/retry",
                payload=value.model_dump(mode="json"),
                status=202,
                operation=operation,
            )
        )

    return router
