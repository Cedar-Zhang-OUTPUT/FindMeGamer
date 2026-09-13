import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.analysis.contracts import CreatorSource
from app.core.config import validate_external_base_url
from app.core.analysis_diagnostics import (
    model_call,
    response_metadata,
    failure_category,
)
from app.integrations.errors import (
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.integrations.http import (
    InvalidContentLength,
    ResponseTooLarge,
    read_bounded_bytes,
    streaming_response,
)
from app.schemas.ai_creator import _canonical_public_url_key

DEFAULT_GEMINI_EMAIL_API_BASE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
)
DEFAULT_GEMINI_EMAIL_MODEL = "gemini-3.8-flash"
MAX_GEMINI_EMAIL_RESPONSE_BYTES = 2_000_000
MAX_GEMINI_EMAIL_ATTEMPTS = 4
GEMINI_EMAIL_RETRY_DELAY_SECONDS = 1.0
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=20.0, pool=5.0)

SYSTEM_PROMPT = (
    "Please locate the email address for a specified individual; you may gather "
    "information from across the web. The user will provide either a person's name "
    "or a link to their social media profile.\nOutput the discovered email address "
    "in a structured format, including the following fields: email address, purpose "
    "of the email, and source.\nIf you are unable to find a direct personal email "
    "address after two attempts, do not continue searching or altering your keywords. "
    "Stop immediately and instead look for the best available general contact page "
    "or publicly available information; personal email addresses are very likely to "
    "appear in social media bios."
)

EMAIL_SCHEMA: dict[str, Any] = {
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
}

_EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}", re.IGNORECASE)
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class GeminiEmailRecord:
    email: str
    usage: str
    source: str


class _MalformedGeminiResponse(Exception):
    pass


class GeminiEmailResearchGateway:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_GEMINI_EMAIL_API_BASE_URL,
        model: str = DEFAULT_GEMINI_EMAIL_MODEL,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        _validate_configuration(api_key=api_key, model=model, sleep=sleep)
        try:
            self._base_url = validate_external_base_url(base_url)
        except ValueError:
            raise PermanentIntegrationError("analysis_configuration_invalid") from None
        self._api_key = api_key
        self._model = model
        self._sleep = sleep
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

    def __enter__(self) -> "GeminiEmailResearchGateway":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def find_public_emails(
        self,
        source: CreatorSource,
        *,
        existing_contacts: tuple[str, ...] = (),
    ) -> tuple[GeminiEmailRecord, ...]:
        if not isinstance(source, CreatorSource):
            raise TypeError("email research requires a CreatorSource")
        if (
            not isinstance(existing_contacts, tuple)
            or not all(isinstance(contact, str) for contact in existing_contacts)
            or len(existing_contacts) > 10
        ):
            raise TypeError("existing contacts must be a bounded tuple of strings")

        payload = _request_payload(source, existing_contacts=existing_contacts)
        for attempt in range(1, MAX_GEMINI_EMAIL_ATTEMPTS + 1):
            try:
                with model_call(
                    provider="gemini",
                    model=self._model,
                    schema="GeminiEmailResearch",
                    attempt="initial" if attempt == 1 else "retry",
                    max_tokens=65_536,
                ) as span:
                    span["request_attempt"] = attempt
                    records = self._request(payload)
            except TransientIntegrationError:
                if attempt == MAX_GEMINI_EMAIL_ATTEMPTS:
                    raise
            except _MalformedGeminiResponse:
                if attempt == MAX_GEMINI_EMAIL_ATTEMPTS:
                    raise PermanentIntegrationError(
                        "public_page_response_invalid"
                    ) from None
            else:
                if records or attempt == MAX_GEMINI_EMAIL_ATTEMPTS:
                    return records
            self._sleep(GEMINI_EMAIL_RETRY_DELAY_SECONDS)
        raise AssertionError("Gemini email retry loop exhausted unexpectedly")

    def _request(self, payload: dict[str, Any]) -> tuple[GeminiEmailRecord, ...]:
        endpoint = f"{self._base_url}/{quote(self._model, safe='')}:generateContent"
        try:
            with streaming_response(
                self._client,
                "POST",
                endpoint,
                headers={"x-goog-api-key": self._api_key},
                json=payload,
                auth=None,
                timeout=HTTP_TIMEOUT,
                follow_redirects=False,
            ) as response:
                if response.status_code == 429 or response.status_code >= 500:
                    failure_category("http_retryable")
                    raise TransientIntegrationError("public_page_unavailable")
                if response.status_code >= 400:
                    failure_category("http_rejected")
                    raise PermanentIntegrationError("public_page_request_rejected")
                body = read_bounded_bytes(
                    response, max_bytes=MAX_GEMINI_EMAIL_RESPONSE_BYTES
                )
        except ResponseTooLarge:
            failure_category("response_limit")
            raise PermanentIntegrationError("public_page_too_large") from None
        except InvalidContentLength:
            failure_category("response_envelope")
            raise PermanentIntegrationError("public_page_response_invalid") from None
        except httpx.TransportError as error:
            failure_category(
                "network_timeout"
                if isinstance(error, httpx.TimeoutException)
                else "network"
            )
            raise TransientIntegrationError("public_page_unavailable") from None
        try:
            envelope = json.loads(body)
        except (UnicodeDecodeError, ValueError):
            failure_category("json")
            return _parse_response(body)
        else:
            response_metadata(envelope, gemini=True)
        return _parse_response(body)


