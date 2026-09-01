import logging

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from app.analysis.contracts import Message
from app.integrations.deepseek import DeepSeekGateway
from app.integrations.errors import (
    InvalidModelOutput,
    PermanentIntegrationError,
    TransientIntegrationError,
)


class GameExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


def test_deepseek_rejects_invalid_structured_output() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = DeepSeekGateway(api_key="test-key", http_client=client)

    with pytest.raises(InvalidModelOutput):
        gateway.complete_structured(
            "deepseek-v4-flash",
            [Message(role="user", content="Extract the game")],
            GameExtraction,
        )

    assert calls == 2


def test_deepseek_validates_directly_against_schema_in_one_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"title":"Elden Ring"}'}}]},
        )

    messages = [Message(role="user", content="Extract public game facts")]
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = DeepSeekGateway(
        api_key="deepseek-secret", http_client=client
    ).complete_structured("deepseek-v4-flash", messages, GameExtraction)

    assert result == GameExtraction(title="Elden Ring")
    assert len(requests) == 1
    body = requests[0].read().decode()
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer deepseek-secret"
    assert '"additionalProperties":false' in body
    assert '"required":["title"]' in body


def test_deepseek_repairs_once_without_mutating_caller_messages() -> None:
    requests: list[httpx.Request] = []
    original = [Message(role="user", content="Original prompt")]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        content = "not-json" if len(requests) == 1 else '{"title":"Repaired"}'
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = DeepSeekGateway(
        api_key="test-key", http_client=client
    ).complete_structured("deepseek-v4-flash", original, GameExtraction)

    assert result.title == "Repaired"
    assert len(requests) == 2
    assert original == [Message(role="user", content="Original prompt")]
    repair_body = requests[1].read().decode()
    assert "Repair" in repair_body
    assert "not-json" in repair_body


def test_deepseek_vision_uses_bounded_openai_multimodal_content() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"title":"Visual"}'}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = DeepSeekGateway(api_key="test-key", http_client=client).complete_vision(
        "deepseek-v4-flash-vision-exp",
        "Analyze only visible evidence",
        ["https://cdn.example/one.jpg", "https://cdn.example/two.jpg"],
        GameExtraction,
    )

    assert result.title == "Visual"
    payload = __import__("json").loads(requests[0].read())
    content = payload["messages"][0]["content"]
    assert content == [
        {"type": "text", "text": "Analyze only visible evidence"},
        {"type": "image_url", "image_url": {"url": "https://cdn.example/one.jpg"}},
        {"type": "image_url", "image_url": {"url": "https://cdn.example/two.jpg"}},
    ]


@pytest.mark.parametrize(
    ("model", "messages"),
    [
        ("", []),
        ("x" * 129, []),
        ("bad model", []),
        ("model", [Message(role="user", content="x")] * 101),
    ],
)
def test_deepseek_rejects_unbounded_structured_inputs(
    model: str, messages: list[Message]
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("network called"))
        )
    )

    with pytest.raises(PermanentIntegrationError, match="deepseek_input_invalid"):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_structured(
            model, messages, GameExtraction
        )


@pytest.mark.parametrize(
    ("prompt", "images"),
    [
        ("", ["https://cdn.example/a.jpg"]),
        ("prompt", []),
        ("prompt", ["https://cdn.example/a.jpg"] * 13),
        ("prompt", ["http://cdn.example/a.jpg"]),
        ("prompt", ["//cdn.example/a.jpg"]),
        ("prompt", ["https://user@cdn.example/a.jpg"]),
    ],
)
def test_deepseek_rejects_invalid_vision_inputs(prompt: str, images: list[str]) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("network called"))
        )
    )

    with pytest.raises(PermanentIntegrationError, match="deepseek_input_invalid"):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_vision(
            "vision-model", prompt, images, GameExtraction
        )


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_deepseek_classifies_ordinary_client_errors_as_permanent(status: int) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="provider body secret")
        )
    )

    with pytest.raises(PermanentIntegrationError, match="deepseek_request_rejected"):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_structured(
            "model", [], GameExtraction
        )


@pytest.mark.parametrize("status", [429, 500, 503])
def test_deepseek_classifies_rate_limit_and_server_errors_as_transient(
    status: int,
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={}))
    )

    with pytest.raises(TransientIntegrationError, match="deepseek_unavailable"):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_structured(
            "model", [], GameExtraction
        )


def test_deepseek_timeout_redacts_authorization_prompt_and_output(caplog) -> None:
    secret = "deepseek-auth-canary"
    prompt = "prompt-canary-private"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.WriteTimeout(
            f"authorization={secret}; prompt={prompt}", request=request
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.DEBUG), pytest.raises(
        TransientIntegrationError, match="deepseek_unavailable"
    ) as caught:
        DeepSeekGateway(api_key=secret, http_client=client).complete_structured(
            "model", [Message(role="user", content=prompt)], GameExtraction
        )

    rendered = f"{caught.value!s}{caught.value!r}{caplog.text}"
    assert secret not in rendered
    assert prompt not in rendered


@pytest.mark.parametrize(
    "response_json",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": "{}", "refusal": "No"}}]},
        {
            "choices": [
                {"message": {"content": '{"title":"one"}'}},
                {"message": {"content": '{"title":"two"}'}},
            ]
        },
    ],
)
def test_deepseek_malformed_envelope_does_not_trigger_repair(
    response_json: object,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=response_json)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(PermanentIntegrationError, match="deepseek_response_invalid"):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_structured(
            "model", [], GameExtraction
        )

    assert calls == 1


def test_deepseek_oversized_output_does_not_trigger_repair() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"x" * 2_100_000)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(PermanentIntegrationError, match="deepseek_response_too_large"):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_structured(
            "model", [], GameExtraction
        )

    assert calls == 1


def test_deepseek_respects_client_ownership_and_closes_owned_client() -> None:
    caller_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )
    injected = DeepSeekGateway(api_key="test-key", http_client=caller_client)
    owned = DeepSeekGateway(api_key="test-key", base_url="http://localhost:18082/v1")

    injected.close()
    owned.close()

    assert not caller_client.is_closed
    assert owned.is_closed
