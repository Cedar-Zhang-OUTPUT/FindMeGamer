"""Small real-provider checks used by the Settings connection screen."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from typing import Iterator

import httpx

from app.core.config import validate_external_base_url


PROBE_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
YOUTUBE_PROBE_CHANNEL_ID = "UC_x5XG1OV2P6uZZ5FSM9Ttw"


class ProductionConnectionProbe:
    """Verify only the provider credentials used by the v1 analysis pipeline.

    Steam Store analysis is public in v1, so a stored Steam Web API key is not
    claimed as valid until the richer Steam integration actually consumes it.
    """

    def __init__(
        self,
        *,
        deepseek_base_url: str,
        youtube_base_url: str,
        google_ai_base_url: str,
        x_base_url: str = "https://api.x.com/2",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._deepseek_base_url = validate_external_base_url(deepseek_base_url)
        self._youtube_base_url = validate_external_base_url(youtube_base_url)
        self._google_ai_base_url = validate_external_base_url(google_ai_base_url)
        self._x_base_url = validate_external_base_url(x_base_url)
        self._http_client = http_client

    def test_connection(self, service: str, secret: str) -> bool:
        if not _valid_secret(secret):
            return False
        try:
            if service == "x":
                return self._get_succeeded(
                    f"{self._x_base_url}/users/by/username/XDevelopers",
                    headers={"Authorization": f"Bearer {secret}"},
                )
            if service == "deepseek":
                return self._get_succeeded(
                    f"{self._deepseek_base_url}/models",
                    headers={"Authorization": f"Bearer {secret}"},
                )
            if service == "youtube":
                return self._get_succeeded(
                    f"{self._youtube_base_url}/channels",
                    headers={"X-Goog-Api-Key": secret},
                    params={"part": "id", "id": YOUTUBE_PROBE_CHANNEL_ID},
                )
            if service == "google_ai":
                return self._get_succeeded(
                    self._google_ai_base_url,
                    headers={"X-Goog-Api-Key": secret},
                )
        except httpx.HTTPError:
            return False
        return False

    def _get_succeeded(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None = None,
    ) -> bool:
        with self._client() as client:
            with client.stream(
                "GET",
                url,
                headers=headers,
                params=params,
                auth=None,
                follow_redirects=False,
                timeout=PROBE_TIMEOUT,
            ) as response:
                return 200 <= response.status_code < 300

    @contextmanager
    def _client(self) -> Iterator[httpx.Client]:
        if self._http_client is not None:
            yield self._http_client
            return
        with httpx.Client(
            timeout=PROBE_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            yield client


def _valid_secret(secret: object) -> bool:
    return (
        isinstance(secret, str)
        and bool(secret)
        and len(secret) <= 16_384
        and not any(character.isspace() or ord(character) < 32 for character in secret)
    )
