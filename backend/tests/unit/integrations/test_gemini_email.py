import json
import logging

import httpx
import pytest

from app.analysis.contracts import CreatorSource
from app.integrations.errors import (
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.integrations.gemini_email import (
    MAX_GEMINI_EMAIL_RESPONSE_BYTES,
    GeminiEmailRecord,
    GeminiEmailResearchGateway,
)


def _creator_source() -> CreatorSource:
    return CreatorSource(
        channel_id="UC123456",
        canonical_url="https://www.youtube.com/channel/UC123456",
        title="Example Creator",
        description="Public gaming channel",
        custom_url="@examplecreator",
        uploads_playlist_id="UU123456",
        videos=(),
        raw_channel={},
        raw_playlist_pages=(),
        raw_video_responses=(),
    )


def _gemini_response(email_info: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "internal reasoning"},
                            {
                                "text": "```json\n"
                                + json.dumps({"email_info": email_info})
                                + "\n```"
                            },
                        ]
                    }
                }
            ]
        },
    )


def test_gateway_sends_validated_search_contract_and_normalizes_records() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _gemini_response(
            [
                {
                    "email": " BUSINESS@Example.COM ",
                    "usage": " Sponsorships ",
                    "source": " https://example.com/contact ",
                },
                {
                    "email": "business@example.com",
                    "usage": "Duplicate",
                    "source": "https://example.com/duplicate",
                },
                {
                    "email": "None found",
                    "usage": "General",
                    "source": "https://example.com/about",
                },
            ]
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = GeminiEmailResearchGateway(
        api_key="google-ai-secret", http_client=client
    ).find_public_emails(_creator_source(), existing_contacts=("manager@example.net",))

    assert result == (
        GeminiEmailRecord(
            email="business@example.com",
            usage="Sponsorships",
            source="https://example.com/contact",
        ),
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == ("/v1beta/models/gemini-3.8-flash:generateContent")
    assert request.url.query == b""
    assert request.headers.get_list("x-goog-api-key") == ["google-ai-secret"]
    payload = json.loads(request.read())
    assert payload["tools"] == [{"googleSearch": {}}, {"urlContext": {}}]
    assert payload["generationConfig"] == {
        "responseMimeType": "application/json",
        "responseJsonSchema": {
            "type": "object",
            "properties": {
                "email_info": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string"},
                            "usage": {"type": "string"},
                            "source": {"type": "string"},
                        },
                        "propertyOrdering": ["email", "usage", "source"],
                        "required": ["email", "usage", "source"],
                    },
                }
            },
            "propertyOrdering": ["email_info"],
            "required": ["email_info"],
        },
        "maxOutputTokens": 65_536,
        "thinkingConfig": {"thinkingLevel": "MEDIUM"},
    }
    system_prompt = payload["systemInstruction"]["parts"][0]["text"]
    target_prompt = payload["contents"][0]["parts"][0]["text"]
    assert "after two attempts" in system_prompt
    assert "Do not guess email patterns" in target_prompt
    assert "Example Creator" in target_prompt
    assert "https://www.youtube.com/channel/UC123456" in target_prompt
    assert "manager@example.net" in target_prompt
    assert request.extensions["timeout"]["read"] == 180.0


def test_gateway_retries_valid_empty_four_times_then_returns_empty() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _gemini_response([])

    gateway = GeminiEmailResearchGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    assert gateway.find_public_emails(_creator_source()) == ()
    assert calls == 4
    assert sleeps == [1.0, 1.0, 1.0]


def test_gateway_stops_immediately_after_first_valid_result() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _gemini_response(
            [
                {
                    "email": "creator@example.com",
                    "usage": "Business",
                    "source": "https://example.com/about",
                }
            ]
        )

    gateway = GeminiEmailResearchGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("unexpected sleep")),
    )

    assert gateway.find_public_emails(_creator_source())[0].email == (
        "creator@example.com"
    )
    assert calls == 1


