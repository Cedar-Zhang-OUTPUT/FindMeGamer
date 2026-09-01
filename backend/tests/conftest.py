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

from app.main import app


BACKEND_ROOT = Path(__file__).resolve().parents[1]


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
    session = Session(bind=connection)
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
def client(migrated_database: None) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def database_inspector(database_engine: Engine) -> Inspector:
    return inspect(database_engine)
