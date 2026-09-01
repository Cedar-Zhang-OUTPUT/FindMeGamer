import json
from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.rate_limit import FixedWindowRateLimiter
from app.core.security import hash_workspace_key
from app.db.models.settings import SharedSettings
from app.main import create_app


def test_session_rejects_missing_bearer_with_stable_error(client) -> None:
    response = client.get("/api/v1/session")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "workspace_key_invalid",
            "message": "A valid Workspace Access Key is required.",
            "retryable": False,
            "correlation_id": response.headers["x-correlation-id"],
        }
    }


def test_session_rejects_invalid_bearer(client) -> None:
    response = client.get(
        "/api/v1/session", headers={"Authorization": "Bearer incorrect-key"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "workspace_key_invalid"
    assert response.json()["error"]["correlation_id"] == response.headers[
        "x-correlation-id"
    ]


def test_session_returns_only_sanitized_workspace_state(
    client, session: Session, workspace_access_key: str
) -> None:
    settings = session.scalar(select(SharedSettings))
    assert settings is not None
    settings.workspace_name = "Publishing Workspace"
    settings.service_connection_state = {
        "steam": {"connected": True, "credential": "never-return-this"},
        "youtube": False,
        "smtp": {
            "last_test_succeeded": False,
            "email_body": "never-return-this-either",
        },
    }
    session.flush()

    response = client.get(
        "/api/v1/session",
        headers={"Authorization": f"Bearer {workspace_access_key}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "workspace_name": "Publishing Workspace",
        "api_version": "v1",
        "service_connections": {
            "steam": True,
            "youtube": False,
            "smtp": False,
        },
    }
    assert "credential" not in response.text
    assert "email_body" not in response.text
    assert "never-return-this" not in response.text


def test_error_propagates_safe_correlation_id(client) -> None:
    response = client.get(
        "/api/v1/session",
        headers={"X-Correlation-ID": "client-request_123"},
    )

    assert response.status_code == 401
    assert response.headers["x-correlation-id"] == "client-request_123"
    assert response.json()["error"]["correlation_id"] == "client-request_123"


def test_unsafe_correlation_id_is_replaced(client) -> None:
    response = client.get(
        "/api/v1/session",
        headers={"X-Correlation-ID": "unsafe correlation\nvalue"},
    )

    correlation_id = response.headers["x-correlation-id"]
    assert correlation_id != "unsafe correlation\nvalue"
    assert "\n" not in correlation_id
    assert response.json()["error"]["correlation_id"] == correlation_id


def test_unmatched_route_uses_stable_error_envelope(client) -> None:
    response = client.get(
        "/does-not-exist",
        headers={"X-Correlation-ID": "missing-route_123"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested resource was not found.",
            "retryable": False,
            "correlation_id": "missing-route_123",
        }
    }
    assert response.headers["x-correlation-id"] == "missing-route_123"


def test_unexpected_error_uses_safe_error_envelope(client) -> None:
    def explode() -> None:
        raise RuntimeError("credential=never-return-this")

    client.app.add_api_route("/_test/explode", explode, methods=["GET"])
    response = client.get(
        "/_test/explode",
        headers={"X-Correlation-ID": "failed-route_123"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "The request could not be completed.",
            "retryable": True,
            "correlation_id": "failed-route_123",
        }
    }
    assert "never-return-this" not in response.text


def test_workspace_rate_limit_is_enforced_without_exposing_key(
    session: Session, rate_limit_counter, workspace_access_key: str
) -> None:
    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=FixedWindowRateLimiter(
            counter=rate_limit_counter,
            limit=1,
            window_seconds=60,
            clock=lambda: 0.0,
        ),
    )

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as limited_client:
        headers = {"Authorization": f"Bearer {workspace_access_key}"}
        first = limited_client.get("/api/v1/session", headers=headers)
        second = limited_client.get("/api/v1/session", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limit_exceeded"
    assert second.json()["error"]["retryable"] is True
    assert workspace_access_key not in repr(rate_limit_counter.keys)


def test_rotating_invalid_bearers_share_pre_authentication_bucket(
    monkeypatch, session: Session, rate_limit_counter, workspace_access_key: str
) -> None:
    verification_attempts: list[str] = []

    def record_verification(raw_key: str, encoded_hash: str) -> bool:
        verification_attempts.append(raw_key)
        return False

    monkeypatch.setattr(
        "app.api.dependencies.verify_workspace_key", record_verification
    )
    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=FixedWindowRateLimiter(
            counter=rate_limit_counter,
            limit=2,
            window_seconds=60,
            clock=lambda: 0.0,
        ),
    )

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as limited_client:
        responses = [
            limited_client.get(
                "/api/v1/session",
                headers={"Authorization": f"Bearer invalid-key-{index}"},
            )
            for index in range(3)
        ]

    assert [response.status_code for response in responses] == [401, 401, 429]
    assert verification_attempts == ["invalid-key-0", "invalid-key-1"]
    assert len(set(rate_limit_counter.keys)) == 1
    assert all("invalid-key" not in key for key in rate_limit_counter.keys)


def test_rate_limit_backend_failure_returns_safe_retryable_error(
    session: Session, workspace_access_key: str
) -> None:
    class FailingRateLimiter:
        def allow(self, workspace_digest: str, client_address: str) -> bool:
            raise TimeoutError("redis-password=never-return-this")

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=FailingRateLimiter(),
    )

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as unavailable_client:
        response = unavailable_client.get(
            "/api/v1/session",
            headers={"Authorization": f"Bearer {workspace_access_key}"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"
    assert response.json()["error"]["retryable"] is True
    assert response.json()["error"]["correlation_id"] == response.headers[
        "x-correlation-id"
    ]
    assert "never-return-this" not in response.text


def test_rate_limit_uses_origin_resolved_through_trusted_proxy(
    session: Session, rate_limit_counter, workspace_access_key: str
) -> None:
    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=FixedWindowRateLimiter(
            counter=rate_limit_counter,
            limit=1,
            window_seconds=60,
            clock=lambda: 0.0,
        ),
        trusted_proxy_cidrs=("172.16.0.0/12",),
    )

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    auth = {"Authorization": f"Bearer {workspace_access_key}"}
    with TestClient(app, client=("172.18.0.2", 50000)) as proxy_client:
        first = proxy_client.get(
            "/api/v1/session",
            headers={**auth, "X-Forwarded-For": "192.0.2.10, 198.51.100.44"},
        )
        second = proxy_client.get(
            "/api/v1/session",
            headers={**auth, "X-Forwarded-For": "203.0.113.20, 198.51.100.44"},
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert len(set(rate_limit_counter.keys)) == 1


def test_request_log_redacts_authorization(client, captured_logs) -> None:
    client.get(
        "/api/v1/session",
        headers={"Authorization": "Bearer never-log-me"},
    )

    assert "never-log-me" not in captured_logs.text
    request_record = next(
        record for record in captured_logs.records if record.name == "app.requests"
    )
    assert set(json.loads(request_record.getMessage())) == {
        "method",
        "route",
        "status",
        "duration_ms",
        "correlation_id",
    }


def test_request_log_ignores_query_string_and_body(client, captured_logs) -> None:
    client.post(
        "/missing?response_token=never-log-query",
        json={
            "smtp_password": "never-log-credential",
            "email_body": "never-log-email-body",
        },
    )

    assert "never-log-query" not in captured_logs.text
    assert "never-log-credential" not in captured_logs.text
    assert "never-log-email-body" not in captured_logs.text
