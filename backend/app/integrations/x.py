"""Bounded, read-only official X API v2 account and public timeline access."""

import json
import re

import httpx

from app.analysis.contracts import XCreatorSource, XPostSource
from app.analysis.targets import CanonicalTarget
from app.core.config import validate_external_base_url
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.http import (
    InvalidContentLength,
    ResponseTooLarge,
    read_bounded_bytes,
    streaming_response,
)
from app.integrations.youtube import (
    _optional_count,
    _optional_datetime,
    _required_string,
    _optional_string,
)

DEFAULT_X_API_BASE_URL = "https://api.x.com/2"
HTTP_TIMEOUT = httpx.Timeout(connect=5, read=20, write=10, pool=5)
_ID = re.compile(r"[1-9][0-9]{0,19}")
_USERNAME = re.compile(r"[A-Za-z0-9_]{1,15}")


class XGateway:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_X_API_BASE_URL,
        http_client: httpx.Client | None = None,
    ):
        if (
            not isinstance(api_key, str)
            or not api_key
            or len(api_key) > 16384
            or any(c.isspace() or ord(c) < 32 for c in api_key)
        ):
            raise PermanentIntegrationError("x_configuration_invalid")
        self._api_key = api_key
        self._base_url = validate_external_base_url(base_url)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=HTTP_TIMEOUT, follow_redirects=False, trust_env=False
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._owns_client:
            self._client.close()

    def resolve_channel(self, target: CanonicalTarget) -> str:
        username = target.canonical_id.removeprefix("x:@")
        if not target.canonical_id.startswith("x:@") or not _USERNAME.fullmatch(
            username
        ):
            raise PermanentIntegrationError("x_target_invalid")
        data = self._request_json(f"users/by/username/{username}").get("data")
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("id"), str)
            or not _ID.fullmatch(data["id"])
        ):
            raise PermanentIntegrationError("x_account_not_found")
        return data["id"]

    def fetch_creator(self, account_id: str) -> XCreatorSource:
        if not isinstance(account_id, str) or not _ID.fullmatch(account_id):
            raise PermanentIntegrationError("x_target_invalid")
        account_payload = self._request_json(
            f"users/{account_id}",
            {
                "user.fields": "description,profile_image_url,public_metrics,url,entities"
            },
        )
        account = account_payload.get("data")
        if not isinstance(account, dict) or account.get("id") != account_id:
            raise PermanentIntegrationError("x_account_not_found")
        posts_payload = self._request_json(
            f"users/{account_id}/tweets",
            {
                "max_results": "50",
                "tweet.fields": "author_id,created_at,public_metrics",
                "exclude": "retweets,replies",
            },
        )
        try:
            posts = posts_payload.get("data", [])
            if (
                posts_payload.get("errors")
                or not isinstance(posts, list)
                or len(posts) > 50
            ):
                raise ValueError()
            if not posts and posts_payload.get("meta", {}).get("result_count") != 0:
                raise ValueError()
            mapped = []
            for post in posts:
                if (
                    not isinstance(post, dict)
                    or post.get("author_id") != account_id
                    or not isinstance(post.get("id"), str)
                    or not _ID.fullmatch(post["id"])
                ):
                    raise ValueError()
                metrics = post.get("public_metrics", {})
                mapped.append(
                    XPostSource(
                        id=post["id"],
                        canonical_url=f"https://x.com/i/status/{post['id']}",
                        text=_required_string(post.get("text"), max_length=30000),
                        published_at=_optional_datetime(post.get("created_at")),
                        public_metrics={
                            k: _optional_count(v)
                            for k, v in metrics.items()
                            if k
                            in {
                                "like_count",
                                "reply_count",
                                "retweet_count",
                                "quote_count",
                                "impression_count",
                                "bookmark_count",
                            }
                        },
                    )
                )
            metrics = account.get("public_metrics", {})
            return XCreatorSource(
                platform_account_id=account_id,
                canonical_url=f"https://x.com/i/user/{account_id}",
                title=_required_string(account.get("name"), max_length=512),
                username=_required_string(account.get("username"), max_length=15),
                description=_optional_string(
                    account.get("description"), max_length=10000
                )
                or "",
                avatar_url=_optional_string(
                    account.get("profile_image_url"), max_length=2048
                ),
                follower_count=_optional_count(metrics.get("followers_count")),
                post_count=_optional_count(metrics.get("tweet_count")),
                posts=tuple(mapped),
                raw_account=account_payload,
                raw_posts=posts_payload,
            )
        except (ValueError, TypeError, AttributeError):
            raise PermanentIntegrationError("x_response_invalid") from None

    def _request_json(self, endpoint: str, params: dict[str, str] | None = None):
        try:
            with streaming_response(
                self._client,
                "GET",
                f"{self._base_url}/{endpoint}",
                params=params,
                headers={"Authorization": f"Bearer {self._api_key}"},
                auth=None,
                timeout=HTTP_TIMEOUT,
                follow_redirects=False,
            ) as response:
                body = read_bounded_bytes(response, max_bytes=4_000_000)
                status = response.status_code
            if status == 402:
                raise PermanentIntegrationError("x_payment_required")
            if status == 429:
                raise TransientIntegrationError("x_rate_limited")
            if status >= 500:
                raise TransientIntegrationError("x_unavailable")
            if status == 403 and any(
                marker in body.lower()
                for marker in (b"usage-capped", b"spend cap", b"usage cap")
            ):
                raise PermanentIntegrationError("x_spend_cap_reached")
            if not 200 <= status < 300:
                raise PermanentIntegrationError("x_request_rejected")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except ResponseTooLarge:
            raise PermanentIntegrationError("x_response_too_large") from None
        except (InvalidContentLength, ValueError):
            raise PermanentIntegrationError("x_response_invalid") from None
        except httpx.TransportError:
            raise TransientIntegrationError("x_unavailable") from None
