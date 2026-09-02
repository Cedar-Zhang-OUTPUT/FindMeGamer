from collections.abc import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.db.models.settings import SharedSettings


class SessionResponse(BaseModel):
    workspace_name: str
    api_version: str
    service_connections: dict[str, bool]


def _connection_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        for field in ("connected", "last_test_succeeded", "configured"):
            state = value.get(field)
            if isinstance(state, bool):
                return state
    return False


def create_router(authenticate_workspace: Callable) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1",
        tags=["session"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get(
        "/session", response_model=SessionResponse, operation_id="validateSession"
    )
    def session(database_session: Session = Depends(get_session)) -> SessionResponse:
        settings = database_session.scalar(select(SharedSettings))
        if settings is None:
            return SessionResponse(
                workspace_name="Find Me Gamer",
                api_version="v1",
                service_connections={},
            )
        connections = {
            service: _connection_boolean(value)
            for service, value in settings.service_connection_state.items()
        }
        return SessionResponse(
            workspace_name=settings.workspace_name,
            api_version="v1",
            service_connections=connections,
        )

    return router
