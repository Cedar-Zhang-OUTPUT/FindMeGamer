import logging
from io import StringIO

from app.core.logging import configure_request_logging, log_request
from app.core.security import hash_workspace_key
from app.main import create_app


class AlwaysAllow:
    def allow(self, workspace_digest: str, client_address: str) -> bool:
        return True


def test_create_app_enables_safe_logger_and_disables_raw_access_logger() -> None:
    safe_logger = logging.getLogger("app.requests")
    access_logger = logging.getLogger("uvicorn.access")
    safe_logger.disabled = True
    safe_logger.setLevel(logging.WARNING)
    access_logger.disabled = False

    create_app(
        workspace_key_hash=hash_workspace_key("logging-test-key"),
        rate_limiter=AlwaysAllow(),
    )

    assert safe_logger.isEnabledFor(logging.INFO)
    assert not safe_logger.disabled
    assert access_logger.disabled


def test_production_logging_emits_safe_request_event_and_suppresses_uvicorn_access() -> None:
    stream = StringIO()
    configure_request_logging(stream=stream)

    log_request(
        method="GET",
        route="/api/v1/session",
        status=200,
        duration_ms=1.25,
        correlation_id="logging-test_123",
    )
    logging.getLogger("uvicorn.access").info(
        '127.0.0.1 - "GET /r/example?response_token=never-log-me HTTP/1.1" 200'
    )

    output = stream.getvalue()
    assert '"route":"/api/v1/session"' in output
    assert '"correlation_id":"logging-test_123"' in output
    assert "response_token" not in output
    assert "never-log-me" not in output
    assert logging.getLogger("app.requests").isEnabledFor(logging.INFO)
    assert logging.getLogger("uvicorn.access").disabled
