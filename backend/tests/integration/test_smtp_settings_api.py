from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.outreach import Delivery, OutreachCampaign, SendBatch
from app.db.models.settings import ServiceSecret, SharedSettings
from app.outreach.rate_limit import SMTPRateLimitError
from app.outreach.smtp import SMTPPermanentError, SMTPTransientError
from app.repositories.settings import SHARED_SETTINGS_ID


SMTP_PAYLOAD = {
    "host": "smtp.example.com",
    "port": 465,
    "encryption": "tls",
    "username": "sender@example.com",
    "password": "smtp-password-never-return",
    "from_name": "Find Me Gamer",
    "reply_to": "team@example.com",
    "emails_per_minute": 10,
}


def test_smtp_routes_require_workspace_authentication(client) -> None:
    for method, path, payload in (
        ("get", "/api/v1/outreach/smtp", None),
        ("put", "/api/v1/outreach/smtp", SMTP_PAYLOAD),
        ("post", "/api/v1/outreach/smtp/test-connection", None),
        (
            "post",
            "/api/v1/outreach/smtp/test-email",
            {"recipient": "company@example.com"},
        ),
    ):
        kwargs = {"json": payload} if payload is not None else {}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "workspace_key_invalid"


def test_smtp_status_starts_unconfigured_with_safe_defaults(auth_client) -> None:
    response = auth_client.get("/api/v1/outreach/smtp")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "host": None,
        "port": None,
        "encryption": None,
        "username": None,
        "from_name": None,
        "reply_to": None,
        "emails_per_minute": 10,
        "last_test_status": None,
        "last_tested_at": None,
    }


def test_first_save_requires_password(auth_client) -> None:
    payload = {key: value for key, value in SMTP_PAYLOAD.items() if key != "password"}

    response = auth_client.put("/api/v1/outreach/smtp", json=payload)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "smtp_password_required"
    assert response.json()["error"]["retryable"] is False


def test_smtp_status_requires_complete_public_metadata_and_secret(
    auth_client, session: Session
) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)
    settings = session.get(SharedSettings, SHARED_SETTINGS_ID)
    assert settings is not None
    state = dict(settings.service_connection_state)
    state["smtp"] = {**state["smtp"], "host": ""}
    settings.service_connection_state = state
    session.flush()

    response = auth_client.get("/api/v1/outreach/smtp")

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["host"] is None


def test_smtp_save_persists_only_encrypted_secret_and_public_metadata(
    auth_client, session: Session
) -> None:
    response = auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)
    reread = auth_client.get("/api/v1/outreach/smtp")
    workspace = auth_client.get("/api/v1/session")
    session.expire_all()
    secret = session.scalar(
        select(ServiceSecret).where(ServiceSecret.service == "smtp")
    )
    settings = session.get(SharedSettings, SHARED_SETTINGS_ID)

    assert response.status_code == 200
    assert response.json() == reread.json()
    assert response.json() == {
        "configured": True,
        "host": "smtp.example.com",
        "port": 465,
        "encryption": "tls",
        "username": "sender@example.com",
        "from_name": "Find Me Gamer",
        "reply_to": "team@example.com",
        "emails_per_minute": 10,
        "last_test_status": None,
        "last_tested_at": None,
    }
    assert SMTP_PAYLOAD["password"] not in response.text
    assert secret is not None
    assert SMTP_PAYLOAD["password"].encode() not in secret.ciphertext
    assert SMTP_PAYLOAD["password"].encode() not in secret.nonce
    assert settings is not None
    assert "password" not in str(settings.service_connection_state)
    assert settings.service_connection_state["smtp"] == {
        "configured": True,
        "host": "smtp.example.com",
        "port": 465,
        "encryption": "tls",
        "username": "sender@example.com",
        "from_name": "Find Me Gamer",
        "reply_to": "team@example.com",
        "last_test_succeeded": None,
        "last_test_at": None,
    }
    assert workspace.json()["service_connections"]["smtp"] is True


def test_omitted_password_retains_credential_and_identical_save_preserves_test(
    auth_client, session: Session, smtp_gateway
) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)
    tested = auth_client.post("/api/v1/outreach/smtp/test-connection")
    session.expire_all()
    before = session.scalar(
        select(ServiceSecret).where(ServiceSecret.service == "smtp")
    )
    assert before is not None
    ciphertext = before.ciphertext

    payload = {key: value for key, value in SMTP_PAYLOAD.items() if key != "password"}
    saved = auth_client.put("/api/v1/outreach/smtp", json=payload)
    session.expire_all()
    after = session.scalar(select(ServiceSecret).where(ServiceSecret.service == "smtp"))

    assert tested.status_code == 200
    assert saved.json()["last_test_status"] == "success"
    assert saved.json()["last_tested_at"] == tested.json()["last_tested_at"]
    assert after is not None
    assert after.ciphertext == ciphertext
    assert len(smtp_gateway.probes) == 1


