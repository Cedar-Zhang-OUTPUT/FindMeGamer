"""Download bounded public images for inline model input without DNS rebinding."""

from __future__ import annotations

import base64
from ipaddress import ip_address
from time import monotonic
from typing import Callable
from urllib.parse import urljoin

from app.integrations.errors import (
    IntegrationError,
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.integrations.public_pages import (
    HostResolver,
    PageTransport,
    PinnedHTTPTransport,
    SocketResolver,
    _remaining,
    _validated_url,
)


MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 3
TOTAL_TIMEOUT_SECONDS = 15.0
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CONTENT_TYPES = frozenset(
    {
        "",
        "application/octet-stream",
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    }
)


class VisionImageLoader:
    def __init__(
        self,
        *,
        resolver: HostResolver | None = None,
        transport: PageTransport | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._resolver = resolver or SocketResolver()
        self._transport = transport or PinnedHTTPTransport(
            accept="image/jpeg,image/png,image/gif,image/webp",
            user_agent="FindMeGamer/1.0 vision-analysis",
        )
        self._clock = clock

    def load(self, url: str) -> str:
        """Return a detected raster MIME type and Base64 bytes, never a remote URL."""
        try:
            return self._load(url)
        except (TimeoutError, OSError):
            raise TransientIntegrationError("vision_image_unavailable") from None
        except IntegrationError as error:
            if error.code.startswith("vision_image_"):
                raise
            raise PermanentIntegrationError("vision_image_response_invalid") from None
        except Exception:
            raise PermanentIntegrationError("vision_image_response_invalid") from None

    def _load(self, url: str) -> str:
        deadline = self._clock() + TOTAL_TIMEOUT_SECONDS
        current = url
        for redirect_count in range(MAX_REDIRECTS + 1):
            _remaining(deadline, self._clock)
            try:
                parsed, hostname = _validated_url(current)
                if parsed.scheme != "https":
                    raise ValueError("HTTPS required")
            except (IntegrationError, ValueError):
                raise PermanentIntegrationError("vision_image_url_invalid") from None
            port = parsed.port or 443
            connect_ip = self._resolve_public_ip(hostname, port, deadline)
            _remaining(deadline, self._clock)
            response = self._transport.request(
                url=current,
                connect_ip=connect_ip,
                port=port,
                host_header=hostname if parsed.port is None else f"{hostname}:{port}",
                server_hostname=hostname,
                connect_timeout=5.0,
                read_timeout=8.0,
                max_response_bytes=MAX_IMAGE_BYTES,
                deadline=deadline,
                clock=self._clock,
            )
            _remaining(deadline, self._clock)
            if response.status_code in _REDIRECT_STATUSES:
                if redirect_count >= MAX_REDIRECTS:
                    raise PermanentIntegrationError("vision_image_redirect_limit")
                if not response.location:
                    raise PermanentIntegrationError("vision_image_redirect_invalid")
                try:
                    current = urljoin(current, response.location)
                except (ValueError, TypeError):
                    raise PermanentIntegrationError(
                        "vision_image_redirect_invalid"
                    ) from None
                continue
            if response.status_code == 429 or response.status_code >= 500:
                raise TransientIntegrationError("vision_image_unavailable")
            if response.status_code != 200:
                raise PermanentIntegrationError("vision_image_request_rejected")
            content_type = (
                (response.content_type or "").split(";", 1)[0].strip().lower()
            )
            if content_type not in _CONTENT_TYPES:
                raise PermanentIntegrationError("vision_image_content_invalid")
            if (
                response.content_length is not None
                and response.content_length > MAX_IMAGE_BYTES
            ):
                raise PermanentIntegrationError("vision_image_too_large")
            body = bytearray()
            for chunk in response.body_chunks:
                _remaining(deadline, self._clock)
                if not isinstance(chunk, bytes):
                    raise PermanentIntegrationError("vision_image_response_invalid")
                if len(body) + len(chunk) > MAX_IMAGE_BYTES:
                    raise PermanentIntegrationError("vision_image_too_large")
                body.extend(chunk)
            _remaining(deadline, self._clock)
            image_type = _image_type(body)
            encoded = base64.b64encode(body).decode("ascii")
            _remaining(deadline, self._clock)
            return f"data:image/{image_type};base64,{encoded}"
        raise PermanentIntegrationError("vision_image_redirect_limit")

    def _resolve_public_ip(self, hostname: str, port: int, deadline: float) -> str:
        values = self._resolver.resolve(
            hostname, port, deadline=deadline, clock=self._clock
        )
        if not values:
            raise TransientIntegrationError("vision_image_unavailable")
        addresses = []
        try:
            for value in values:
                address = ip_address(value)
                if (
                    not address.is_global
                    or address.is_loopback
                    or address.is_private
                    or address.is_link_local
                    or address.is_multicast
                    or address.is_reserved
                    or address.is_unspecified
                ):
                    raise ValueError("not a public address")
                addresses.append(address.compressed)
        except ValueError:
            raise PermanentIntegrationError("vision_image_address_rejected") from None
        return sorted(set(addresses))[0]


def _image_type(body: bytes | bytearray) -> str:
    if len(body) >= 4 and body.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(body) > 8 and body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(body) > 6 and body[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if len(body) > 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "webp"
    raise PermanentIntegrationError("vision_image_content_invalid")
