from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.settings import ServiceSecret


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/settings/reanalysis", None),
        (
            "patch",
            "/api/v1/settings/reanalysis",
            {"creator_interval_days": 14, "game_interval_days": 30},
        ),
        ("get", "/api/v1/settings/connections/youtube", None),
        (
            "put",
            "/api/v1/settings/connections/youtube",
            {"secret": "never-accepted-without-auth"},
        ),
        ("post", "/api/v1/settings/connections/youtube", None),
    ],
)
def test_settings_routes_require_workspace_authentication(
    client, method: str, path: str, payload: dict[str, object] | None
) -> None:
    request = getattr(client, method)
    response = request(path, **({"json": payload} if payload is not None else {}))

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "workspace_key_invalid",
            "message": "A valid Workspace Access Key is required.",
            "retryable": False,
            "correlation_id": response.headers["x-correlation-id"],
        }
    }


def test_reanalysis_defaults_and_updates_persist(auth_client) -> None:
    initial = auth_client.get("/api/v1/settings/reanalysis")
    updated = auth_client.patch(
        "/api/v1/settings/reanalysis",
        json={"creator_interval_days": 7, "game_interval_days": 45},
    )
    reread = auth_client.get("/api/v1/settings/reanalysis")

    assert initial.status_code == 200
    assert initial.json() == {
        "creator_interval_days": 14,
        "game_interval_days": 30,
    }
    assert updated.status_code == 200
    assert updated.json() == {
        "creator_interval_days": 7,
        "game_interval_days": 45,
    }
    assert reread.json() == updated.json()


@pytest.mark.parametrize(
    "payload",
    [
        {"creator_interval_days": 0, "game_interval_days": 30},
        {"creator_interval_days": 31, "game_interval_days": 30},
        {"creator_interval_days": 14, "game_interval_days": 0},
        {"creator_interval_days": 14, "game_interval_days": 91},
        {"creator_interval_days": None, "game_interval_days": 30},
        {"creator_interval_days": 14},
    ],
)
def test_reanalysis_rejects_disabled_out_of_range_or_incomplete_values(
    auth_client, payload: dict[str, object]
) -> None:
    response = auth_client.patch("/api/v1/settings/reanalysis", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"


@pytest.mark.parametrize("service", ["steam", "youtube", "deepseek", "google_ai"])
def test_settings_support_only_approved_connection_services(
    auth_client, service: str
) -> None:
    missing = auth_client.get(f"/api/v1/settings/connections/{service}")
    saved = auth_client.put(
        f"/api/v1/settings/connections/{service}",
        json={"secret": f"{service}-secret"},
    )

    assert missing.status_code == 200
    assert missing.json() == {
        "configured": False,
        "last_test_status": None,
        "last_tested_at": None,
    }
    assert saved.status_code == 200
    assert saved.json() == {
        "configured": True,
        "last_test_status": None,
        "last_tested_at": None,
    }


@pytest.mark.parametrize("method", ["get", "put", "post"])
@pytest.mark.parametrize("service", ["smtp", "unknown"])
def test_unknown_connection_service_uses_stable_error_envelope(
    auth_client, method: str, service: str
) -> None:
    request = getattr(auth_client, method)
    kwargs = {"json": {"secret": "never-store"}} if method == "put" else {}

    response = request(f"/api/v1/settings/connections/{service}", **kwargs)

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "connection_service_unknown",
            "message": "The requested connection service is not supported.",
            "retryable": False,
            "correlation_id": response.headers["x-correlation-id"],
        }
    }


def test_unknown_connection_service_wins_over_body_validation(auth_client) -> None:
    response = auth_client.put("/api/v1/settings/connections/smtp")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "connection_service_unknown"


def test_connection_read_never_returns_plaintext(auth_client, session: Session) -> None:
    plaintext = "google-ai-key-never-store-in-plaintext"
    auth_client.put(
        "/api/v1/settings/connections/google_ai", json={"secret": plaintext}
    )

    body = auth_client.get("/api/v1/settings/connections/google_ai").json()
    session.expire_all()
    stored = session.scalar(
        select(ServiceSecret).where(ServiceSecret.service == "google_ai")
    )

    assert body["configured"] is True
    assert set(body) == {"configured", "last_test_status", "last_tested_at"}
    assert plaintext not in str(body)
    assert stored is not None
    assert plaintext.encode() not in stored.ciphertext
    assert plaintext.encode() not in stored.nonce


