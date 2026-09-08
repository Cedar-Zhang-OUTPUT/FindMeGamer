"""Bounded, one-page official X recent-search metadata discovery."""

import json
import re
from datetime import UTC, datetime

import httpx

from app.core.config import validate_external_base_url
from app.integrations.http import (
    InvalidContentLength,
    ResponseTooLarge,
    read_bounded_bytes,
    streaming_response,
)
from app.schemas.discovery import (
    DiscoveredAccount,
    DiscoveredContent,
    DiscoveryCursor,
    DiscoveryIssue,
    DiscoveryPage,
    DiscoveryRequest,
)


class XDiscoveryGateway:
    def __init__(
        self,
        *,
        bearer_token: str,
        base_url: str = "https://api.x.com/2",
        http_client: httpx.Client | None = None,
    ):
        if (
            not bearer_token
            or len(bearer_token) > 16384
            or any(ord(c) <= 32 or ord(c) >= 127 for c in bearer_token)
        ):
            raise ValueError("Invalid X credential.")
        self._token = bearer_token
        self._base_url = validate_external_base_url(base_url)
        self._owns_client = http_client is None
        self._client = (
            http_client
            if http_client is not None
            else httpx.Client(trust_env=False, follow_redirects=False)
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._owns_client:
            self._client.close()

    def discover(self, request: DiscoveryRequest) -> DiscoveryPage:
        if request.platform != "x":
            return DiscoveryPage(
                platform=request.platform,
                status="unavailable",
                coverage="unavailable",
                issues=[DiscoveryIssue(code="not_supported")],
            )
        if request.max_requests == 0:
            return DiscoveryPage(
                platform="x",
                status="budget_exhausted",
                coverage="recent_7_days",
                issues=[DiscoveryIssue(code="budget_exhausted")],
            )
        params = {
            "query": request.query,
            "max_results": str(request.page_size),
            "expansions": "author_id",
            "tweet.fields": "author_id,created_at,lang,public_metrics",
            "user.fields": "name,username,description,public_metrics,location,profile_image_url",
        }
        if request.cursor:
            params["next_token"] = request.cursor.token
        try:
            with streaming_response(
                self._client,
                "GET",
                f"{self._base_url}/tweets/search/recent",
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=httpx.Timeout(connect=5, read=20, write=10, pool=5),
                follow_redirects=False,
            ) as response:
                status = response.status_code
                if status != 200:
                    code = {
                        400: "invalid_request",
                        401: "unauthorized",
                        402: "unavailable",
                        403: "forbidden",
                        422: "invalid_request",
                        429: "rate_limited",
                    }.get(status, "unavailable" if status >= 500 else "forbidden")
                    retry = response.headers.get("retry-after", "")
                    retry_seconds = (
                        int(retry)
                        if retry.isascii() and retry.isdecimal() and len(retry) <= 9
                        else None
                    )
                    return self._failure(
                        code,
                        retryable=status == 429 or status >= 500,
                        retry_after_seconds=retry_seconds if status == 429 else None,
                    )
                payload = json.loads(read_bounded_bytes(response, max_bytes=4_000_000))
        except httpx.TimeoutException:
            return self._failure("timeout", retryable=True)
        except httpx.HTTPError:
            return self._failure("unavailable", retryable=True)
        except (ValueError, ResponseTooLarge, InvalidContentLength):
            return self._failure("invalid_response")
        return self._normalize(payload, request)

    @staticmethod
    def _failure(code, *, retryable=False, retry_after_seconds=None):
        return DiscoveryPage(
            platform="x",
            status="failed",
            coverage="recent_7_days",
            requests_used=1,
            issues=[
                DiscoveryIssue(
                    code=code,
                    retryable=retryable,
                    retry_after_seconds=retry_after_seconds,
                )
            ],
        )

    def _normalize(self, payload, request):
        if not isinstance(payload, dict):
            return self._failure("invalid_response")
        meta = payload.get("meta", {})
        if not isinstance(meta, dict):
            return self._failure("invalid_response")
        data = payload.get("data")
        if data is None and meta.get("result_count") == 0 and not payload.get("errors"):
            data = []
        if not isinstance(data, list):
            return self._failure("invalid_response")
        includes = payload.get("includes", {})
        users = includes.get("users", []) if isinstance(includes, dict) else []
        partial = bool(payload.get("errors")) or not isinstance(users, list)
        users_by_id = (
            {
                user["id"]: user
                for user in users
                if isinstance(user, dict) and _identifier(user.get("id"))
            }
            if isinstance(users, list)
            else {}
        )
        now = datetime.now(UTC)
        accounts = {}
        contents = {}
        for item in data:
            if not isinstance(item, dict) or not _identifier(item.get("id")):
                partial = True
                continue
            content_id = item["id"]
            if content_id in contents:
                continue
            author_id = (
                item.get("author_id") if _identifier(item.get("author_id")) else None
            )
            if author_id is None:
                partial = True
            elif author_id not in accounts:
                user = users_by_id.get(author_id, {})
                partial |= not bool(user)
                metrics = user.get("public_metrics", {})
                followers = (
                    _count(metrics.get("followers_count"))
                    if isinstance(metrics, dict)
                    else None
                )
                accounts[author_id] = DiscoveredAccount(
                    platform="x",
                    account_id=author_id,
                    profile_url=f"https://x.com/i/user/{author_id}",
                    display_name=_text(user.get("name")),
                    handle=_text(user.get("username")),
                    description=_text(user.get("description")),
                    follower_count=followers,
                    location_text=_text(user.get("location")),
                    avatar_url=_public_url(user.get("profile_image_url")),
                    collected_at=now,
                    metadata_complete=bool(user),
                )
            metrics = item.get("public_metrics", {})
            public_metrics = (
                {
                    key: value
                    for key, value in metrics.items()
                    if key
                    in {
                        "retweet_count",
                        "reply_count",
                        "like_count",
                        "quote_count",
                        "bookmark_count",
                        "impression_count",
                    }
                    and _count(value) is not None
                }
                if isinstance(metrics, dict)
                else {}
            )
            contents[content_id] = DiscoveredContent(
                platform="x",
                content_id=content_id,
                account_id=author_id,
                source_url=f"https://x.com/i/web/status/{content_id}",
                text=_text(item.get("text")),
                language=_text(item.get("lang")),
                published_at=_timestamp(item.get("created_at")),
                public_metrics=public_metrics,
                collected_at=now,
            )
        token = meta.get("next_token")
        cursor = None
        if token is not None:
            if (
                isinstance(token, str)
                and 0 < len(token) <= 2048
                and all(32 < ord(c) < 127 for c in token)
            ):
                cursor = DiscoveryCursor(
                    token=token, query_fingerprint=request.fingerprint()
                )
            else:
                partial = True
        return DiscoveryPage(
            platform="x",
            accounts=list(accounts.values()),
            contents=list(contents.values()),
            next_cursor=cursor,
            status="partial" if partial else "more" if cursor else "complete",
            issues=[DiscoveryIssue(code="partial_data")] if partial else [],
            requests_used=1,
            provider_items_received=len(data),
            coverage="recent_7_days",
        )


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9]{1,32}", value) is not None


def _text(value):
    return value if isinstance(value, str) and value else None


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def _public_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = httpx.URL(value)
        return (
            value if url.scheme == "https" and url.host and not url.userinfo else None
        )
    except httpx.InvalidURL:
        return None
