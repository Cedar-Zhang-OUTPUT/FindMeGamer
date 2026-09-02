from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import cast, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from app.core.crypto import EncryptedValue
from app.db.models.settings import ServiceSecret, SharedSettings


SHARED_SETTINGS_ID = UUID("00000000-0000-0000-0000-000000000001")
SMTP_PUBLIC_FIELDS = (
    "host",
    "port",
    "encryption",
    "username",
    "from_name",
    "reply_to",
)


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

    def get_smtp_settings(self, *, for_update: bool = False) -> SharedSettings:
        statement = select(SharedSettings).where(
            SharedSettings.id == SHARED_SETTINGS_ID
        )
        if for_update:
            statement = statement.with_for_update()
        settings = self._session.scalar(statement)
        if settings is None:
            raise RuntimeError("shared settings row is missing")
        return settings

    def save_smtp_configuration(
        self,
        *,
        public_metadata: dict[str, object],
        emails_per_minute: int,
        encrypted_password: EncryptedValue | None,
    ) -> tuple[SharedSettings, ServiceSecret]:
        settings = self.get_smtp_settings(for_update=True)
        stored = self.get_connection("smtp")
        current = settings.service_connection_state.get("smtp", {})
        public_changed = any(
            current.get(field) != public_metadata[field] for field in SMTP_PUBLIC_FIELDS
        )
        reset_test = public_changed or encrypted_password is not None

        if encrypted_password is not None:
            statement = insert(ServiceSecret).values(
                id=uuid4(),
                service="smtp",
                ciphertext=encrypted_password.ciphertext,
                nonce=encrypted_password.nonce,
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
            self._session.flush()
            stored = self.get_connection("smtp")
        elif stored is not None and reset_test:
            stored.last_test_succeeded = None
            stored.last_test_at = None

        if stored is None:
            raise RuntimeError("SMTP password is missing")

        if reset_test:
            last_test_succeeded = None
            last_test_at = None
        else:
            last_test_succeeded = stored.last_test_succeeded
            last_test_at = stored.last_test_at
        smtp_metadata = {
            **public_metadata,
            "configured": True,
            "last_test_succeeded": last_test_succeeded,
            "last_test_at": last_test_at.isoformat() if last_test_at else None,
        }
        state = dict(settings.service_connection_state)
        state["smtp"] = smtp_metadata
        settings.service_connection_state = state
        settings.smtp_rate_per_minute = emails_per_minute
        self._session.flush()
        return settings, stored

    def record_smtp_test(
        self,
        *,
        expected_secret: EncryptedValue,
        expected_public_metadata: dict[str, object],
        succeeded: bool,
        tested_at: datetime,
    ) -> ServiceSecret | None:
        settings = self.get_smtp_settings(for_update=True)
        stored = self.get_connection("smtp")
        current = settings.service_connection_state.get("smtp", {})
        current_public = {field: current.get(field) for field in SMTP_PUBLIC_FIELDS}
        if (
            stored is None
            or bytes(stored.ciphertext) != expected_secret.ciphertext
            or bytes(stored.nonce) != expected_secret.nonce
            or current_public != expected_public_metadata
        ):
            return None
        stored.last_test_succeeded = succeeded
        stored.last_test_at = tested_at
        state = dict(settings.service_connection_state)
        state["smtp"] = {
            **expected_public_metadata,
            "configured": True,
            "last_test_succeeded": succeeded,
            "last_test_at": tested_at.isoformat(),
        }
        settings.service_connection_state = state
        self._session.flush()
        return stored

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
        expected: EncryptedValue,
        succeeded: bool,
        tested_at: datetime,
    ) -> ServiceSecret | None:
        updated_id = self._session.scalar(
            update(ServiceSecret)
            .where(
                ServiceSecret.service == service,
                ServiceSecret.ciphertext == expected.ciphertext,
                ServiceSecret.nonce == expected.nonce,
            )
            .values(
                last_test_succeeded=succeeded,
                last_test_at=tested_at,
                updated_at=func.now(),
            )
            .returning(ServiceSecret.id)
            .execution_options(synchronize_session=False)
        )
        if updated_id is None:
            return None
        self._update_connection_metadata(
            service, last_test_succeeded=succeeded, last_test_at=tested_at
        )
        self._session.flush()
        return self._session.get(ServiceSecret, updated_id, populate_existing=True)

    def _update_connection_metadata(
        self,
        service: str,
        *,
        last_test_succeeded: bool | None,
        last_test_at: datetime | None,
    ) -> None:
        metadata_patch = {
            service: {
                "configured": True,
                "last_test_succeeded": last_test_succeeded,
                "last_test_at": last_test_at.isoformat() if last_test_at else None,
            }
        }
        updated_id = self._session.scalar(
            update(SharedSettings)
            .where(SharedSettings.id == SHARED_SETTINGS_ID)
            .values(
                service_connection_state=SharedSettings.service_connection_state.op(
                    "||"
                )(cast(metadata_patch, JSONB)),
                updated_at=func.now(),
            )
            .returning(SharedSettings.id)
            .execution_options(synchronize_session=False)
        )
        if updated_id is None:
            raise RuntimeError("shared settings row is missing")
