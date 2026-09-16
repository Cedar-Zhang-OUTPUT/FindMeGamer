import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from ..errors import ApiError
from .logging import protect_http_logs


def int_header(headers, name):
    try:
        return int(headers[name])
    except (KeyError, ValueError):
        return None


def retry_after(headers):
    number = int_header(headers, "retry-after")
    if number is not None:
        return max(0, number)
    try:
        return max(
            0,
            int(
                (
                    parsedate_to_datetime(headers["retry-after"])
                    - datetime.now(timezone.utc)
                ).total_seconds()
            ),
        )
    except (KeyError, ValueError, TypeError):
        reset = int_header(headers, "x-rate-limit-reset")
        if reset is None:
            reset = int_header(headers, "ratelimit-reset")
        return (
            max(0, int(reset - datetime.now(timezone.utc).timestamp()))
            if reset is not None
            else None
        )


def cursor_at(data, path):
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data if isinstance(data, (str, int)) else None


def encode_query(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(encode_query(item) for item in value)
    return str(value)


async def call_provider(
    settings,
    operation,
    path,
    params,
    provider,
    request_id,
    transport=None,
    *,
    twitch_auth=None,
):
    protect_http_logs()
    query = dict(params)
    headers = {"Accept": "application/json"}
    secret = ""
    if provider == "twitch":
        if twitch_auth is None:
            raise ApiError(
                503,
                "configuration_missing",
                "Twitch authorization manager is unavailable.",
            )
        secret = await twitch_auth.token(operation["auth"], transport)
        headers["Authorization"] = "Bearer " + secret
        headers["Client-Id"] = settings.twitch_client_id
    if operation["auth"] in {"api-key", "api-key-optional"}:
        secret = getattr(settings, provider + "_api_key").get_secret_value()
        if not secret and operation["auth"] == "api-key":
            raise ApiError(
                503,
                "configuration_missing",
                "Company provider credentials are not configured.",
            )
    elif operation["auth"] == "bearer":
        secret = settings.x_bearer_token.get_secret_value()
        if not secret:
            raise ApiError(
                503,
                "configuration_missing",
                "Company provider credentials are not configured.",
            )
        headers["Authorization"] = "Bearer " + secret
    if operation.get("transport_mode") == "input_json":
        query = {"input_json": json.dumps(query, separators=(",", ":"))}
    elif provider == "twitch":
        query = [
            (name, encode_query(item))
            for name, value in query.items()
            for item in (value if isinstance(value, list) else [value])
        ]
    else:
        query = {name: encode_query(value) for name, value in query.items()}
    if operation["auth"] in {"api-key", "api-key-optional"} and secret:
        query["key"] = secret
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, transport=transport, trust_env=False
        ) as client:
            response = await client.get(
                operation["base_url"] + path, params=query, headers=headers
            )
    except httpx.TimeoutException:
        raise ApiError(
            504, "upstream_timeout", "Provider request timed out.", retryable=True
        ) from None
    except httpx.HTTPError:
        raise ApiError(
            502, "upstream_unavailable", "Provider connection failed.", retryable=True
        ) from None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code >= 300:
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        errors = error.get("errors", []) if isinstance(error, dict) else []
        reasons = {item.get("reason") for item in errors if isinstance(item, dict)}
        if response.status_code == 402 or reasons & {
            "quotaExceeded",
            "dailyLimitExceeded",
            "dailyLimitExceededUnreg",
        }:
            raise ApiError(
                429, "quota_exhausted", "Provider quota or balance is exhausted."
            )
        if response.status_code == 429 or reasons & {
            "rateLimitExceeded",
            "userRateLimitExceeded",
        }:
            raise ApiError(
                429,
                "rate_limited",
                "Provider rate limit reached.",
                retryable=True,
                retry_after_seconds=retry_after(response.headers),
            )
        if response.status_code in {401, 403}:
            if provider == "twitch" and response.status_code == 401:
                twitch_auth.invalidate(operation["auth"])
            raise ApiError(
                403,
                "provider_authorization_required",
                "Provider denied access; check company authorization.",
            )
        if response.status_code in {400, 404, 422}:
            raise ApiError(
                response.status_code,
                "provider_rejected_request",
                "Provider rejected this request; check the operation parameters.",
            )
        raise ApiError(
            502,
            "upstream_unavailable",
            "Provider returned an unexpected response.",
            retryable=response.status_code >= 500,
        )
    if payload is None:
        raise ApiError(
            502,
            "invalid_provider_response",
            "Provider did not return JSON.",
            retryable=True,
        )
    # No response-schema coercion: preserve new fields and partial error arrays.
    pagination = operation.get("pagination")
    return {
        "data": payload,
        "meta": {
            "request_id": request_id,
            "next_cursor": (
                cursor_at(payload, pagination["response_path"]) if pagination else None
            ),
            "rate_limit": {
                "limit": int_header(
                    response.headers,
                    "ratelimit-limit" if provider == "twitch" else "x-rate-limit-limit",
                ),
                "remaining": int_header(
                    response.headers,
                    (
                        "ratelimit-remaining"
                        if provider == "twitch"
                        else "x-rate-limit-remaining"
                    ),
                ),
                "reset_at": int_header(
                    response.headers,
                    "ratelimit-reset" if provider == "twitch" else "x-rate-limit-reset",
                ),
            },
            "warnings": [],
        },
    }
