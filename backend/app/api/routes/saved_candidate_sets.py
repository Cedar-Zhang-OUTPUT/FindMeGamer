"""Named-set restoration is read-only, never a discovery or selection action."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.activity import _get, _write
from app.core.database import get_session
from app.db.models.discovery import Activity, DiscoveryQuery
from app.db.models.saved_candidate_set import SavedCandidateSet
from app.repositories.candidate_queries import candidate_page
from app.repositories.saved_candidate_sets import metadata, save
from app.schemas.activity import CandidateEvidence, CandidateSort, CandidatePage
from app.schemas.saved_candidate_set import SavedSetCreate, SavedSetView, SavedSetPage


def create_router(authenticate_workspace):
    router = APIRouter(
        prefix="/api/v2",
        tags=["saved-candidate-sets"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.post(
        "/discovery/queries/{query_id}/saved-sets",
        status_code=201,
        response_model=SavedSetView,
        operation_id="saveCandidateSetV2",
    )
    def create(
        query_id: UUID,
        value: SavedSetCreate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/discovery/queries/{query_id}/saved-sets",
            payload=value.model_dump(mode="json"),
            status=201,
            operation=lambda: save(session, query_id, value),
        )
        return JSONResponse(status_code=status, content=body)

    @router.get(
        "/activities/{activity_id}/saved-sets",
        response_model=SavedSetPage,
        operation_id="listCandidateSetsV2",
    )
    def list_sets(
        activity_id: UUID,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        session: Session = Depends(get_session),
    ):
        _get(session, Activity, activity_id)
        statement = (
            select(SavedCandidateSet, DiscoveryQuery)
            .join(DiscoveryQuery, SavedCandidateSet.query_id == DiscoveryQuery.id)
            .where(DiscoveryQuery.activity_id == activity_id)
        )
        rows = session.execute(
            statement.order_by(
                SavedCandidateSet.created_at.desc(), SavedCandidateSet.id
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [metadata(item, query) for item, query in rows],
            "total": session.scalar(
                select(func.count()).select_from(statement.subquery())
            ),
            "limit": limit,
            "offset": offset,
        }

    @router.get(
        "/discovery/saved-sets/{set_id}",
        response_model=SavedSetView,
        operation_id="getCandidateSetV2",
    )
    def get_set(set_id: UUID, session: Session = Depends(get_session)):
        item = _get(session, SavedCandidateSet, set_id)
        return metadata(item, _get(session, DiscoveryQuery, item.query_id))

    @router.get(
        "/discovery/saved-sets/{set_id}/results",
        response_model=CandidatePage,
        operation_id="getCandidateSetResultsV2",
    )
    def results(
        set_id: UUID,
        evidence: CandidateEvidence = "all",
        sort: CandidateSort = "added",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        session: Session = Depends(get_session),
    ):
        item = _get(session, SavedCandidateSet, set_id)
        query = _get(session, DiscoveryQuery, item.query_id)
        return candidate_page(
            session,
            query,
            evidence=evidence,
            sort=sort,
            limit=limit,
            offset=offset,
            candidate_ids=[UUID(i) for i in item.candidate_ids],
        )

    return router
