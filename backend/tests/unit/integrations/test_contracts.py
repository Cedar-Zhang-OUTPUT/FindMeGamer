import pytest
from pydantic import ValidationError

from app.analysis.contracts import Message
from app.integrations.errors import (
    InvalidModelOutput,
    PermanentIntegrationError,
    TransientIntegrationError,
)


@pytest.mark.parametrize("role", ["system", "user", "assistant"])
def test_message_accepts_only_supported_roles(role: str) -> None:
    assert Message(role=role, content="Bounded content").role == role


@pytest.mark.parametrize(
    "kwargs",
    [
        {"role": "tool", "content": "content"},
        {"role": "user", "content": ""},
        {"role": "user", "content": "x" * 131_073},
    ],
)
def test_message_rejects_unsupported_or_unbounded_input(
    kwargs: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        Message(**kwargs)


@pytest.mark.parametrize(
    "error_type",
    [TransientIntegrationError, PermanentIntegrationError, InvalidModelOutput],
)
def test_integration_errors_never_render_supplied_secret_context(
    error_type: type[Exception],
) -> None:
    secret = "canary-secret-auth-value"
    error = error_type("safe_code", secret)

    assert secret not in str(error)
    assert secret not in repr(error)
    assert "safe_code" in str(error)
