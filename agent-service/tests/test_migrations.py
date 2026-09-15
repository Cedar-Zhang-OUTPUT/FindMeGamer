"""Use a fresh schema per test in the explicitly isolated PostgreSQL test DB."""

import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


def migrate(url, schema=None, revision="head"):
    env = dict(os.environ, FMG_AGENT_DATABASE_URL=url)
    if schema:
        env["PGOPTIONS"] = f"-c search_path={schema}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
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
        original = migrate(url, schema, revision="0001_tokens")
        assert original.returncode == 0, original.stderr
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"""INSERT INTO "{schema}".access_tokens
                (id, digest, label, scopes, created_at)
                VALUES ('migration-survivor', :digest, 'preserve', '[]', CURRENT_TIMESTAMP)"""
                ),
                {"digest": "0" * 64},
            )
        first = migrate(url, schema)
        assert first.returncode == 0, first.stderr
        second = migrate(url, schema)
        assert second.returncode == 0, second.stderr
        with engine.connect() as conn:
            assert (
                conn.scalar(
                    text(
                        f"""SELECT label FROM "{schema}".access_tokens
                WHERE id = 'migration-survivor' """
                    )
                )
                == "preserve"
            )
            assert set(inspect(conn).get_table_names(schema=schema)) == {
                "access_tokens",
                "alembic_version",
                "email_jobs",
            }
            assert (
                conn.scalar(text(f'SELECT version_num FROM "{schema}".alembic_version'))
                == "0002_email_jobs"
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
            from concurrent.futures import ThreadPoolExecutor
            from fmg_agent.email.jobs import JobStore

            with app.state.sessions() as session:
                email_token = issue_token(
                    session, label="email-agent", scopes=["email:enrich"]
                )
            store = JobStore(app.state.sessions)
            # Concurrent requests have one durable record and one active owner.
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs = list(
                    pool.map(
                        lambda _: store.create(
                            email_token.id,
                            "same-key",
                            {"url": "https://example.com/creator"},
                        ),
                        range(4),
                    )
                )
            ids = {job["id"] for job in jobs}
            assert len(ids) == 1
            job_id = jobs[0]["id"]
            with ThreadPoolExecutor(max_workers=4) as pool:
                leases = list(pool.map(lambda _: store.claim(job_id), range(4)))
            assert sum(lease is not None for lease in leases) == 1
            lease = next(lease for lease in leases if lease is not None)
            assert store.checkpoint(job_id, lease, "public_pages", {"emails": []})
            assert store.fail(job_id, lease, "upstream_rate_limited", retryable=True)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda _: store.retry(job_id, email_token.id), range(4)))
            assert store.load(job_id)["checkpoints"] == {"public_pages": {"emails": []}}
            assert store.complete(job_id, store.claim(job_id), [])
            assert store.load(job_id)["state"] == "completed"
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
