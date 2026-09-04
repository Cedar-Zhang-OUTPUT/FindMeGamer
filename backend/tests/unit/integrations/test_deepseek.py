import json
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


def test_deepseek_first_structured_request_uses_json_object_with_actual_schema() -> (
    None
):
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
    payload = json.loads(requests[0].read())
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer deepseek-secret"
    assert payload["response_format"] == {"type": "json_object"}
    instruction = payload["messages"][0]
    assert instruction["role"] == "system"
    prefix = (
        "Return exactly one JSON value that validates against this JSON Schema. "
        "Return no Markdown, prose, or commentary. JSON Schema: "
    )
    assert instruction["content"].startswith(prefix)
    assert json.loads(instruction["content"][len(prefix) :]) == {
        "additionalProperties": False,
        "properties": {"title": {"title": "Title", "type": "string"}},
        "required": ["title"],
        "title": "GameExtraction",
        "type": "object",
    }
    assert payload["messages"][1:] == [
        {"role": "user", "content": "Extract public game facts"}
    ]


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


def test_deepseek_first_vision_request_uses_json_object_with_actual_schema() -> None:
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
    payload = json.loads(requests[0].read())
    assert payload["response_format"] == {"type": "json_object"}
    instruction = payload["messages"][0]
    assert instruction["role"] == "system"
    prefix = (
        "Return exactly one JSON value that validates against this JSON Schema. "
        "Return no Markdown, prose, or commentary. JSON Schema: "
    )
    assert instruction["content"].startswith(prefix)
    assert json.loads(instruction["content"][len(prefix) :]) == {
        "additionalProperties": False,
        "properties": {"title": {"title": "Title", "type": "string"}},
        "required": ["title"],
        "title": "GameExtraction",
        "type": "object",
    }
    content = payload["messages"][1]["content"]
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
        ("prompt", ["http://localhost/a.jpg"]),
        ("prompt", ["http://127.0.0.1/a.jpg"]),
        ("prompt", ["http://[::1]/a.jpg"]),
        ("prompt", ["//cdn.example/a.jpg"]),
        ("prompt", ["https://user@cdn.example/a.jpg"]),
        ("prompt", ["https://cdn.example/a.jpg#fragment"]),
        ("prompt", ["https://cdn.example/a.jpg\x00"]),
        ("prompt", ["ftp://cdn.example/a.jpg"]),
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


@pytest.mark.parametrize(
    "image_url",
    [
        "https://%00.example/image.jpg",
        "https://%65xample.com/image.jpg",
        "https://exa\u202emple.com/image.jpg",
        "https://xn--/image.jpg",
        "https://_bad.example/image.jpg",
        "https://-bad.example/image.jpg",
        "https://bad-.example/image.jpg",
        "https://bad..example/image.jpg",
        f"https://{'a' * 64}.example/image.jpg",
        "https://example.com/%00.jpg",
        "https://example.com/%20.jpg",
        "https://example.com/%7F.jpg",
        "https://example.com/%C2%A0.jpg",
        "https://example.com/%E2%80%AE.jpg",
        "https://example.com/image.jpg?signature=%0Asecret",
        "https://example.com/image.jpg?signature=%ZZ",
        "https://example.com/\u200d.jpg",
        "https://example.com/\ud800.jpg",
        "https://example.com/image.jpg#",
        "https://example.com:bad/image.jpg",
        "https://example.com:0/image.jpg",
        "https://example.com:65536/image.jpg",
        "https:////example.com/image.jpg",
        "https://example.com\\@evil.example/image.jpg",
        "https://127.0.0.1/image.jpg",
        "https://[::1]/image.jpg",
        "https://169.254.169.254/image.jpg",
        "https://10.0.0.1/image.jpg",
        "https://224.0.0.1/image.jpg",
        "https://240.0.0.1/image.jpg",
        "https://0.0.0.0/image.jpg",
        "https://8.8.8.8/image.jpg",
        "https://[2606:4700:4700::1111]/image.jpg",
        "https://2130706433/image.jpg",
        "https://017700000001/image.jpg",
        "https://0x7f000001/image.jpg",
        "https://0177.0.0.1/image.jpg",
        "https://0x7f.0x0.0x0.0x1/image.jpg",
        "https://127.0.0.0x1/image.jpg",
        "https://0177.0x0.0.1/image.jpg",
        "https://0x7f.1/image.jpg",
        "https://127.1/image.jpg",
        "https://127.0.1/image.jpg",
        "https://127.0.0.1./image.jpg",
        "https://１２７.０.０.１/image.jpg",
        "https://١٢٧.٠.٠.١/image.jpg",
        f"https://cdn.example/{'a' * 2_049}",
        f"https://cdn.example/{'中' * 680}",
    ],
)
def test_deepseek_rejects_adversarial_image_url_before_provider_call(
    image_url: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"title":"bad"}'}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(PermanentIntegrationError, match="deepseek_input_invalid"):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_vision(
            "vision-model", "prompt", [image_url], GameExtraction
        )

    assert calls == 0