def _validate_configuration(
    *,
    api_key: object,
    model: object,
    sleep: object,
) -> None:
    if (
        not isinstance(api_key, str)
        or not api_key
        or len(api_key) > 16_384
        or any(character.isspace() or ord(character) < 32 for character in api_key)
        or not isinstance(model, str)
        or not _MODEL_NAME.fullmatch(model)
        or not callable(sleep)
    ):
        raise PermanentIntegrationError("analysis_configuration_invalid")


def _request_payload(
    source: CreatorSource, *, existing_contacts: tuple[str, ...]
) -> dict[str, Any]:
    contact_entry = ", ".join(existing_contacts) or "Not provided"
    target_prompt = "\n".join(
        (
            "Research this specific creator:",
            f"Name: {_clean_field(source.title, 'Unknown')}",
            (
                "Platform: X"
                if urlsplit(source.canonical_url).hostname
                in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
                else "Platform: YouTube"
            ),
            f"Profile URL: {_clean_field(source.canonical_url, 'Not provided')}",
            "Existing public contact entry: "
            f"{_clean_field(contact_entry, 'Not provided')}",
            "",
            "Search the public web broadly, including official profile/about pages, "
            "linked sites, media kits, management or agency pages, reputable creator "
            "databases, archived public pages, and other publicly indexed third-party "
            "pages.",
            "",
            "Non-primary public sources are acceptable. Do not guess email patterns. "
            "Do not use leaked data, private databases, login-gated personal "
            "information, or an address that cannot be tied to this creator or their "
            "authorized team.",
            "",
            "Return every plausible publicly listed contact email tied to the creator "
            "or their team. For each email, state its intended usage and give the exact "
            "public HTTP(S) source URL where it was found. Never return a source label "
            "without its exact URL. Independently verify any email already present in "
            "the existing contact entry. If no public email is found, return "
            '{"email_info":[]}.',
        )
    )
    return {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": target_prompt}]}],
        "tools": [{"googleSearch": {}}, {"urlContext": {}}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": EMAIL_SCHEMA,
            "maxOutputTokens": 65_536,
            "thinkingConfig": {"thinkingLevel": "MEDIUM"},
        },
    }


def _parse_response(body: bytes) -> tuple[GeminiEmailRecord, ...]:
    try:
        payload = json.loads(body)
        candidate = payload["candidates"][0]
        parts = candidate["content"]["parts"]
        if not isinstance(parts, list):
            raise TypeError
        text = "\n".join(
            part["text"]
            for part in parts
            if isinstance(part, dict)
            and part.get("thought") is not True
            and isinstance(part.get("text"), str)
        ).strip()
        text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text).strip()
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace >= first_brace:
            text = text[first_brace : last_brace + 1]
        structured = json.loads(text)
        email_info = structured["email_info"]
        if not isinstance(email_info, list):
            raise TypeError
    except (UnicodeDecodeError, ValueError):
        failure_category("json")
        raise _MalformedGeminiResponse from None
    except (KeyError, IndexError, TypeError):
        failure_category("schema")
        raise _MalformedGeminiResponse from None
    return _normalize_records(email_info)


def _normalize_records(records: list[object]) -> tuple[GeminiEmailRecord, ...]:
    normalized: list[GeminiEmailRecord] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        match = _EMAIL_PATTERN.search(str(record.get("email", "")))
        if match is None:
            continue
        email = match.group(0).lower()
        if email in seen:
            continue
        source = _clean_field(record.get("source"), "")
        try:
            _canonical_public_url_key(source)
        except ValueError:
            continue
        seen.add(email)
        normalized.append(
            GeminiEmailRecord(
                email=email,
                usage=_clean_field(record.get("usage"), "Usage not specified"),
                source=source,
            )
        )
    return tuple(normalized)


def _clean_field(value: object, fallback: str) -> str:
    text = str(value or "")
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.replace("；", "，").replace("｜", "/").strip() or fallback
