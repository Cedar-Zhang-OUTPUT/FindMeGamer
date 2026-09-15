"""Security boundary tests use real sessions, token storage and HTTP requests."""

import hashlib
import json
import os
import subprocess
import sys

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select, text


@pytest.fixture
def gateway(tmp_path):
    from fmg_agent.app import create_app
    from fmg_agent.auth import require_scope
    from fmg_agent.config import Settings
    from fmg_agent.db import Base

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'auth.sqlite'}")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)

    # Exercise the production scope dependency without inventing a sending API.
    @app.post("/test/send", dependencies=[Depends(require_scope("email:send"))])
    def send():
        return {"accepted": True}

    with TestClient(app) as client:
        yield app, client


def issue(app, scopes=("read",)):
    from fmg_agent.auth import issue_token

    with app.state.sessions() as session:
        return issue_token(session, label="test-agent", scopes=list(scopes))


def headers(raw):
    return {"Authorization": f"Bearer {raw}"}


def test_health_does_not_expose_configuration(gateway):
    _, client = gateway
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "authorization", [None, "Bearer invented", "Basic secret", "Bearer"]
)
def test_invalid_auth_is_uniform_and_redacted(gateway, authorization):
    _, client = gateway
    response = client.get(
        "/v1/auth/check",
        headers={} if authorization is None else {"Authorization": authorization},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"
    assert response.json()["error"]["retryable"] is False
    assert response.json()["request_id"]
    assert response.headers["www-authenticate"] == "Bearer"
    assert "invented" not in response.text
    assert "secret" not in response.text


def test_issued_token_authenticates_and_only_digest_is_stored(gateway):
    from fmg_agent.db import AccessToken

    app, client = gateway
    issued = issue(app)
    response = client.get("/v1/auth/check", headers=headers(issued.token))
    assert response.status_code == 200
    assert response.json()["data"] == {
        "token_id": issued.id,
        "label": "test-agent",
        "scopes": ["read"],
    }
    with app.state.sessions() as session:
        stored = session.scalar(select(AccessToken))
        assert stored.digest == hashlib.sha256(issued.token.encode()).hexdigest()
        rows = session.execute(text("SELECT * FROM access_tokens")).all()
    assert issued.token not in str(rows)
    assert issued.token not in repr(issued)
    assert issued.token not in response.text


def test_revocation_is_effective_on_next_request(gateway):
    from fmg_agent.auth import revoke_token

    app, client = gateway
    issued = issue(app)
    assert (
        client.get("/v1/auth/check", headers=headers(issued.token)).status_code == 200
    )
    with app.state.sessions() as session:
        assert revoke_token(session, issued.id) is True
        assert revoke_token(session, issued.id) is True
    response = client.get("/v1/auth/check", headers=headers(issued.token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"


def test_read_token_cannot_send(gateway):
    app, client = gateway
    issued = issue(app)
    response = client.post("/test/send", headers=headers(issued.token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


def test_explicit_send_scope_allows_send(gateway):
    app, client = gateway
    issued = issue(app, ("read", "email:send"))
    assert client.post("/test/send", headers=headers(issued.token)).json() == {
        "accepted": True
    }


@pytest.mark.parametrize("scopes", [[], ["admin"], ["read", "unknown"]])
def test_invalid_scopes_do_not_create_tokens(gateway, scopes):
    from fmg_agent.auth import issue_token
    from fmg_agent.db import AccessToken

    app, _ = gateway
    with app.state.sessions() as session:
        with pytest.raises(ValueError):
            issue_token(session, label="agent", scopes=scopes)
        assert session.scalar(select(AccessToken)) is None


def test_admin_create_and_revoke_without_secret_in_arguments(gateway, tmp_path):
    app, client = gateway
    env = dict(os.environ, FMG_AGENT_DATABASE_URL=str(app.state.engine.url))
    create = subprocess.run(
        [
            sys.executable,
            "-m",
            "fmg_agent.admin",
            "token",
            "create",
            "--label",
            "cli-agent",
        ],
        env=env,
        text=True,
        capture_output=True,
    )
    assert create.returncode == 0, create.stderr
    created = json.loads(create.stdout)
    assert created["token"] not in create.stderr
    assert (
        client.get("/v1/auth/check", headers=headers(created["token"])).status_code
        == 200
    )
    revoke = subprocess.run(
        [sys.executable, "-m", "fmg_agent.admin", "token", "revoke", created["id"]],
        env=env,
        text=True,
        capture_output=True,
    )
    assert revoke.returncode == 0, revoke.stderr
    assert (
        client.get("/v1/auth/check", headers=headers(created["token"])).status_code
        == 401
    )


def test_missing_database_fails_without_leaking_dsn(tmp_path):
    env = dict(
        os.environ,
        FMG_AGENT_DATABASE_URL="postgresql+psycopg://agent:must-not-leak@127.0.0.1:1/find_me_gamer_agent",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "fmg_agent.admin",
            "token",
            "create",
            "--label",
            "agent",
        ],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 5
    assert result.stdout == ""
    assert "storage is unavailable" in result.stderr
    assert "must-not-leak" not in result.stderr
    assert "Traceback" not in result.stderr


def test_storage_failure_returns_recoverable_error_without_details(tmp_path):
    from fmg_agent.app import create_app
    from fmg_agent.config import Settings

    # A database without migrations must not produce a raw SQL traceback.
    app = create_app(
        Settings(database_url=f"sqlite:///{tmp_path / 'unmigrated.sqlite'}")
    )
    with TestClient(app) as client:
        response = client.get("/v1/auth/check", headers=headers("test-secret-token"))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert response.json()["error"]["retryable"] is True
    assert "access_tokens" not in response.text
    assert "test-secret-token" not in response.text


def test_settings_repr_does_not_expose_database_password():
    from fmg_agent.config import Settings

    settings = Settings(
        database_url="postgresql+psycopg://agent:secret-value@localhost/find_me_gamer_agent"
    )
    assert "secret-value" not in repr(settings)


@pytest.mark.parametrize(
    "database", ["find_me_gamer", "find_me_gamer_test", "postgres"]
)
def test_old_database_is_rejected(database):
    from fmg_agent.config import Settings

    with pytest.raises(ValueError, match="isolated"):
        Settings(database_url=f"postgresql+psycopg://agent:secret@localhost/{database}")