@pytest.mark.parametrize("change", [{"host": "mail.example.com"}, {"password": "new"}])
def test_connection_field_or_password_change_resets_last_test(
    auth_client, change: dict[str, object]
) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)
    tested = auth_client.post("/api/v1/outreach/smtp/test-connection")
    payload = {**SMTP_PAYLOAD, **change}

    updated = auth_client.put("/api/v1/outreach/smtp", json=payload)

    assert tested.json()["last_test_status"] == "success"
    assert updated.json()["last_test_status"] is None
    assert updated.json()["last_tested_at"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"host": "localhost"},
        {"host": "https://smtp.example.com"},
        {"host": "smtp example.com"},
        {"port": 0},
        {"port": 65_536},
        {"encryption": "ssl"},
        {"username": "not-an-email"},
        {"from_name": "   "},
        {"reply_to": "not-an-email"},
        {"emails_per_minute": 0},
        {"emails_per_minute": 61},
        {"unexpected": "field"},
    ],
)
def test_smtp_update_rejects_invalid_or_extra_fields(
    auth_client, change: dict[str, object]
) -> None:
    response = auth_client.put("/api/v1/outreach/smtp", json={**SMTP_PAYLOAD, **change})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"
    assert SMTP_PAYLOAD["password"] not in response.text


def test_connection_test_runs_outside_transaction_and_records_success(
    auth_client, session: Session, smtp_gateway
) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)
    smtp_gateway.before_call = lambda: (
        (_ for _ in ()).throw(
            AssertionError("database transaction held during SMTP probe")
        )
        if session.in_transaction()
        else None
    )

    response = auth_client.post("/api/v1/outreach/smtp/test-connection")

    assert response.status_code == 200
    assert response.json()["succeeded"] is True
    assert response.json()["last_test_status"] == "success"
    assert datetime.fromisoformat(response.json()["last_tested_at"])
    assert len(smtp_gateway.probes) == 1


@pytest.mark.parametrize("error_type", [SMTPPermanentError, SMTPTransientError])
def test_connection_failure_records_safe_status_without_upstream_text(
    auth_client, smtp_gateway, captured_logs, error_type
) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)
    smtp_gateway.error = error_type("upstream secret detail")

    response = auth_client.post("/api/v1/outreach/smtp/test-connection")

    assert response.status_code == 200
    assert response.json()["succeeded"] is False
    assert response.json()["last_test_status"] == "failure"
    assert "upstream secret detail" not in response.text
    assert "upstream secret detail" not in captured_logs.text


def test_missing_configuration_is_a_safe_conflict(auth_client) -> None:
    for path, payload in (
        ("/api/v1/outreach/smtp/test-connection", None),
        ("/api/v1/outreach/smtp/test-email", {"recipient": "company@example.com"}),
    ):
        kwargs = {"json": payload} if payload else {}
        response = auth_client.post(path, **kwargs)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "smtp_not_configured"


def test_stale_test_result_cannot_overwrite_changed_public_configuration(
    auth_client, session: Session, smtp_gateway
) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)

    def replace_configuration() -> None:
        settings = session.get(SharedSettings, SHARED_SETTINGS_ID)
        assert settings is not None
        metadata = dict(settings.service_connection_state)
        metadata["smtp"] = {**metadata["smtp"], "host": "changed.example.com"}
        settings.service_connection_state = metadata
        session.commit()

    smtp_gateway.before_call = replace_configuration

    response = auth_client.post("/api/v1/outreach/smtp/test-connection")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "smtp_configuration_changed"
    assert response.json()["error"]["retryable"] is True
    session.expire_all()
    secret = session.scalar(
        select(ServiceSecret).where(ServiceSecret.service == "smtp")
    )
    assert secret is not None
    assert secret.last_test_succeeded is None


def test_test_email_rate_limit_does_not_sleep_or_send(
    auth_client, smtp_gateway, smtp_rate_limiter
) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)
    smtp_rate_limiter.delay = 0.25

    response = auth_client.post(
        "/api/v1/outreach/smtp/test-email",
        json={"recipient": "company@example.com"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "smtp_rate_limited"
    assert response.json()["error"]["retryable"] is True
    assert smtp_gateway.sends == []


def test_limiter_failure_is_safe_and_does_not_send(
    auth_client, smtp_gateway, smtp_rate_limiter
) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)
    smtp_rate_limiter.error = SMTPRateLimitError("internal limiter detail")

    response = auth_client.post(
        "/api/v1/outreach/smtp/test-email",
        json={"recipient": "company@example.com"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "smtp_rate_limit_unavailable"
    assert response.json()["error"]["retryable"] is True
    assert "internal limiter detail" not in response.text
    assert smtp_gateway.sends == []


def test_test_email_sends_once_with_fixed_headers_and_creates_no_business_rows(
    auth_client, session: Session, smtp_gateway, smtp_rate_limiter
) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD)
    before = {
        model: session.scalar(select(func.count()).select_from(model))
        for model in (OutreachCampaign, SendBatch, Delivery)
    }
    smtp_rate_limiter.before_call = lambda: (
        (_ for _ in ()).throw(
            AssertionError("database transaction held during limiter call")
        )
        if session.in_transaction()
        else None
    )

    response = auth_client.post(
        "/api/v1/outreach/smtp/test-email",
        json={"recipient": "company@example.com"},
    )
    session.expire_all()
    after = {
        model: session.scalar(select(func.count()).select_from(model))
        for model in (OutreachCampaign, SendBatch, Delivery)
    }

    assert response.status_code == 200
    assert response.json()["succeeded"] is True
    assert smtp_rate_limiter.calls == [(str(SHARED_SETTINGS_ID), 10)]
    assert len(smtp_gateway.sends) == 1
    config, message = smtp_gateway.sends[0]
    assert config.username == "sender@example.com"
    assert message["From"] == "Find Me Gamer <sender@example.com>"
    assert message["Reply-To"] == "team@example.com"
    assert message["To"] == "company@example.com"
    assert message["Subject"] == "Find Me Gamer SMTP Test"
    assert "SMTP configuration is working" in message.get_content()
    assert after == before