@pytest.mark.parametrize(
    "image_url",
    [
        "https://cdn.example/image.jpg",
        "https://images.example.com:8443/path/image.jpg?"
        "X-Amz-Signature=abc%2Fdef%2Bghi%3D",
        "https://例子.测试/image.jpg",
        "https://cdn.example/a%2Fb.jpg?q=%E4%B8%AD",
        "https://127.0.0.1.images.example/image.jpg",
        "https://0x7f.images.example/image.jpg",
    ],
)
def test_deepseek_accepts_strict_public_https_image_url(image_url: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"title":"valid"}'}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = DeepSeekGateway(api_key="test-key", http_client=client).complete_vision(
        "vision-model", "prompt", [image_url], GameExtraction
    )

    assert result.title == "valid"
    assert len(requests) == 1


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

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(
            TransientIntegrationError, match="deepseek_unavailable"
        ) as caught,
    ):
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


def test_deepseek_stops_streaming_at_cap_and_closes_lying_length_response(
    monkeypatch, gateway_byte_stream_factory, caplog
) -> None:
    monkeypatch.setattr("app.integrations.deepseek.MAX_DEEPSEEK_RESPONSE_BYTES", 5)
    secret = "deepseek-unread-stream-canary"
    stream = gateway_byte_stream_factory([b"1234", b"56", secret.encode()])
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            headers={"Content-Length": "1"},
            stream=stream,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(
            PermanentIntegrationError, match="deepseek_response_too_large"
        ) as caught,
    ):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_structured(
            "model", [], GameExtraction
        )

    assert requests == 1
    assert stream.yielded == 2
    assert stream.closed is True
    assert secret not in f"{caught.value!s}{caught.value!r}{caplog.text}"


def test_deepseek_streaming_read_timeout_is_transient_and_closes(
    gateway_byte_stream_factory, caplog
) -> None:
    stream = gateway_byte_stream_factory(
        [b'{"choices":', b"unused"],
        error_after=1,
    )
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, stream=stream)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(
            TransientIntegrationError, match="deepseek_unavailable"
        ) as caught,
    ):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_structured(
            "model", [], GameExtraction
        )

    assert requests == 1
    assert stream.yielded == 1
    assert stream.closed is True
    assert "gateway-stream-timeout-canary" not in (
        f"{caught.value!s}{caught.value!r}{caplog.text}"
    )


def test_deepseek_does_not_read_server_error_body(
    gateway_byte_stream_factory, caplog
) -> None:
    secret = "deepseek-server-body-canary"
    stream = gateway_byte_stream_factory([secret.encode(), b"unused"])
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(503, stream=stream)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(
            TransientIntegrationError, match="deepseek_unavailable"
        ) as caught,
    ):
        DeepSeekGateway(api_key="test-key", http_client=client).complete_structured(
            "model", [], GameExtraction
        )

    assert requests == 1
    assert stream.yielded == 0
    assert stream.closed is True
    assert secret not in f"{caught.value!s}{caught.value!r}{caplog.text}"


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
