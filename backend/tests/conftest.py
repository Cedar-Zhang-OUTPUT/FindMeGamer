import atexit
import base64
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.engine import Inspector
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.core.security import hash_workspace_key


WORKSPACE_ACCESS_KEY = "test-workspace-access-key"
os.environ.setdefault(
    "WORKSPACE_ACCESS_KEY_HASH", hash_workspace_key(WORKSPACE_ACCESS_KEY)
)
_test_master_key = tempfile.NamedTemporaryFile(prefix="find-me-gamer-key-", delete=False)
_test_master_key.write(base64.b64encode(bytes(range(32))))
_test_master_key.close()
os.chmod(_test_master_key.name, 0o600)
os.environ.setdefault("MASTER_KEY_FILE", _test_master_key.name)
atexit.register(lambda: Path(_test_master_key.name).unlink(missing_ok=True))

from app.core.database import get_session
from app.core.rate_limit import FixedWindowRateLimiter
from app.main import create_app


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class FakeRateLimitCounter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.keys: list[str] = []

    def increment(self, key: str, window_seconds: int) -> int:
        self.keys.append(key)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


class FakeConnectionProbe:
    def __init__(self) -> None:
        self.result = True
        self.error: Exception | None = None
        self.expected: tuple[str, str] | None = None
        self.before_test = lambda: None

    def test_connection(self, service: str, secret: str) -> bool:
        self.before_test()
        if self.expected is not None and (service, secret) != self.expected:
            raise AssertionError("probe received an unexpected service or secret")
        if self.error is not None:
            raise self.error
        return self.result


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
def connection_probe() -> FakeConnectionProbe:
    return FakeConnectionProbe()


@pytest.fixture
def client(
    session: Session,
    rate_limit_counter: FakeRateLimitCounter,
    workspace_access_key: str,
    connection_probe: FakeConnectionProbe,
) -> Iterator[TestClient]:
    @contextmanager
    def job_session_factory() -> Iterator[Session]:
        yield session

    test_app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=FixedWindowRateLimiter(
            counter=rate_limit_counter,
            limit=100,
            window_seconds=60,
            clock=lambda: 0.0,
        ),
        secret_cipher=SecretCipher(bytes(range(32))),
        connection_probe=connection_probe,
        job_session_factory=job_session_factory,
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
def auth_client(client: TestClient, workspace_access_key: str) -> TestClient:
    client.headers.update({"Authorization": f"Bearer {workspace_access_key}"})
    return client


@pytest.fixture
def captured_logs(
    caplog: pytest.LogCaptureFixture,
) -> Iterator[pytest.LogCaptureFixture]:
    logger = logging.getLogger("app.requests")
    caplog.handler.setLevel(logging.INFO)
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


@pytest.fixture
def database_inspector(
    migrated_database: None, database_engine: Engine
) -> Inspector:
    return inspect(database_engine)
