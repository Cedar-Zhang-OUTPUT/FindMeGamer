import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.engine import Inspector
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.rate_limit import FixedWindowRateLimiter
from app.core.security import hash_workspace_key
from app.main import create_app


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ACCESS_KEY = "test-workspace-access-key"


class FakeRateLimitCounter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.keys: list[str] = []

    def increment(self, key: str, window_seconds: int) -> int:
        self.keys.append(key)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point to the isolated PostgreSQL test database")
    return url


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    config = Config(BACKEND_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="session")
def migrated_database(alembic_config: Config) -> Iterator[None]:
    command.upgrade(alembic_config, "head")
    yield


@pytest.fixture(scope="session")
def database_engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(
    migrated_database: None, database_engine: Engine
) -> Iterator[Session]:
    connection = database_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def database_session(session: Session) -> Session:
    return session


@pytest.fixture
def rate_limit_counter() -> FakeRateLimitCounter:
    return FakeRateLimitCounter()


@pytest.fixture
def workspace_access_key() -> str:
    return WORKSPACE_ACCESS_KEY


@pytest.fixture
def client(
    session: Session,
    rate_limit_counter: FakeRateLimitCounter,
    workspace_access_key: str,
) -> Iterator[TestClient]:
    test_app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=FixedWindowRateLimiter(
            counter=rate_limit_counter,
            limit=100,
            window_seconds=60,
            clock=lambda: 0.0,
        ),
    )

    def override_get_session() -> Iterator[Session]:
        yield session

    test_app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(test_app) as test_client:
            yield test_client
    finally:
        test_app.dependency_overrides.clear()


@pytest.fixture
def captured_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    logging.getLogger("app.requests").disabled = False
    caplog.set_level("INFO", logger="app.requests")
    return caplog


@pytest.fixture
def database_inspector(
    migrated_database: None, database_engine: Engine
) -> Inspector:
    return inspect(database_engine)
