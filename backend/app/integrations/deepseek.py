import json
import re
import unicodedata
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any, TypeVar
from urllib.parse import unquote_to_bytes, urlsplit

import httpx
import idna
from pydantic import BaseModel, ValidationError

from app.analysis.contracts import Message
from app.core.config import validate_external_base_url
from app.integrations.errors import (
    InvalidModelOutput,
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.integrations.http import (
    InvalidContentLength,
    ResponseTooLarge,
    read_bounded_bytes,
    streaming_response,
)

T = TypeVar("T", bound=BaseModel)
DEFAULT_DEEPSEEK_API_BASE_URL = "https://api.deepseek.com"
MAX_DEEPSEEK_RESPONSE_BYTES = 2_000_000
MAX_MODEL_CONTENT_BYTES = 1_000_000
MAX_REPAIR_CONTEXT_CHARACTERS = 8_192
MAX_SCHEMA_BYTES = 200_000
MAX_MESSAGES = 100
MAX_TOTAL_MESSAGE_CHARACTERS = 1_000_000
MAX_VISION_IMAGES = 12
MAX_MODEL_OUTPUT_TOKENS = 384 * 1_024
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=20.0, pool=5.0)
_model_name = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_dns_label = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_hex_pair = re.compile(r"^[0-9A-Fa-f]{2}$")
_numeric_host_label = re.compile(r"^(?:[0-9]+|0[xX][0-9A-Fa-f]+)$")


@dataclass(frozen=True, slots=True)
class _DeepSeekUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class DeepSeekGateway:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_DEEPSEEK_API_BASE_URL,
        http_client: httpx.Client | None = None,
    ) -> None:
        _validate_api_key(api_key)
        self._api_key = api_key
        self._base_url = validate_external_base_url(base_url)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=HTTP_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        )

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DeepSeekGateway":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def complete_structured(
        self,
        model: str,
        messages: list[Message],
        schema: type[T],
        *,
        max_tokens: int | None = None,
    ) -> T:
        _validate_model(model)
        _validate_messages(messages)
        request_messages = [message.model_dump(mode="json") for message in messages]
        return self._complete(
            model,
            request_messages,
            schema,
            max_tokens=max_tokens,
        )

    def complete_vision(
        self,
        model: str,
        prompt: str,
        image_urls: list[str],
        schema: type[T],
        *,
        max_tokens: int | None = None,
    ) -> T:
        _validate_model(model)
        if (
            not isinstance(prompt, str)
            or not prompt
            or len(prompt) > 100_000
            or not isinstance(image_urls, list)
            or not 1 <= len(image_urls) <= MAX_VISION_IMAGES
        ):
            raise PermanentIntegrationError("deepseek_input_invalid")
        for image_url in image_urls:
            _validate_image_url(image_url)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(
            {"type": "image_url", "image_url": {"url": image_url}}
            for image_url in image_urls
        )
        return self._complete(
            model,
            [{"role": "user", "content": content}],
            schema,
            max_tokens=max_tokens,
        )

    def _complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        schema: type[T],
        *,
        max_tokens: int | None,
    ) -> T:
        schema_payload = _schema_payload(schema)
        output_budget = _resolve_max_tokens(schema, max_tokens)
        request_messages = [_schema_instruction(schema_payload), *messages]
        content = self._request(
            model,
            request_messages,
            max_tokens=output_budget,
        )
        try:
            return schema.model_validate_json(content)
        except (ValidationError, ValueError):
            repair_messages = [
                *request_messages,
                *_repair_messages(content, schema_payload),
            ]
        repaired = self._request(
            model,
            repair_messages,
            max_tokens=output_budget,
        )
        try:
            return schema.model_validate_json(repaired)
        except (ValidationError, ValueError):
            raise InvalidModelOutput("deepseek_model_output_invalid") from None

    def _request(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            # V4 defaults to thinking, whose reasoning tokens consume this same
            # budget before any schema JSON is emitted.
            "thinking": {"type": "disabled"},
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            with streaming_response(
                self._client,
                "POST",
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                auth=None,
                timeout=HTTP_TIMEOUT,
                follow_redirects=False,
            ) as response:
                if response.status_code == 429 or response.status_code >= 500:
                    raise TransientIntegrationError("deepseek_unavailable")
                if response.status_code >= 400:
                    raise PermanentIntegrationError("deepseek_request_rejected")
                body = read_bounded_bytes(
                    response,
                    max_bytes=MAX_DEEPSEEK_RESPONSE_BYTES,
                )
        except ResponseTooLarge:
            raise PermanentIntegrationError("deepseek_response_too_large") from None
        except InvalidContentLength:
            raise PermanentIntegrationError("deepseek_response_invalid") from None
        except httpx.TransportError:
            raise TransientIntegrationError("deepseek_unavailable") from None
        try:
            envelope = json.loads(body)
        except (UnicodeDecodeError, ValueError):
            raise PermanentIntegrationError("deepseek_response_invalid") from None
        return _extract_content(envelope)


def _validate_api_key(api_key: str) -> None:
    if (
        not isinstance(api_key, str)
        or not api_key
        or len(api_key) > 16_384
        or any(character.isspace() or ord(character) < 32 for character in api_key)
    ):
        raise PermanentIntegrationError("deepseek_configuration_invalid")


def _validate_model(model: str) -> None:
    if not isinstance(model, str) or not _model_name.fullmatch(model):
        raise PermanentIntegrationError("deepseek_input_invalid")


def _validate_messages(messages: object) -> None:
    if (
        not isinstance(messages, list)
        or len(messages) > MAX_MESSAGES
        or not all(isinstance(message, Message) for message in messages)
        or sum(len(message.content) for message in messages)
        > MAX_TOTAL_MESSAGE_CHARACTERS
    ):
        raise PermanentIntegrationError("deepseek_input_invalid")


def _resolve_max_tokens(schema: type[T], override: int | None) -> int | None:
    value = override
    if value is None:
        value = getattr(schema, "deepseek_max_tokens", None)
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= MAX_MODEL_OUTPUT_TOKENS:
        raise PermanentIntegrationError("deepseek_input_invalid")
    return value


def _validate_image_url(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2_048
        or len(value.encode("utf-8", errors="surrogatepass")) > 2_048
        or not value.startswith("https://")
        or "\\" in value
        or "#" in value
        or _has_unsafe_url_characters(value)
    ):
        raise PermanentIntegrationError("deepseek_input_invalid")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or "%" in parsed.netloc
            or (port is not None and port == 0)
        ):
            raise ValueError("invalid URL authority")
        _validate_dns_hostname(hostname)
        _validate_percent_encoded_component(parsed.path)
        _validate_percent_encoded_component(parsed.query)
    except (ValueError, UnicodeError, idna.IDNAError):
        raise PermanentIntegrationError("deepseek_input_invalid") from None


