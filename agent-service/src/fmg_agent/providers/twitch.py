"""Server-only Twitch OAuth for the single-process gateway.

App credentials are cached; user refresh rotations are atomically persisted in a
private mounted directory. No OAuth tokens are returned to CLI callers or logged.
"""

import asyncio
import json
import os
import tempfile
import time

import httpx

from ..errors import ApiError
from .logging import protect_http_logs


class TwitchAuth:
    def __init__(self, settings):
        self.settings = settings
        self.lock = asyncio.Lock()
        self.tokens = {}
        self.checked = {}
        self.expires = {}
        self.refresh = settings.twitch_refresh_token.get_secret_value()
        self.loaded = False

    def invalidate(self, kind):
        self.checked.pop(kind, None)
        self.expires[kind] = 0

    def load_user(self):
        if self.loaded:
            return
        path = self.settings.twitch_token_store
        try:
            if path and path.exists():
                data = json.loads(path.read_text())
                if data["client_id"] != self.settings.twitch_client_id:
                    raise ValueError()
                self.tokens["twitch-user"] = data["access_token"]
                self.refresh = data["refresh_token"]
            else:
                self.tokens["twitch-user"] = (
                    self.settings.twitch_user_token.get_secret_value()
                )
        except (OSError, ValueError, KeyError, TypeError):
            raise ApiError(
                503, "configuration_missing", "Repair the server Twitch token store."
            ) from None
        self.loaded = True

    def persist(self, token, refresh):
        path = self.settings.twitch_token_store
        if path is None:
            raise ApiError(
                503,
                "configuration_missing",
                "Configure a persistent private Twitch token store before refreshing.",
            )
        name = None
        try:
            # The administrator provisions/mounts the directory; never silently
            # place secrets in a disposable container filesystem.
            fd, name = tempfile.mkstemp(prefix=".twitch-", dir=path.parent)
            with os.fdopen(fd, "w") as stream:
                json.dump(
                    {
                        "client_id": self.settings.twitch_client_id,
                        "access_token": token,
                        "refresh_token": refresh,
                    },
                    stream,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        except OSError:
            raise ApiError(
                503,
                "configuration_missing",
                "Twitch token rotation could not be saved; repair server storage.",
            ) from None
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    async def token(self, kind, transport=None):
        protect_http_logs()
        s = self.settings
        if not s.twitch_client_id or not s.twitch_client_secret.get_secret_value():
            raise ApiError(
                503,
                "configuration_missing",
                "Company Twitch credentials are not configured.",
            )
        async with self.lock:
            if kind == "twitch-user":
                self.load_user()
            now = time.monotonic()
            if (
                self.tokens.get(kind)
                and now - self.checked.get(kind, -3601) < 3600
                and self.expires.get(kind, 0) > now + 60
            ):
                return self.tokens[kind]
            try:
                async with httpx.AsyncClient(
                    timeout=30,
                    transport=transport,
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    token = self.tokens.get(kind)
                    if token:
                        info = await self.validate(client, token, kind)
                        if info is not None and info.get("expires_in", 0) > 60:
                            self.mark(kind, token, info["expires_in"])
                            return token
                    if kind == "twitch-user" and (
                        not self.refresh or s.twitch_token_store is None
                    ):
                        raise ApiError(
                            403,
                            "provider_authorization_required",
                            "Company Twitch user authorization needs renewal and persistent token storage.",
                        )
                    body = {
                        "client_id": s.twitch_client_id,
                        "client_secret": s.twitch_client_secret.get_secret_value(),
                        "grant_type": (
                            "refresh_token"
                            if kind == "twitch-user"
                            else "client_credentials"
                        ),
                    }
                    if kind == "twitch-user":
                        body["refresh_token"] = self.refresh
                    response = await client.post(
                        "https://id.twitch.tv/oauth2/token", data=body
                    )
                    self.check_response(response)
                    data = response.json()
                    token = data["access_token"]
                    if not isinstance(token, str) or not token:
                        raise ValueError()
                    if kind == "twitch-user":
                        refresh = data["refresh_token"]
                        if not isinstance(refresh, str) or not refresh:
                            raise ValueError()
                        self.persist(token, refresh)
                        self.refresh = refresh
                        self.tokens[kind] = token
                    info = await self.validate(client, token, kind)
                    if info is None:
                        raise ApiError(
                            403,
                            "provider_authorization_required",
                            "Twitch rejected the new authorization.",
                        )
                    self.mark(kind, token, info["expires_in"])
                    return token
            except httpx.TimeoutException:
                raise ApiError(
                    504,
                    "upstream_timeout",
                    "Twitch authorization timed out.",
                    retryable=True,
                ) from None
            except httpx.HTTPError:
                raise ApiError(
                    502,
                    "upstream_unavailable",
                    "Twitch authorization connection failed.",
                    retryable=True,
                ) from None
            except (ValueError, KeyError, TypeError):
                raise ApiError(
                    502,
                    "invalid_provider_response",
                    "Twitch returned invalid authorization metadata.",
                ) from None

    def mark(self, kind, token, expires):
        self.tokens[kind] = token
        self.checked[kind] = time.monotonic()
        self.expires[kind] = time.monotonic() + int(expires)

    @staticmethod
    def check_response(response):
        if response.status_code == 429:
            from .transport import retry_after

            raise ApiError(
                429,
                "rate_limited",
                "Twitch authorization rate limit reached.",
                retryable=True,
                retry_after_seconds=retry_after(response.headers),
            )
        if response.status_code >= 500:
            raise ApiError(
                502,
                "upstream_unavailable",
                "Twitch authorization is unavailable.",
                retryable=True,
            )
        if response.status_code != 200:
            raise ApiError(
                403,
                "provider_authorization_required",
                "Repair company Twitch authorization.",
            )

    async def validate(self, client, token, kind):
        response = await client.get(
            "https://id.twitch.tv/oauth2/validate",
            headers={"Authorization": "OAuth " + token},
        )
        if response.status_code == 401:
            return None
        self.check_response(response)
        info = response.json()
        if info.get("client_id") != self.settings.twitch_client_id or (
            kind == "twitch-user" and not info.get("user_id")
        ):
            raise ApiError(
                403,
                "provider_authorization_required",
                "Twitch authorization belongs to a different application or token type.",
            )
        return info

    async def maintain(self, transport=None):
        """Validate configured sessions on startup, then hourly, without blocking other providers."""
        while True:
            kinds = ["twitch-app"]
            if (
                self.settings.twitch_user_token.get_secret_value()
                or self.settings.twitch_refresh_token.get_secret_value()
                or self.settings.twitch_token_store
            ):
                kinds.append("twitch-user")
            for kind in kinds:
                try:
                    self.checked.pop(kind, None)
                    await self.token(kind, transport)
                except ApiError:
                    self.invalidate(kind)
            await asyncio.sleep(3540)
