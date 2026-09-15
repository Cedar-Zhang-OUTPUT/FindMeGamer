"""Use a fresh schema per test in the explicitly isolated PostgreSQL test DB."""

import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


def migrate(url, schema=None):
    env = dict(os.environ, FMG_AGENT_DATABASE_URL=url)
    if schema:
        env["PGOPTIONS"] = f"-c search_path={schema}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_migration_rejects_old_database_before_connecting():
    result = migrate(
        "postgresql+psycopg://agent:private-value@127.0.0.1:1/find_me_gamer"
    )
    assert result.returncode != 0
    assert "isolated" in result.stderr
    assert "private-value" not in result.stderr


@pytest.mark.postgres
def test_postgres_migration_repeat_and_auth_roundtrip():
    from fastapi.testclient import TestClient
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token, revoke_token
    from fmg_agent.config import Settings

    url = os.environ.get("FMG_AGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set FMG_AGENT_TEST_DATABASE_URL for isolated PostgreSQL checks")
    # Refuse destructive fixture setup outside the one dedicated test DB.
    engine = create_engine(url)
    assert engine.url.database == "find_me_gamer_agent_test"
    schema = "auth_test_" + uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        first = migrate(url, schema)
        assert first.returncode == 0, first.stderr
        second = migrate(url, schema)
        assert second.returncode == 0, second.stderr
        with engine.connect() as conn:
            assert set(inspect(conn).get_table_names(schema=schema)) == {
                "access_tokens",
                "alembic_version",
            }
            assert (
                conn.scalar(text(f'SELECT version_num FROM "{schema}".alembic_version'))
                == "0001_tokens"
            )
        # Use the same migrated schema through the actual application factory.
        settings = Settings(
            database_url=str(
                engine.url.set(
                    query={"options": f"-c search_path={schema}"}
                ).render_as_string(hide_password=False)
            )
        )
        app = create_app(settings)
        with TestClient(app) as client:
            with app.state.sessions() as session:
                issued = issue_token(session, label="postgres-agent", scopes=["read"])
            assert (
                client.get(
                    "/v1/auth/check",
                    headers={"Authorization": f"Bearer {issued.token}"},
                ).status_code
                == 200
            )
            with app.state.sessions() as session:
                revoke_token(session, issued.id)
            assert (
                client.get(
                    "/v1/auth/check",
                    headers={"Authorization": f"Bearer {issued.token}"},
                ).status_code
                == 401
            )
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