def _has_unsafe_url_characters(value: str) -> bool:
    return any(
        character.isspace() or unicodedata.category(character).startswith("C")
        for character in value
    )


def _validate_dns_hostname(hostname: str) -> None:
    try:
        ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("IP literals are not accepted")
    ascii_hostname = idna.encode(
        hostname,
        strict=True,
        uts46=False,
        std3_rules=True,
    ).decode("ascii")
    labels = ascii_hostname.split(".")
    if (
        len(ascii_hostname) > 253
        or len(labels) < 2
        or any(not _dns_label.fullmatch(label) for label in labels)
        or all(_numeric_host_label.fullmatch(label) for label in labels)
    ):
        raise ValueError("invalid DNS hostname")


def _validate_percent_encoded_component(component: str) -> None:
    position = 0
    while position < len(component):
        if component[position] != "%":
            position += 1
            continue
        if position + 2 >= len(component) or not _hex_pair.fullmatch(
            component[position + 1 : position + 3]
        ):
            raise ValueError("invalid percent encoding")
        position += 3
    decoded = unquote_to_bytes(component).decode("utf-8")
    if "\\" in decoded or _has_unsafe_url_characters(decoded):
        raise ValueError("unsafe URL component")


def _schema_payload(schema: type[T]) -> dict[str, Any]:
    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        raise PermanentIntegrationError("deepseek_input_invalid")
    generated = schema.model_json_schema()
    encoded = json.dumps(
        generated, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(encoded.encode("utf-8")) > MAX_SCHEMA_BYTES:
        raise PermanentIntegrationError("deepseek_input_invalid")
    return {"title": schema.__name__[:64] or "StructuredOutput", "schema": generated}


def _schema_instruction(schema_payload: dict[str, Any]) -> dict[str, str]:
    schema_json = json.dumps(
        schema_payload["schema"],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return {
        "role": "system",
        "content": (
            "Return exactly one JSON value that validates against this JSON Schema. "
            "Return no Markdown, prose, or commentary. "
            f"JSON Schema: {schema_json}"
        ),
    }


def _extract_content(envelope: object) -> str:
    if not isinstance(envelope, dict):
        raise PermanentIntegrationError("deepseek_response_invalid")
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise PermanentIntegrationError("deepseek_response_invalid")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise PermanentIntegrationError("deepseek_response_invalid")
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise TransientIntegrationError("deepseek_model_output_invalid")
    if finish_reason == "insufficient_system_resource":
        raise TransientIntegrationError("deepseek_unavailable")
    if finish_reason not in (None, "stop"):
        raise PermanentIntegrationError("deepseek_response_invalid")
    _parse_usage(envelope.get("usage"))
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("refusal"):
        raise PermanentIntegrationError("deepseek_response_invalid")
    content = message.get("content")
    if (
        not isinstance(content, str)
        or not content
        or len(content.encode("utf-8")) > MAX_MODEL_CONTENT_BYTES
    ):
        raise PermanentIntegrationError("deepseek_response_invalid")
    return content


def _parse_usage(value: object) -> _DeepSeekUsage | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PermanentIntegrationError("deepseek_response_invalid")
    return _DeepSeekUsage(
        prompt_tokens=_usage_token_count(value.get("prompt_tokens")),
        completion_tokens=_usage_token_count(value.get("completion_tokens")),
        total_tokens=_usage_token_count(value.get("total_tokens")),
    )


def _usage_token_count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise PermanentIntegrationError("deepseek_response_invalid")
    return value


def _repair_messages(
    invalid_content: str, schema_payload: dict[str, Any]
) -> list[dict[str, str]]:
    schema_json = json.dumps(
        schema_payload["schema"],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    context = invalid_content[:MAX_REPAIR_CONTEXT_CHARACTERS]
    instruction = (
        "Repair the previous assistant output. Return exactly one JSON value that "
        "validates against this JSON Schema, with no Markdown or commentary. "
        f"JSON Schema: {schema_json}"
    )
    return [
        {"role": "assistant", "content": context},
        {"role": "user", "content": instruction},
    ]
