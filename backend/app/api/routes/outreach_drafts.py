"""New locked-template preparation; no SMTP sending authority."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.routes.activity import _get, _write, _error
from app.core.database import get_session
from app.db.models.outreach_drafts import OutreachTemplateVersion
from app.db.models.profiles import GameProfile
from app.repositories.outreach_templates_v2 import (
    builtin,
    register_canonical,
    create_version,
    template_view,
)
from app.schemas.outreach_drafts import (
    CanonicalRegistration,
    TemplateVersionCreate,
    TemplateVersionView,
    TemplateCatalog,
)
from app.schemas.outreach_drafts import (
    CompositionCreate,
    CompositionView,
    CompositionPage,
    DraftView,
    DraftEdit,
    DraftRevision,
    SenderFacts,
)
from app.db.models.outreach_drafts import OutreachComposition, OutreachDraft
from app.db.models.discovery import Activity
from app.db.models.jobs import acquire_job_change_lock
from app.repositories import outreach_drafts as drafts
from app.workers.outreach_draft_tasks import CeleryDraftDispatcher


def create_router(authenticate_workspace, *, dispatcher=None):
    dispatcher = dispatcher or CeleryDraftDispatcher()
    router = APIRouter(
        prefix="/api/v2",
        tags=["outreach-drafts"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get(
        "/outreach/template-versions",
        response_model=TemplateCatalog,
        operation_id="listOutreachTemplateVersionsV2",
    )
    def templates(game_id: UUID | None = None, session: Session = Depends(get_session)):
        statement = select(OutreachTemplateVersion)
        if game_id is not None:
            _get(session, GameProfile, game_id)
            statement = statement.where(OutreachTemplateVersion.game_id == game_id)
        items = session.scalars(
            statement.order_by(
                OutreachTemplateVersion.created_at, OutreachTemplateVersion.id
            )
        ).all()
        from app.repositories.outreach_templates_v2 import game_builtin

        return {
            "items": [template_view(item) for item in items],
            "builtin": (
                game_builtin(session, _get(session, GameProfile, game_id))
                if game_id is not None
                else None
            ),
        }

    @router.post(
        "/outreach/template-versions/canonical",
        response_model=TemplateVersionView,
        status_code=201,
        operation_id="registerCanonicalOutreachTemplateV2",
    )
    def canonical(
        value: CanonicalRegistration,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path="/api/v2/outreach/template-versions/canonical",
            payload=value.model_dump(mode="json"),
            status=201,
            operation=lambda: register_canonical(session, value.game_id),
        )
        return JSONResponse(status_code=status, content=body)

    @router.post(
        "/outreach/template-versions",
        response_model=TemplateVersionView,
        status_code=201,
        operation_id="createOutreachTemplateVersionV2",
    )
    def create(
        value: TemplateVersionCreate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path="/api/v2/outreach/template-versions",
            payload=value.model_dump(mode="json"),
            status=201,
            operation=lambda: create_version(session, value),
        )
        return JSONResponse(status_code=status, content=body)

    @router.get(
        "/outreach/template-versions/{version_id}",
        response_model=TemplateVersionView,
        operation_id="getOutreachTemplateVersionV2",
    )
    def get(version_id: UUID, session: Session = Depends(get_session)):
        return template_view(_get(session, OutreachTemplateVersion, version_id))

    @router.post(
        "/activities/{activity_id}/compositions",
        response_model=CompositionView,
        status_code=201,
        operation_id="createOutreachCompositionV2",
    )
    def compose(
        activity_id: UUID,
        value: CompositionCreate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/activities/{activity_id}/compositions",
            payload=value.model_dump(mode="json"),
            status=201,
            operation=lambda: drafts.create_composition(session, activity_id, value),
        )
        pending = session.scalars(
            select(OutreachDraft)
            .where(
                OutreachDraft.composition_id == UUID(body["id"]),
                OutreachDraft.status == "pending",
            )
            .order_by(OutreachDraft.input_order)
        ).all()
        for row in pending:
            dispatch(row.id)
        return JSONResponse(status_code=status, content=body)

    @router.get(
        "/activities/{activity_id}/compositions",
        response_model=CompositionPage,
        operation_id="listOutreachCompositionsV2",
    )
    def compositions(
        activity_id: UUID,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        _get(session, Activity, activity_id)
        condition = OutreachComposition.activity_id == activity_id
        rows = session.scalars(
            select(OutreachComposition)
            .where(condition)
            .order_by(OutreachComposition.created_at.desc(), OutreachComposition.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [drafts.composition_view(session, row) for row in rows],
            "total": session.scalar(
                select(func.count()).select_from(OutreachComposition).where(condition)
            ),
            "limit": limit,
            "offset": offset,
        }

    @router.get(
        "/outreach/compositions/{composition_id}",
        response_model=CompositionView,
        operation_id="getOutreachCompositionV2",
    )
    def composition(composition_id: UUID, session: Session = Depends(get_session)):
        return drafts.composition_view(
            session, _get(session, OutreachComposition, composition_id)
        )

    def mutate(session, draft_id, value, operation):
        acquire_job_change_lock(session)
        row = session.scalar(
            select(OutreachDraft).where(OutreachDraft.id == draft_id).with_for_update()
        )
        if row is None:
            row = _get(session, OutreachDraft, draft_id)
        body = operation(session, row, value)
        session.commit()
        return body

    @router.patch(
        "/outreach/drafts/{draft_id}",
        response_model=DraftView,
        operation_id="editOutreachDraftV2",
    )
    def edit(draft_id: UUID, value: DraftEdit, session: Session = Depends(get_session)):
        return mutate(session, draft_id, value, drafts.edit_draft)

    @router.post(
        "/outreach/drafts/{draft_id}/refresh",
        response_model=DraftView,
        operation_id="refreshOutreachDraftV2",
    )
    def refresh(
        draft_id: UUID, value: DraftRevision, session: Session = Depends(get_session)
    ):
        body = mutate(session, draft_id, value, drafts.refresh_draft)
        if body["status"] == "pending":
            dispatch(draft_id)
        return body

    def dispatch(identity):
        try:
            dispatcher.dispatch(identity)
        except Exception:
            raise _error(
                503,
                "draft_queue_unavailable",
                "Draft saved, but the queue is temporarily unavailable. Retry dispatch.",
            ) from None

    @router.post(
        "/outreach/drafts/{draft_id}/retry",
        response_model=DraftView,
        operation_id="retryOutreachDraftV2",
    )
    def retry(
        draft_id: UUID, value: DraftRevision, session: Session = Depends(get_session)
    ):
        body = mutate(session, draft_id, value, drafts.retry_draft)
        if body["status"] == "pending":
            dispatch(draft_id)
        return body

    @router.post(
        "/outreach/compositions/{composition_id}/sender-facts",
        response_model=CompositionView,
        operation_id="confirmOutreachSenderFactsV2",
    )
    def sender_facts(
        composition_id: UUID,
        value: SenderFacts,
        session: Session = Depends(get_session),
    ):
        acquire_job_change_lock(session)
        result = drafts.confirm_sender_facts(session, composition_id, value)
        session.commit()
        return result

    return router
