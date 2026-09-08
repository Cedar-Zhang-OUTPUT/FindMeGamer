"""Bounded official YouTube search metadata; never evidence of having watched."""

import json
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from app.core.config import validate_external_base_url
from app.integrations.http import (
    InvalidContentLength,
    ResponseTooLarge,
    read_bounded_bytes,
    streaming_response,
)
from app.integrations.youtube import _validate_api_key
from app.schemas.discovery import (
    DiscoveredAccount,
    DiscoveredContent,
    DiscoveryCursor,
    DiscoveryIssue,
    DiscoveryPage,
    DiscoveryRequest,
)

_CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{6,126}\Z")
_VIDEO = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TIMEOUT = httpx.Timeout(connect=5, read=20, write=10, pool=5)


class YouTubeDiscoveryGateway:
    def __init__(
        self,
        *,
        api_key,
        base_url="https://www.googleapis.com/youtube/v3",
        http_client=None,
    ):
        _validate_api_key(api_key)
        self._key = api_key
        self._base_url = validate_external_base_url(base_url)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=_TIMEOUT, trust_env=False, follow_redirects=False
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._owns_client:
            self._client.close()

    def discover(self, request: DiscoveryRequest) -> DiscoveryPage:
        if request.platform != "youtube":
            return DiscoveryPage(
                platform=request.platform,
                status="unavailable",
                coverage="unavailable",
                issues=[DiscoveryIssue(code="not_supported")],
            )
        page = DiscoveryPage(
            platform="youtube", status="complete", coverage="search_index"
        )
        if request.max_requests < 2:
            page.status = "budget_exhausted"
            page.issues.append(DiscoveryIssue(code="budget_exhausted"))
            return page
        params = {
            "part": "snippet",
            "type": request.search_mode,
            "q": request.query,
            "maxResults": str(request.page_size),
        }
        for key, value in (
            ("regionCode", request.region_hint),
            ("relevanceLanguage", request.language_hint),
            ("pageToken", request.cursor.token if request.cursor else None),
        ):
            if value:
                params[key] = value
        page.requests_used += 1
        payload, issue = self._get("search", params)
        if issue:
            page.status = "failed"
            page.issues.append(issue)
            return page
        token = payload.get("nextPageToken")
        if token is not None:
            if isinstance(token, str) and 0 < len(token) <= 2048:
                page.next_cursor = DiscoveryCursor(
                    token=token, query_fingerprint=request.fingerprint()
                )
            else:
                page.issues.append(DiscoveryIssue(code="invalid_response"))
        items = payload["items"]
        page.provider_items_received = len(items)
        now = datetime.now(UTC)
        accounts = {}
        contents = {}
        for item in items:
            if not isinstance(item, dict):
                _partial(page)
                continue
            identity = _dict(item.get("id"))
            snippet = _dict(item.get("snippet"))
            channel_id = (
                identity.get("channelId")
                if request.search_mode == "channel"
                else snippet.get("channelId")
            )
            if not isinstance(channel_id, str) or not _CHANNEL.fullmatch(channel_id):
                channel_id = None
                _partial(page)
            if channel_id and channel_id not in accounts:
                accounts[channel_id] = DiscoveredAccount(
                    platform="youtube",
                    account_id=channel_id,
                    profile_url=f"https://www.youtube.com/channel/{channel_id}",
                    display_name=_text(
                        snippet.get(
                            "title"
                            if request.search_mode == "channel"
                            else "channelTitle"
                        )
                    ),
                    collected_at=now,
                    metadata_complete=False,
                )
            if request.search_mode == "video":
                video_id = identity.get("videoId")
                if not isinstance(video_id, str) or not _VIDEO.fullmatch(video_id):
                    _partial(page)
                    continue
                contents.setdefault(
                    video_id,
                    DiscoveredContent(
                        platform="youtube",
                        content_id=video_id,
                        account_id=channel_id,
                        source_url=f"https://www.youtube.com/watch?v={video_id}",
                        title=_text(snippet.get("title")),
                        text=_text(snippet.get("description")),
                        published_at=_date(snippet.get("publishedAt")),
                        collected_at=now,
                    ),
                )
        if accounts:
            page.requests_used += 1
            enriched, issue = self._get(
                "channels", {"part": "snippet,statistics", "id": ",".join(accounts)}
            )
            if issue:
                page.issues.append(issue)
            else:
                for item in enriched["items"]:
                    if not isinstance(item, dict):
                        _partial(page)
                        continue
                    channel_id = item.get("id")
                    if not isinstance(channel_id, str) or channel_id not in accounts:
                        continue
                    snippet = _dict(item.get("snippet"))
                    stats = _dict(item.get("statistics"))
                    account = accounts[channel_id]
                    account.display_name = (
                        _text(snippet.get("title")) or account.display_name
                    )
                    account.description = _text(snippet.get("description"))
                    custom = _text(snippet.get("customUrl"))
                    account.handle = (
                        custom if custom and custom.startswith("@") else None
                    )
                    account.country = _text(snippet.get("country"))
                    account.avatar_url = _url(
                        _dict(_dict(snippet.get("thumbnails")).get("default")).get(
                            "url"
                        )
                    )
                    account.follower_count = (
                        None
                        if stats.get("hiddenSubscriberCount") is True
                        else _count(stats.get("subscriberCount"))
                    )
                    account.metadata_complete = bool(snippet)
            if any(not a.metadata_complete for a in accounts.values()):
                _partial(page)
        page.accounts = list(accounts.values())
        page.contents = list(contents.values())
        page.status = (
            "partial" if page.issues else "more" if page.next_cursor else "complete"
        )
        return page

    def _get(self, path, params):
        try:
            with streaming_response(
                self._client,
                "GET",
                f"{self._base_url}/{path}",
                timeout=_TIMEOUT,
                params=params,
                headers={"X-Goog-Api-Key": self._key},
            ) as response:
                status = response.status_code
                if status != 200:
                    code = {
                        400: "invalid_request",
                        401: "unauthorized",
                        403: "forbidden",
                        422: "invalid_request",
                        429: "rate_limited",
                    }.get(status, "unavailable")
                    if status == 403:
                        try:
                            error_payload = json.loads(
                                read_bounded_bytes(response, max_bytes=4_000_000)
                            )
                            errors = _dict(_dict(error_payload).get("error")).get(
                                "errors"
                            )
                            if isinstance(errors, list) and any(
                                isinstance(error, dict)
                                and error.get("reason")
                                in (
                                    "quotaExceeded",
                                    "dailyLimitExceeded",
                                    "userRateLimitExceeded",
                                    "rateLimitExceeded",
                                )
                                for error in errors
                            ):
                                code = "rate_limited"
                        except (
                            ValueError,
                            UnicodeError,
                            ResponseTooLarge,
                            InvalidContentLength,
                        ):
                            pass
                    retry_after = (
                        _count(response.headers.get("retry-after"))
                        if code == "rate_limited"
                        else None
                    )
                    return None, DiscoveryIssue(
                        code=code,
                        retryable=code == "rate_limited" or status >= 500,
                        retry_after_seconds=retry_after,
                    )
                payload = json.loads(read_bounded_bytes(response, max_bytes=4_000_000))
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("items"), list
                ):
                    return None, DiscoveryIssue(code="invalid_response")
                return payload, None
        except httpx.TimeoutException:
            return None, DiscoveryIssue(code="timeout", retryable=True)
        except httpx.HTTPError:
            return None, DiscoveryIssue(code="unavailable", retryable=True)
        except (ValueError, UnicodeError, ResponseTooLarge, InvalidContentLength):
            return None, DiscoveryIssue(code="invalid_response")


def _dict(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    return value if isinstance(value, str) and value else None


def _url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and "\\" not in value
        ):
            return value
    except ValueError:
        pass
    return None


def _count(value):
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and len(value) <= 20
    ):
        return int(value)
    return None


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date if date.tzinfo else None
    except ValueError:
        return None


def _partial(page):
    if not any(issue.code == "partial_data" for issue in page.issues):
        page.issues.append(DiscoveryIssue(code="partial_data"))
