import json
import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any, TypeVar
from urllib.parse import unquote_to_bytes, urlsplit

import httpx
import idna
from pydantic import BaseModel, ValidationError

from app.analysis.contracts import Message
from app.analysis.evidence_binding import normalize_evidence_json
from app.core.config import validate_external_base_url
from app.core.analysis_diagnostics import (
    model_call,
    response_metadata,
    failure_category,
)
from app.integrations.errors import (
    InvalidModelOutput,
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.integrations.creator_brief_repair import repair_creator_brief_text
from app.integrations.http import (
    InvalidContentLength,
    ResponseTooLarge,
    read_bounded_bytes,
    streaming_response,
)
from app.integrations.vision_images import VisionImageLoader
from app.schemas.ai_creator_map_reduce import CreatorBriefSynthesis

T = TypeVar("T", bound=BaseModel)
DEFAULT_DEEPSEEK_API_BASE_URL = "https://api.deepseek.com"
MAX_DEEPSEEK_RESPONSE_BYTES = 2_000_000
MAX_MODEL_CONTENT_BYTES = 1_000_000
MAX_REPAIR_CONTEXT_CHARACTERS = 8_192
MAX_SCHEMA_BYTES = 200_000
MAX_MESSAGES = 100
MAX_TOTAL_MESSAGE_CHARACTERS = 1_000_000
MAX_VISION_IMAGES = 12
MAX_VISION_DOWNLOAD_WORKERS = 4
# Leave room below the provider's 48 MiB request limit for prompts and repair.
MAX_VISION_INLINE_CHARACTERS = 24 * 1_024 * 1_024
MAX_MODEL_OUTPUT_TOKENS = 384 * 1_024
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=20.0, pool=5.0)
_model_name = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_dns_label = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_hex_pair = re.compile(r"^[0-9A-Fa-f]{2}$")
_numeric_host_label = re.compile(r"^(?:[0-9]+|0[xX][0-9A-Fa-f]+)$")
logger = logging.getLogger(__name__)
_VALIDATION_REASON_CODES = {
    "unavailable visual analysis requires a reason and unavailable claims": "visual_unavailable_shape_invalid",
    "available visual analysis cannot carry an unavailable reason": "visual_available_reason_invalid",
    "available visual analysis requires an available claim": "visual_available_claim_missing",
    "available visual claims require visual-observation evidence": "visual_claim_evidence_kind_invalid",
    "visual observations must reference a visual asset": "visual_asset_source_type_required",
    "text must be nonblank without surrounding whitespace": "text_blank_or_untrimmed",
    "text contains unsupported control characters": "text_control_characters",
    "text contains control characters": "text_control_characters",
    "keyword phrase contains unsafe query syntax": "keyword_unsafe_query_syntax",
    "keyword phrase must contain a letter or digit": "keyword_alphanumeric_required",
    "query terms must be unique": "keyword_duplicate_terms",
    "query platforms must exactly match requested platforms": "planning_platform_mismatch",
}


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
        image_loader: VisionImageLoader | None = None,
    ) -> None:
        _validate_api_key(api_key)
        self._api_key = api_key
        self._base_url = validate_external_base_url(base_url)
        self._owns_client = http_client is None
        # Image fetching uses its own pinned transport, never the API client or key.
        self._image_loader = image_loader or VisionImageLoader()
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
        with ThreadPoolExecutor(max_workers=MAX_VISION_DOWNLOAD_WORKERS) as executor:
            inline_images = list(executor.map(self._image_loader.load, image_urls))
        if sum(len(image) for image in inline_images) > MAX_VISION_INLINE_CHARACTERS:
            raise PermanentIntegrationError("deepseek_input_invalid")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(
            {"type": "image_url", "image_url": {"url": image_url}}
            for image_url in inline_images
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
        response_content = {}
        try:
            return self._validated_request(
                model,
                request_messages,
                schema,
                schema_payload,
                "initial",
                output_budget,
                response_content,
            )
        except (ValidationError, ValueError) as error:
            content = response_content["content"]
            _log_schema_failure(schema_payload, "initial", error)
            if schema is CreatorBriefSynthesis:
                brief = repair_creator_brief_text(
                    content,
                    error,
                    lambda messages, text_schema: self.complete_structured(
                        model, messages, text_schema, max_tokens=2_048
                    ),
                )
                if brief is not None:
                    return brief
            repair_messages = [
                *request_messages,
                *_repair_messages(content, schema_payload, error),
            ]
        try:
            return self._validated_request(
                model,
                repair_messages,
                schema,
                schema_payload,
                "repair",
                output_budget,
                response_content,
            )
        except (ValidationError, ValueError) as error:
            repaired = response_content["content"]
            _log_schema_failure(schema_payload, "repair", error)
            if schema is CreatorBriefSynthesis:
                brief = repair_creator_brief_text(
                    repaired,
                    error,
                    lambda messages, text_schema: self.complete_structured(
                        model, messages, text_schema, max_tokens=2_048
                    ),
                )
                if brief is not None:
                    return brief
            raise InvalidModelOutput("deepseek_model_output_invalid") from None

    def _validated_request(
        self, model, messages, schema, schema_payload, attempt, budget, response_content
    ):
        actual_model = (
            "deepseek-flash"
            if model
            in {"deepseek-v4-flash", "deepseek-v4-flash-vision-exp", "deepseek-v4-pro"}
            else model
        )
        with model_call(
            provider="deepseek",
            model=actual_model,
            schema=schema_payload["title"],
            attempt=attempt,
            max_tokens=budget,
        ) as span:
            content = self._request(model, messages, max_tokens=budget)
            response_content["content"] = content
            try:
                return schema.model_validate_json(normalize_evidence_json(content))
            except (ValidationError, ValueError) as error:
                safe = _safe_validation_errors(schema_payload, error)
                span["category"] = (
                    "json"
                    if any(e["type"] == "json_invalid" for e in safe)
                    else "schema"
                )
                span["validation_errors"] = safe
                span["validation_error_count"] = (
                    error.error_count() if isinstance(error, ValidationError) else 1
                )
                counts = {}
                for item in _safe_validation_errors(schema_payload, error, limit=None):
                    reason = item.get("reason", item["type"])
                    if reason not in counts and len(counts) >= 63:
                        reason = "other"
                    counts[reason] = counts.get(reason, 0) + 1
                span["validation_reason_counts"] = counts
                raise

    def _request(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None,
    ) -> str:
        # Existing saved plans may carry historical model names. Route only the
        # known old aliases without rewriting their persisted audit records.
        if model in {
            "deepseek-v4-flash",
            "deepseek-v4-flash-vision-exp",
            "deepseek-v4-pro",
        }:
            model = "deepseek-flash"
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
                    failure_category("http_retryable")
                    raise TransientIntegrationError("deepseek_unavailable")
                if response.status_code >= 400:
                    failure_category("http_rejected")
                    raise PermanentIntegrationError("deepseek_request_rejected")
                body = read_bounded_bytes(
                    response,
                    max_bytes=MAX_DEEPSEEK_RESPONSE_BYTES,
                )
        except ResponseTooLarge:
            failure_category("response_limit")
            raise PermanentIntegrationError("deepseek_response_too_large") from None
        except InvalidContentLength:
            failure_category("response_envelope")
            raise PermanentIntegrationError("deepseek_response_invalid") from None
        except httpx.TransportError as error:
            failure_category(
                "network_timeout"
                if isinstance(error, httpx.TimeoutException)
                else "network"
            )
            raise TransientIntegrationError("deepseek_unavailable") from None
        try:
            envelope = json.loads(body)
        except (UnicodeDecodeError, ValueError):
            failure_category("json")
            raise PermanentIntegrationError("deepseek_response_invalid") from None
        response_metadata(envelope)
        try:
            return _extract_content(envelope, model=model, max_tokens=max_tokens)
        except (PermanentIntegrationError, TransientIntegrationError):
            failure_category("response_envelope")
            raise


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


def _schema_location_names(value: object) -> set[str]:
    """Only code-owned schema names may appear in validation locations."""
    names: set[str] = set()
    if isinstance(value, dict):
        names.update(value.get("properties", {}))
        names.update(item for item in value.get("enum", []) if isinstance(item, str))
        if isinstance(value.get("const"), str):
            names.add(value["const"])
        for child in value.values():
            names.update(_schema_location_names(child))
    elif isinstance(value, list):
        for child in value:
            names.update(_schema_location_names(child))
    return names


def _safe_validation_errors(
    schema_payload: dict[str, Any], error: ValueError, *, limit: int | None = 8
) -> list[dict[str, Any]]:
    allowed_names = _schema_location_names(schema_payload["schema"])
    errors = (
        error.errors(include_input=False, include_url=False)
        if isinstance(error, ValidationError)
        else [{"type": "value_error", "loc": ()}]
    )
    safe_errors = []
    for item in errors[:limit]:
        location = [
            (
                part
                if type(part) is int
                or (
                    isinstance(part, str)
                    and part in allowed_names
                    and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", part)
                )
                else "[redacted]"
            )
            for part in item["loc"][:12]
        ]
        error_type = item["type"]
        safe_errors.append(
            {
                "type": (
                    error_type
                    if re.fullmatch(r"[a-z_]{1,64}", error_type)
                    else "unknown"
                ),
                "loc": location,
            }
        )
        # Never log raw validator messages/context: they may include model text.
        # Only exact, code-owned reasons become fixed diagnostic codes.
        reason = _VALIDATION_REASON_CODES.get(str(item.get("ctx", {}).get("error")))
        if reason is not None:
            safe_errors[-1]["reason"] = reason
    return safe_errors


def _log_schema_failure(
    schema_payload: dict[str, Any], attempt: str, error: ValueError
) -> None:
    logger.warning(
        "%s",
        json.dumps(
            {
                "event": "deepseek_schema_validation_failed",
                "schema": schema_payload["title"],
                "attempt": attempt,
                "errors": _safe_validation_errors(schema_payload, error),
            }
        ),
    )


def _log_truncated_output(
    envelope: dict[str, Any], *, model: str, max_tokens: int | None
) -> None:
    usage: dict[str, int] = {}
    raw_usage = envelope.get("usage")
    if isinstance(raw_usage, dict):
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = raw_usage.get(name)
            if type(value) is int and value >= 0:
                usage[name] = value
        details = raw_usage.get("completion_tokens_details")
        if isinstance(details, dict):
            value = details.get("reasoning_tokens")
            if type(value) is int and value >= 0:
                usage["reasoning_tokens"] = value
    logger.warning(
        "%s",
        json.dumps(
            {
                "event": "deepseek_output_truncated",
                "model": model,
                "finish_reason": "length",
                "max_tokens": max_tokens,
                "usage": usage,
            }
        ),
    )


def _extract_content(envelope: object, *, model: str, max_tokens: int | None) -> str:
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
        _log_truncated_output(envelope, model=model, max_tokens=max_tokens)
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
    invalid_content: str, schema_payload: dict[str, Any], error: ValueError
) -> list[dict[str, str]]:
    schema_json = json.dumps(
        schema_payload["schema"],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    creator_stage = schema_payload["title"] in {
        "CreatorVideoBatchDigest",
        "CreatorContentFormatReduction",
        "CreatorPresentationReduction",
        "CreatorPerformanceAudienceReduction",
        "CreatorCommercialSafetyReduction",
        "CreatorBriefSynthesis",
    }
    limit = 32_000 if creator_stage else MAX_REPAIR_CONTEXT_CHARACTERS
    context = invalid_content if len(invalid_content.encode("utf-8")) <= limit else None
    if not creator_stage:
        context = invalid_content[:MAX_REPAIR_CONTEXT_CHARACTERS]
    safe_errors_json = json.dumps(_safe_validation_errors(schema_payload, error))
    instruction = (
        "Repair the previous assistant output. Return exactly one JSON value that "
        "validates against this JSON Schema, with no Markdown or commentary. "
        "Correct the fields identified by the validation errors according to the schema. "
        "For list fields, obey maxItems by keeping only the strongest supported items; "
        "do not exceed the limit to preserve every item.\n"
        f"Validation errors: {safe_errors_json}\n"
        f"JSON Schema: {schema_json}"
    )
    if schema_payload["title"] in {"SearchPlanOutput", "RequestedSearchPlanOutput"}:
        instruction += (
            "\nFor query terms, use only letters, digits, spaces, apostrophes or hyphens. "
            "Rewrite title punctuation such as colons, ampersands, slashes or underscores "
            "as spaces; do not copy unsafe punctuation from a supplied title into terms. "
            "Keep terms unique and emit exactly one query for each requested platform."
        )
    if context is None:
        instruction += "\nThe prior output exceeds the bounded repair context and is omitted entirely. Regenerate the complete JSON from the original supplied inputs; do not continue a partial JSON fragment."
        return [{"role": "user", "content": instruction}]
    return [
        {"role": "assistant", "content": context},
        {"role": "user", "content": instruction},
    ]
