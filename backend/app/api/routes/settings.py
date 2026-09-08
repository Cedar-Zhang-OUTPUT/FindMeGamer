from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.crypto import EncryptedValue, SecretCipher
from app.core.database import get_session
from app.core.errors import APIError
from app.db.models.settings import ServiceSecret
from app.repositories.settings import SettingsRepository
from app.schemas.settings import (
    ConnectionSecretUpdate,
    ConnectionStatusResponse,
    ReanalysisSettingsResponse,
    ReanalysisSettingsUpdate,
)


ALLOWED_CONNECTION_SERVICES = frozenset(
    {"steam", "youtube", "deepseek", "google_ai", "x"}
)


class ConnectionProbe(Protocol):
    def test_connection(self, service: str, secret: str) -> bool: ...


class UnavailableConnectionProbe:
    def test_connection(self, service: str, secret: str) -> bool:
        return False


def _require_supported_service(service: str) -> str:
    if service not in ALLOWED_CONNECTION_SERVICES:
        raise APIError(
            status_code=404,
            code="connection_service_unknown",
            message="The requested connection service is not supported.",
        )
    return service


def _connection_status(stored: ServiceSecret | None) -> ConnectionStatusResponse:
    if stored is None:
        return ConnectionStatusResponse(
            configured=False,
            last_test_status=None,
            last_tested_at=None,
        )
    if stored.last_test_succeeded is None:
        test_status = None
    elif stored.last_test_succeeded:
        test_status = "success"
    else:
        test_status = "failure"
    return ConnectionStatusResponse(
        configured=True,
        last_test_status=test_status,
        last_tested_at=stored.last_test_at,
    )


def create_router(
    authenticate_workspace: Callable,
    *,
    secret_cipher: SecretCipher,
    connection_probe: ConnectionProbe,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/settings",
        tags=["settings"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get(
        "/reanalysis",
        response_model=ReanalysisSettingsResponse,
        operation_id="getReanalysisSettings",
    )
    def read_reanalysis(
        database_session: Session = Depends(get_session),
    ) -> ReanalysisSettingsResponse:
        stored = SettingsRepository(database_session).get_reanalysis()
        return ReanalysisSettingsResponse(
            creator_interval_days=stored.creator_interval_days,
            game_interval_days=stored.game_interval_days,
        )

    @router.patch(
        "/reanalysis",
        response_model=ReanalysisSettingsResponse,
        operation_id="updateReanalysisSettings",
    )
    def update_reanalysis(
        update: ReanalysisSettingsUpdate,
        database_session: Session = Depends(get_session),
    ) -> ReanalysisSettingsResponse:
        stored = SettingsRepository(database_session).update_reanalysis(
            creator_interval_days=update.creator_interval_days,
            game_interval_days=update.game_interval_days,
        )
        database_session.commit()
        return ReanalysisSettingsResponse(
            creator_interval_days=stored.creator_interval_days,
            game_interval_days=stored.game_interval_days,
        )

    @router.get(
        "/connections/{service}",
        response_model=ConnectionStatusResponse,
        operation_id="getConnectionStatus",
    )
    def read_connection(
        service: Annotated[str, Depends(_require_supported_service)],
        database_session: Session = Depends(get_session),
    ) -> ConnectionStatusResponse:
        stored = SettingsRepository(database_session).get_connection(service)
        return _connection_status(stored)

    @router.put(
        "/connections/{service}",
        response_model=ConnectionStatusResponse,
        operation_id="replaceConnectionSecret",
    )
    def replace_connection(
        service: Annotated[str, Depends(_require_supported_service)],
        update: ConnectionSecretUpdate,
        database_session: Session = Depends(get_session),
    ) -> ConnectionStatusResponse:
        encrypted = secret_cipher.encrypt(update.secret)
        stored = SettingsRepository(database_session).replace_connection(
            service, encrypted
        )
        database_session.commit()
        return _connection_status(stored)

    @router.post(
        "/connections/{service}",
        response_model=ConnectionStatusResponse,
        operation_id="testConnection",
    )
    def test_connection(
        service: Annotated[str, Depends(_require_supported_service)],
        database_session: Session = Depends(get_session),
    ) -> ConnectionStatusResponse:
        repository = SettingsRepository(database_session)
        stored = repository.get_connection(service)
        if stored is None:
            raise APIError(
                status_code=409,
                code="connection_not_configured",
                message="Configure the connection before testing it.",
            )
        encrypted = EncryptedValue(
            ciphertext=bytes(stored.ciphertext), nonce=bytes(stored.nonce)
        )
        database_session.commit()

        try:
            secret = secret_cipher.decrypt(encrypted)
        except Exception:
            raise APIError(
                status_code=500,
                code="internal_error",
                message="The request could not be completed.",
                retryable=True,
            ) from None
        try:
            succeeded = connection_probe.test_connection(service, secret)
        except Exception:
            succeeded = False
        finally:
            secret = ""

        tested_at = datetime.now(timezone.utc)
        stored = SettingsRepository(database_session).record_connection_test(
            service,
            expected=encrypted,
            succeeded=succeeded,
            tested_at=tested_at,
        )
        if stored is None:
            database_session.rollback()
            raise APIError(
                status_code=409,
                code="connection_changed",
                message="The connection changed while it was being tested.",
                retryable=True,
            )
        database_session.commit()
        return _connection_status(stored)

    return router
