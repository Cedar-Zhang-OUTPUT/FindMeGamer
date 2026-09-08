"""Manual business follow-up, never a mail dispatch or simulated inbox."""

from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.core.database import get_session
from app.api.routes.activity import _get, _write
from app.db.models.discovery import Activity
from app.db.models.profiles import CreatorProfile
from app.repositories.activity_preparation import get_selection
from app.repositories.activity_collaboration import (
    invitation,
    list_invitations,
    update_tracking,
)
from app.schemas.activity_collaboration import (
    ActivityInvitation,
    ActivityInvitationPage,
    CollaborationUpdate,
    ManualActivityResponse,
    SendingState,
    InvitationState,
    FollowUpState,
)


def create_router(authenticate_workspace):
    router = APIRouter(
        prefix="/api/v2",
        tags=["activity-collaboration"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get(
        "/activities/{activity_id}/invitations",
        response_model=ActivityInvitationPage,
        operation_id="listActivityInvitationsV2",
    )
    def listing(
        activity_id: UUID,
        sending_state: SendingState | None = None,
        invitation_state: InvitationState | None = None,
        follow_up_state: FollowUpState | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        _get(session, Activity, activity_id)
        return list_invitations(
            session,
            activity_id=activity_id,
            sending_state=sending_state,
            invitation_state=invitation_state,
            follow_up_state=follow_up_state,
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/activities/{activity_id}/invitations/{selection_id}",
        response_model=ActivityInvitation,
        operation_id="getActivityInvitationV2",
    )
    def get(
        activity_id: UUID, selection_id: UUID, session: Session = Depends(get_session)
    ):
        return invitation(session, get_selection(session, activity_id, selection_id))

    @router.get(
        "/library/creators/{creator_id}/invitations",
        response_model=ActivityInvitationPage,
        operation_id="listCreatorInvitationsV2",
    )
    def creator_history(
        creator_id: UUID,
        activity_id: UUID | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        _get(session, CreatorProfile, creator_id)
        return list_invitations(
            session,
            creator_id=creator_id,
            activity_id=activity_id,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/activities/{activity_id}/invitations/{selection_id}/update",
        response_model=ActivityInvitation,
        operation_id="updateActivityCollaborationV2",
    )
    def update(
        activity_id: UUID,
        selection_id: UUID,
        value: CollaborationUpdate,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/activities/{activity_id}/invitations/{selection_id}/update",
            payload=value.model_dump(mode="json", exclude_unset=True),
            status=200,
            operation=lambda: update_tracking(
                session, activity_id, selection_id, value
            ),
        )
        return JSONResponse(status_code=status, content=body)

    @router.post(
        "/activities/{activity_id}/invitations/{selection_id}/responses",
        response_model=ActivityInvitation,
        operation_id="recordActivityResponseV2",
    )
    def record_response(
        activity_id: UUID,
        selection_id: UUID,
        value: ManualActivityResponse,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        session: Session = Depends(get_session),
    ):
        body, status = _write(
            session,
            key=key,
            path=f"/api/v2/activities/{activity_id}/invitations/{selection_id}/responses",
            payload=value.model_dump(mode="json"),
            status=200,
            operation=lambda: update_tracking(
                session, activity_id, selection_id, value, response=True
            ),
        )
        return JSONResponse(status_code=status, content=body)

    return router