def test_replacing_secret_atomically_upserts_and_resets_test_status(
    auth_client, session: Session, connection_probe
) -> None:
    auth_client.put(
        "/api/v1/settings/connections/youtube", json={"secret": "first-secret"}
    )
    connection_probe.expected = ("youtube", "first-secret")
    tested = auth_client.post("/api/v1/settings/connections/youtube")
    session.expire_all()
    first = session.scalar(
        select(ServiceSecret).where(ServiceSecret.service == "youtube")
    )
    assert first is not None
    first_id = first.id
    first_ciphertext = first.ciphertext
    assert tested.json()["last_test_status"] == "success"

    replaced = auth_client.put(
        "/api/v1/settings/connections/youtube", json={"secret": "second-secret"}
    )
    session.expire_all()
    second = session.scalar(
        select(ServiceSecret).where(ServiceSecret.service == "youtube")
    )

    assert replaced.json() == {
        "configured": True,
        "last_test_status": None,
        "last_tested_at": None,
    }
    assert second is not None
    assert second.id == first_id
    assert second.ciphertext != first_ciphertext
    assert session.scalar(select(func.count()).select_from(ServiceSecret)) == 1


def test_connection_probe_success_records_safe_status_after_read_transaction_closes(
    auth_client, session: Session, connection_probe
) -> None:
    auth_client.put(
        "/api/v1/settings/connections/google_ai",
        json={"secret": "google-ai-secret"},
    )
    connection_probe.expected = ("google_ai", "google-ai-secret")
    connection_probe.before_test = lambda: (
        (_ for _ in ()).throw(AssertionError("database transaction held during probe"))
        if session.in_transaction()
        else None
    )

    response = auth_client.post("/api/v1/settings/connections/google_ai")

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["last_test_status"] == "success"
    assert datetime.fromisoformat(response.json()["last_tested_at"])


def test_connection_probe_failure_records_failure_without_secret(
    auth_client, connection_probe
) -> None:
    connection_probe.result = False
    connection_probe.expected = ("steam", "steam-private-key")
    auth_client.put(
        "/api/v1/settings/connections/steam",
        json={"secret": "steam-private-key"},
    )

    response = auth_client.post("/api/v1/settings/connections/steam")

    assert response.status_code == 200
    assert response.json()["last_test_status"] == "failure"
    assert response.json()["last_tested_at"] is not None
    assert "steam-private-key" not in response.text


def test_connection_probe_exception_is_sanitized_in_api_and_logs(
    auth_client, connection_probe, captured_logs
) -> None:
    secret = "youtube-key-never-expose"
    connection_probe.error = TimeoutError(
        f"upstream failure includes credential={secret}"
    )
    auth_client.put("/api/v1/settings/connections/youtube", json={"secret": secret})

    response = auth_client.post("/api/v1/settings/connections/youtube")

    assert response.status_code == 200
    assert response.json()["last_test_status"] == "failure"
    assert secret not in response.text
    assert "upstream failure" not in response.text
    assert secret not in captured_logs.text
    assert "upstream failure" not in captured_logs.text


def test_connection_test_requires_a_configured_secret(auth_client) -> None:
    response = auth_client.post("/api/v1/settings/connections/steam")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "connection_not_configured"


def test_connection_decryption_failure_uses_safe_public_error(
    auth_client, session: Session, captured_logs
) -> None:
    secret = "corrupted-key-never-expose"
    auth_client.put("/api/v1/settings/connections/deepseek", json={"secret": secret})
    session.expire_all()
    stored = session.scalar(
        select(ServiceSecret).where(ServiceSecret.service == "deepseek")
    )
    assert stored is not None
    stored.ciphertext = bytes([stored.ciphertext[0] ^ 1]) + stored.ciphertext[1:]
    session.flush()

    response = auth_client.post("/api/v1/settings/connections/deepseek")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert secret not in response.text
    assert secret not in captured_logs.text