def test_gateway_retries_when_email_has_no_exact_public_source_url() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _gemini_response(
                [
                    {
                        "email": "creator@example.com",
                        "usage": "Business",
                        "source": "YouTube About page",
                    }
                ]
            )
        return _gemini_response(
            [
                {
                    "email": "creator@example.com",
                    "usage": "Business",
                    "source": "https://www.youtube.com/@creator/about",
                }
            ]
        )

    gateway = GeminiEmailResearchGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    assert gateway.find_public_emails(_creator_source()) == (
        GeminiEmailRecord(
            email="creator@example.com",
            usage="Business",
            source="https://www.youtube.com/@creator/about",
        ),
    )
    assert calls == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_gateway_retries_transient_http_failures(status_code: int) -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status_code, text="unsafe provider detail")
        return _gemini_response(
            [
                {
                    "email": "recovered@example.com",
                    "usage": "Business",
                    "source": "https://example.com/contact",
                }
            ]
        )

    gateway = GeminiEmailResearchGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    assert gateway.find_public_emails(_creator_source())[0].email == (
        "recovered@example.com"
    )
    assert calls == 2
    assert sleeps == [1.0]


def test_gateway_retries_transport_failure() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("provider offline", request=request)
        return _gemini_response(
            [
                {
                    "email": "recovered@example.com",
                    "usage": "Business",
                    "source": "https://example.com/contact",
                }
            ]
        )

    gateway = GeminiEmailResearchGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    assert gateway.find_public_emails(_creator_source())[0].email == (
        "recovered@example.com"
    )
    assert calls == 2
    assert sleeps == [1.0]


def test_gateway_rejects_permanent_http_failure_without_retry_or_secret_leak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "google-ai-key-canary"
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text=f"provider echoed {secret}")

    gateway = GeminiEmailResearchGateway(
        api_key=secret,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("unexpected retry")),
    )

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(
            PermanentIntegrationError, match="public_page_request_rejected"
        ) as caught,
    ):
        gateway.find_public_emails(_creator_source())

    assert calls == 1
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert secret not in caplog.text


def test_gateway_reports_exhausted_transient_failures_safely() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, text="rate limited")

    gateway = GeminiEmailResearchGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    with pytest.raises(TransientIntegrationError, match="public_page_unavailable"):
        gateway.find_public_emails(_creator_source())

    assert calls == 4
    assert sleeps == [1.0, 1.0, 1.0]


def test_gateway_retries_malformed_output_then_fails_safely() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "not structured JSON"}]}}
                ]
            },
        )

    gateway = GeminiEmailResearchGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    with pytest.raises(PermanentIntegrationError, match="public_page_response_invalid"):
        gateway.find_public_emails(_creator_source())

    assert calls == 4
    assert sleeps == [1.0, 1.0, 1.0]


def test_gateway_rejects_oversized_response_before_parsing() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-length": str(MAX_GEMINI_EMAIL_RESPONSE_BYTES + 1)},
            content=b"{}",
        )

    gateway = GeminiEmailResearchGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("unexpected retry")),
    )

    with pytest.raises(PermanentIntegrationError, match="public_page_too_large"):
        gateway.find_public_emails(_creator_source())

    assert calls == 1


@pytest.mark.parametrize("api_key", ["", "has whitespace", "bad\nkey"])
def test_gateway_rejects_invalid_key_as_configuration(api_key: str) -> None:
    with pytest.raises(
        PermanentIntegrationError, match="analysis_configuration_invalid"
    ):
        GeminiEmailResearchGateway(api_key=api_key)


def test_gateway_owns_only_the_default_http_client() -> None:
    injected = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("network called"))
        )
    )
    injected_gateway = GeminiEmailResearchGateway(
        api_key="test-key", http_client=injected
    )
    injected_gateway.close()
    assert not injected.is_closed

    with GeminiEmailResearchGateway(api_key="test-key") as owned_gateway:
        assert not owned_gateway.is_closed
    assert owned_gateway.is_closed
