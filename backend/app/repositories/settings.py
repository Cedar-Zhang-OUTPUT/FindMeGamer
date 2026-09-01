from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.crypto import EncryptedValue
from app.db.models.settings import ServiceSecret, SharedSettings


SHARED_SETTINGS_ID = UUID("00000000-0000-0000-0000-000000000001")


class SettingsRepository:
    def __init__(self, database_session: Session) -> None:
        self._session = database_session

    def get_reanalysis(self) -> SharedSettings:
        settings = self._session.get(SharedSettings, SHARED_SETTINGS_ID)
        if settings is None:
            raise RuntimeError("shared settings row is missing")
        return settings

    def update_reanalysis(
        self, *, creator_interval_days: int, game_interval_days: int
    ) -> SharedSettings:
        settings = self.get_reanalysis()
        settings.creator_interval_days = creator_interval_days
        settings.game_interval_days = game_interval_days
        self._session.flush()
        return settings

    def get_connection(self, service: str) -> ServiceSecret | None:
        return self._session.scalar(
            select(ServiceSecret).where(ServiceSecret.service == service)
        )

    def replace_connection(
        self, service: str, encrypted: EncryptedValue
    ) -> ServiceSecret:
        statement = insert(ServiceSecret).values(
            id=uuid4(),
            service=service,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            last_test_succeeded=None,
            last_test_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[ServiceSecret.service],
            set_={
                "ciphertext": statement.excluded.ciphertext,
                "nonce": statement.excluded.nonce,
                "last_test_succeeded": None,
                "last_test_at": None,
                "updated_at": func.now(),
            },
        )
        self._session.execute(statement)
        self._update_connection_metadata(
            service, last_test_succeeded=None, last_test_at=None
        )
        self._session.flush()
        stored = self.get_connection(service)
        if stored is None:
            raise RuntimeError("service secret upsert did not persist")
        return stored

    def record_connection_test(
        self,
        service: str,
        *,
        succeeded: bool,
        tested_at: datetime,
    ) -> ServiceSecret:
        stored = self.get_connection(service)
        if stored is None:
            raise RuntimeError("service secret is missing")
        stored.last_test_succeeded = succeeded
        stored.last_test_at = tested_at
        self._update_connection_metadata(
            service, last_test_succeeded=succeeded, last_test_at=tested_at
        )
        self._session.flush()
        return stored

    def _update_connection_metadata(
        self,
        service: str,
        *,
        last_test_succeeded: bool | None,
        last_test_at: datetime | None,
    ) -> None:
        settings = self.get_reanalysis()
        state = dict(settings.service_connection_state)
        state[service] = {
            "configured": True,
            "last_test_succeeded": last_test_succeeded,
            "last_test_at": last_test_at.isoformat() if last_test_at else None,
        }
        settings.service_connection_state = state
