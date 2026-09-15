"""Bounded public Store helpers; not guaranteed Steam Web API methods."""

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

import httpx

from ..errors import ApiError
from .transport import retry_after

STORE = "https://store.steampowered.com"
MAX_BYTES = 2 * 1024 * 1024


def store_operations():
    shared = {
        "method": "GET",
        "base_url": STORE,
        "auth": "none",
        "availability": "simulated",
        "pagination": None,
        "response_schema": {},
        "stability": "store-helper-not-official-web-api",
    }
    locale = {
        "l": {"type": "string", "location": "query"},
        "cc": {"type": "string", "location": "query"},
    }
    return {
        "store.search": {
            **shared,
            "id": "store.search",
            "path": "/api/storesearch/",
            "parameters": {
                "term": {"type": "string", "required": True, "location": "query"},
                **locale,
            },
            "summary": "Search game names; returns multiple candidates and original JSON. One bounded Store request, not exhaustive search.",
            "source_url": STORE + "/api/storesearch/",
        },
        "store.recommendations": {
            **shared,
            "id": "store.recommendations",
            "path": "/recommended/morelike/app/",
            "parameters": {
                "appid": {
                    "type": "string",
                    "required": True,
                    "location": "query",
                    "description": "Positive App ID or https://store.steampowered.com/app/ID/... URL",
                },
                **locale,
            },
            "summary": "Parse public similar-game cards; unique IDs/URLs, name may be null. name_hint is a URL slug, not a verified title. One page; no automatic detail calls.",
            "source_url": STORE + "/recommended/morelike/app/570/",
        },
    }


def app_id(value):
    raw = str(value)
    if re.fullmatch(r"[1-9][0-9]*", raw):
        return raw
    try:
        url = urlsplit(raw)
        match = re.match(r"^/app/([1-9][0-9]*)(?:/|$)", url.path)
        if url.scheme == "https" and url.netloc == "store.steampowered.com" and match:
            return match[1]
    except ValueError:
        pass
    raise ApiError(
        422, "invalid_request", "Supply a Steam App ID or official Store app URL."
    )


def invalid_response():
    return ApiError(
        502,
        "invalid_provider_response",
        "Steam Store returned an unrecognized response.",
    )


class Recommendations(HTMLParser):
    def __init__(self, current):
        super().__init__(convert_charrefs=True)
        self.current = current
        self.items = []
        self.seen = {current}
        self.recognized = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if "similar_grid_ctn" in classes:
            self.recognized = True
        if tag != "a" or "similar_grid_capsule" not in classes:
            return
        href = attrs.get("href", "")
        try:
            identity = app_id(href)
        except ApiError:
            return
        if identity in self.seen or attrs.get("data-ds-appid") != identity:
            return
        self.seen.add(identity)
        segments = urlsplit(href).path.split("/")
        hint = unquote(segments[3]).replace("_", " ") if len(segments) > 3 else ""
        self.items.append(
            {
                "app_id": identity,
                "name": None,
                "name_hint": hint or None,
                "url": f"{STORE}/app/{identity}/",
            }
        )


async def call_store(operation, params, request_id, transport=None):
    query = {"l": "english", "cc": "US"}
    for key in ("l", "cc"):
        if key in params:
            if not isinstance(params[key], str) or not params[key].strip():
                raise ApiError(
                    422, "invalid_request", "Store locale must be a nonempty string."
                )
            query[key] = params[key]
    search = operation["id"] == "store.search"
    if search:
        term = params["term"]
        if not isinstance(term, str) or not term.strip():
            raise ApiError(422, "invalid_request", "Supply a nonempty game name.")
        query["term"] = term.strip()
        path = "/api/storesearch/"
    else:
        identity = app_id(params["appid"])
        path = f"/recommended/morelike/app/{identity}/"
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False, transport=transport
        ) as client:
            async with client.stream("GET", STORE + path, params=query) as response:
                if response.status_code == 429:
                    raise ApiError(
                        429,
                        "rate_limited",
                        "Steam Store rate limit reached.",
                        retryable=True,
                        retry_after_seconds=retry_after(response.headers),
                    )
                if response.status_code != 200:
                    raise ApiError(
                        502,
                        "upstream_unavailable",
                        "Steam Store request failed.",
                        retryable=response.status_code >= 500,
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        raise ApiError(
                            502,
                            "provider_response_too_large",
                            "Steam Store response exceeded the size limit.",
                        )
                source_url = str(response.url)
    except httpx.TimeoutException:
        raise ApiError(
            504, "upstream_timeout", "Steam Store request timed out.", retryable=True
        ) from None
    except httpx.HTTPError:
        raise ApiError(
            502,
            "upstream_unavailable",
            "Steam Store connection failed.",
            retryable=True,
        ) from None
    if search:
        try:
            upstream = json.loads(content)
        except (ValueError, UnicodeError):
            raise invalid_response() from None
        if not isinstance(upstream, dict) or not isinstance(
            upstream.get("items"), list
        ):
            raise invalid_response()
        candidates = []
        for row in upstream["items"]:
            if not isinstance(row, dict):
                raise invalid_response()
            if row.get("type") != "app":
                continue
            if not re.fullmatch(
                r"[1-9][0-9]*", str(row.get("id", ""))
            ) or not isinstance(row.get("name"), str):
                raise invalid_response()
            candidates.append(
                {
                    "app_id": str(row["id"]),
                    "name": row["name"],
                    "url": f'{STORE}/app/{row["id"]}/',
                }
            )
        data = {"candidates": candidates, "upstream": upstream}
    else:
        parser = Recommendations(identity)
        parser.feed(content.decode("utf-8", errors="replace"))
        if not parser.recognized:
            raise invalid_response()
        data = {"app_id": identity, "items": parser.items}
    return {
        "data": data,
        "meta": {
            "request_id": request_id,
            "source_url": source_url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "next_cursor": None,
            "rate_limit": {"limit": None, "remaining": None, "reset_at": None},
            "warnings": [
                "Steam Store convenience endpoint; results and page structure may change."
            ],
        },
    }
