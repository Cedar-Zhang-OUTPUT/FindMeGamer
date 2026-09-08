"""Two bounded official reads for one selected X account; no automatic paging."""

import json
from datetime import UTC, datetime

import httpx

from app.analysis.x_source import XCreatorSource
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.http import (
    InvalidContentLength,
    ResponseTooLarge,
    read_bounded_bytes,
    streaming_response,
)
from app.integrations.x_discovery import (
    XDiscoveryGateway,
    _identifier,
    _text,
    _count,
    _public_url,
)
from app.schemas.discovery import DiscoveredAccount, DiscoveryRequest


class XCreatorGateway(XDiscoveryGateway):
    """Reuse the existing credential/client ownership and public metadata mapper."""

    def _read(self, path, params):
        try:
            with streaming_response(
                self._client,
                "GET",
                f"{self._base_url}/{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=httpx.Timeout(connect=5, read=20, write=10, pool=5),
                follow_redirects=False,
            ) as response:
                if response.status_code == 429 or response.status_code >= 500:
                    raise TransientIntegrationError("x_unavailable")
                if response.status_code == 404:
                    raise PermanentIntegrationError("x_account_not_found")
                if response.status_code != 200:
                    raise PermanentIntegrationError("x_request_rejected")
                payload = json.loads(read_bounded_bytes(response, max_bytes=4_000_000))
        except (httpx.TimeoutException, httpx.HTTPError):
            raise TransientIntegrationError("x_unavailable") from None
        except (ValueError, ResponseTooLarge, InvalidContentLength):
            raise PermanentIntegrationError("x_response_invalid") from None
        if not isinstance(payload, dict) or payload.get("errors"):
            raise PermanentIntegrationError("x_response_invalid")
        return payload

    def fetch_creator(self, account_id: str) -> XCreatorSource:
        if not _identifier(account_id):
            raise PermanentIntegrationError("x_account_id_invalid")
        user_payload = self._read(
            f"users/{account_id}",
            {
                "user.fields": "name,username,description,public_metrics,location,profile_image_url,protected",
            },
        )
        user = user_payload.get("data")
        if not isinstance(user, dict) or user.get("id") != account_id:
            raise PermanentIntegrationError("x_source_identity_mismatch")
        if user.get("protected") is True:
            raise PermanentIntegrationError("x_request_rejected")
        metrics = user.get("public_metrics")
        account = DiscoveredAccount(
            platform="x",
            account_id=account_id,
            profile_url=f"https://x.com/i/user/{account_id}",
            display_name=_text(user.get("name")),
            handle=_text(user.get("username")),
            description=_text(user.get("description")),
            follower_count=(
                _count(metrics.get("followers_count"))
                if isinstance(metrics, dict)
                else None
            ),
            location_text=_text(user.get("location")),
            avatar_url=_public_url(user.get("profile_image_url")),
            collected_at=datetime.now(UTC),
        )
        payload = self._read(
            f"users/{account_id}/tweets",
            {
                "max_results": "50",
                "exclude": "retweets,replies",
                "tweet.fields": "author_id,created_at,lang,public_metrics",
            },
        )
        data = payload.get("data", [])
        if (
            not isinstance(data, list)
            or len(data) > 50
            or any(
                not isinstance(item, dict) or item.get("author_id") != account_id
                for item in data
            )
        ):
            raise PermanentIntegrationError("x_source_identity_mismatch")
        page = self._normalize(
            {**payload, "includes": {"users": [user]}},
            DiscoveryRequest(platform="x", query=f"from:{account_id}", page_size=50),
        )
        if page.status not in {"complete", "more"}:
            raise PermanentIntegrationError("x_response_invalid")
        return XCreatorSource(
            account=account,
            contents=page.contents,
            more_available=page.next_cursor is not None,
        )
