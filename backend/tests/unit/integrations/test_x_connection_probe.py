import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.connection_probe import ProductionConnectionProbe


def make_probe(client, **kwargs):
    return ProductionConnectionProbe(
        deepseek_base_url="https://api.deepseek.com",
        youtube_base_url="https://www.googleapis.com/youtube/v3",
        google_ai_base_url="https://generativelanguage.googleapis.com/v1beta/models",
        http_client=client,
        **kwargs,
    )


def test_x_probe_uses_usage_access_not_paid_search_and_keeps_secret_out_of_url():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"data": {"project_usage": 2}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert make_probe(client).test_connection("x", "x-bearer-canary") is True
    assert len(seen) == 1
    assert seen[0].url == "https://api.x.com/2/usage/tweets?days=1"
    assert seen[0].headers["authorization"] == "Bearer x-bearer-canary"
    assert "x-bearer-canary" not in str(seen[0].url)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
def test_x_probe_rejections_fail_without_retry_redirect_or_error_echo(status):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://other.invalid"},
            text="x-bearer-canary",
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert make_probe(client).test_connection("x", "x-bearer-canary") is False
    assert len(seen) == 1


def test_x_probe_timeout_returns_false_without_secret_exception():
    seen = []

    def handle(request):
        seen.append(request)
        raise httpx.ReadTimeout("x-bearer-canary", request=request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert make_probe(client).test_connection("x", "x-bearer-canary") is False
    assert len(seen) == 1


def test_x_probe_accepts_server_configured_loopback_fixture_origin():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        probe = make_probe(client, x_base_url="http://127.0.0.1:9099/2/")
        assert probe.test_connection("x", "fixture-bearer") is True
    assert seen[0].url == "http://127.0.0.1:9099/2/usage/tweets?days=1"


@pytest.mark.parametrize("url", ["http://api.x.com/2", "https://user:pass@api.x.com/2"])
def test_x_server_base_url_rejects_cleartext_or_embedded_credentials(url):
    with pytest.raises(ValidationError):
        Settings(x_api_base_url=url)
