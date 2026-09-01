from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event, select, update
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.core.database import get_session
from app.core.security import hash_workspace_key
from app.db.models.settings import ServiceSecret, SharedSettings
from app.main import create_app
from app.repositories.settings import SHARED_SETTINGS_ID


class AlwaysAllow:
    def allow(self, workspace_digest: str, client_address: str) -> bool:
        return True


class BlockingConnectionProbe:
    def __init__(self) -> None:
        self.block = False
        self.entered = Event()
        self.release = Event()
        self.secret_seen: str | None = None

    def test_connection(self, service: str, secret: str) -> bool:
        self.secret_seen = secret
        if self.block:
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("test did not release the blocking probe")
        return True


@dataclass
class IndependentSettingsHarness:
    first: TestClient
    second: TestClient
    probe: BlockingConnectionProbe
    engine: Engine


@pytest.fixture
def independent_settings_harness(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> Iterator[IndependentSettingsHarness]:
    _reset_settings_state(database_engine)
    probe = BlockingConnectionProbe()
    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AlwaysAllow(),
        secret_cipher=SecretCipher(bytes(range(32))),
        connection_probe=probe,
    )

    def independent_session() -> Iterator[Session]:
        with Session(database_engine) as database_session:
            try:
                yield database_session
                database_session.commit()
            except Exception:
                database_session.rollback()
                raise

    app.dependency_overrides[get_session] = independent_session
    authorization = {"Authorization": f"Bearer {workspace_access_key}"}
    try:
        with TestClient(app, headers=authorization) as first:
            with TestClient(app, headers=authorization) as second:
                yield IndependentSettingsHarness(
                    first=first,
                    second=second,
                    probe=probe,
                    engine=database_engine,
                )
    finally:
        probe.release.set()
        app.dependency_overrides.clear()
        _reset_settings_state(database_engine)


def test_stale_probe_result_cannot_mark_replaced_credential_tested(
    independent_settings_harness: IndependentSettingsHarness,
) -> None:
    harness = independent_settings_harness
    configured = harness.first.put(
        "/api/v1/settings/connections/youtube",
        json={"secret": "credential-a"},
    )
    assert configured.status_code == 200
    harness.probe.block = True

    with ThreadPoolExecutor(max_workers=1) as executor:
        probe_request = executor.submit(
            harness.first.post, "/api/v1/settings/connections/youtube"
        )
        assert harness.probe.entered.wait(timeout=5)
        replaced = harness.second.put(
            "/api/v1/settings/connections/youtube",
            json={"secret": "credential-b"},
        )
        harness.probe.release.set()
        probe_response = probe_request.result(timeout=5)

    status = harness.second.get("/api/v1/settings/connections/youtube")

    assert harness.probe.secret_seen == "credential-a"
    assert replaced.status_code == 200
    assert probe_response.status_code == 409
    assert probe_response.json()["error"]["code"] == "connection_changed"
    assert probe_response.json()["error"]["retryable"] is True
    assert status.json() == {
        "configured": True,
        "last_test_status": None,
        "last_tested_at": None,
    }


def test_concurrent_different_service_updates_preserve_both_metadata_entries(
    independent_settings_harness: IndependentSettingsHarness,
) -> None:
    harness = independent_settings_harness
    configured = harness.first.put(
        "/api/v1/settings/connections/youtube",
        json={"secret": "youtube-secret"},
    )
    assert configured.status_code == 200
    updates_ready = Barrier(2)

    def synchronize_shared_settings_updates(
        connection, cursor, statement, parameters, context, executemany
    ) -> None:
        if statement.lstrip().lower().startswith("update shared_settings"):
            updates_ready.wait(timeout=5)

    event.listen(
        harness.engine, "before_cursor_execute", synchronize_shared_settings_updates
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            steam_replacement = executor.submit(
                harness.first.put,
                "/api/v1/settings/connections/steam",
                json={"secret": "steam-secret"},
            )
            youtube_test = executor.submit(
                harness.second.post, "/api/v1/settings/connections/youtube"
            )
            steam_response = steam_replacement.result(timeout=5)
            youtube_response = youtube_test.result(timeout=5)
    finally:
        event.remove(
            harness.engine,
            "before_cursor_execute",
            synchronize_shared_settings_updates,
        )

    with Session(harness.engine) as database_session:
        settings = database_session.get(SharedSettings, SHARED_SETTINGS_ID)
        secrets = {
            secret.service: secret
            for secret in database_session.scalars(select(ServiceSecret)).all()
        }
        assert settings is not None
        metadata = settings.service_connection_state

    workspace = harness.first.get("/api/v1/session")

    assert steam_response.status_code == 200
    assert youtube_response.status_code == 200
    assert set(secrets) == {"steam", "youtube"}
    assert secrets["youtube"].last_test_succeeded is True
    assert set(metadata) == {"steam", "youtube"}
    assert metadata["steam"]["configured"] is True
    assert metadata["youtube"]["last_test_succeeded"] is True
    assert workspace.status_code == 200
    assert workspace.json()["service_connections"] == {
        "steam": True,
        "youtube": True,
    }


def _reset_settings_state(engine: Engine) -> None:
    with Session(engine) as database_session:
        database_session.execute(delete(ServiceSecret))
        database_session.execute(
            update(SharedSettings)
            .where(SharedSettings.id == SHARED_SETTINGS_ID)
            .values(
                creator_interval_days=14,
                game_interval_days=30,
                service_connection_state={},
            )
        )
        database_session.commit()
