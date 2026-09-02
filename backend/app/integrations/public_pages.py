"""Bounded, DNS-rebinding-safe fetching of creator-linked public pages."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
from ipaddress import ip_address
import socket
import ssl
from time import monotonic
from typing import Callable, Iterable, Protocol
from urllib.parse import urljoin, urlsplit

from pydantic import ValidationError

from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.schemas.ai_creator import URLContactCandidate


DEFAULT_MAX_REDIRECTS = 3
DEFAULT_MAX_RESPONSE_BYTES = 256_000
DEFAULT_MAX_DECODED_CHARACTERS = 256_000
DEFAULT_TOTAL_TIMEOUT_SECONDS = 15.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_READ_TIMEOUT_SECONDS = 8.0
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_TEXT_CONTENT_TYPES = frozenset({"text/html", "text/plain", "application/xhtml+xml"})


@dataclass(frozen=True, slots=True)
class PublicPage:
    url: str
    text: str
    content_type: str


@dataclass(frozen=True, slots=True)
class RawPageResponse:
    status_code: int
    content_type: str | None
    content_length: int | None
    location: str | None
    body_chunks: Iterable[bytes]


class HostResolver(Protocol):
    def resolve(self, hostname: str, port: int) -> tuple[str, ...]: ...


class PageTransport(Protocol):
    def request(
        self,
        *,
        url: str,
        connect_ip: str,
        port: int,
        host_header: str,
        server_hostname: str,
        connect_timeout: float,
        read_timeout: float,
        max_response_bytes: int,
    ) -> RawPageResponse: ...


class SocketResolver:
    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        records = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        return tuple(sorted({record[4][0] for record in records}))


class PinnedHTTPTransport:
    """Connect to a validated IP while preserving HTTP Host and TLS SNI."""

    def request(
        self,
        *,
        url: str,
        connect_ip: str,
        port: int,
        host_header: str,
        server_hostname: str,
        connect_timeout: float,
        read_timeout: float,
        max_response_bytes: int,
    ) -> RawPageResponse:
        parsed = urlsplit(url)
        connection: http.client.HTTPConnection
        if parsed.scheme == "https":
            connection = _PinnedHTTPSConnection(
                server_hostname,
                connect_ip=connect_ip,
                port=port,
                timeout=connect_timeout,
                context=ssl.create_default_context(),
            )
        else:
            connection = _PinnedHTTPConnection(
                server_hostname,
                connect_ip=connect_ip,
                port=port,
                timeout=connect_timeout,
            )
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Host": host_header,
                    "Accept": "text/html,text/plain,application/xhtml+xml",
                    "User-Agent": "FindMeGamer/1.0 contact-discovery",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if connection.sock is not None:
                connection.sock.settimeout(read_timeout)
            chunks: list[bytes] = []
            received = 0
            while True:
                chunk = response.read(min(16_384, max_response_bytes + 1 - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
                if received > max_response_bytes:
                    break
            raw_length = response.getheader("Content-Length")
            content_length = (
                int(raw_length)
                if raw_length is not None
                and raw_length.isascii()
                and raw_length.isdecimal()
                else None
            )
            return RawPageResponse(
                status_code=response.status,
                content_type=response.getheader("Content-Type"),
                content_length=content_length,
                location=response.getheader("Location"),
                body_chunks=tuple(chunks),
            )
        finally:
            connection.close()


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, *, connect_ip: str, **kwargs: object) -> None:
        self._connect_ip = connect_ip
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, *, connect_ip: str, **kwargs: object) -> None:
        self._connect_ip = connect_ip
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


class PublicPageGateway:
    def __init__(
        self,
        *,
        resolver: HostResolver | None = None,
        transport: PageTransport | None = None,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_decoded_characters: int = DEFAULT_MAX_DECODED_CHARACTERS,
        total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if (
            type(max_redirects) is not int
            or not 0 <= max_redirects <= 5
            or type(max_response_bytes) is not int
            or not 1 <= max_response_bytes <= 1_000_000
            or type(max_decoded_characters) is not int
            or not 1 <= max_decoded_characters <= 1_000_000
            or not all(
                type(value) is float and 0 < value <= 60
                for value in (
                    total_timeout_seconds,
                    connect_timeout_seconds,
                    read_timeout_seconds,
                )
            )
        ):
            raise ValueError("invalid public-page bounds")
        self._resolver = resolver or SocketResolver()
        self._transport = transport or PinnedHTTPTransport()
        self._max_redirects = max_redirects
        self._max_response_bytes = max_response_bytes
        self._max_decoded_characters = max_decoded_characters
        self._total_timeout_seconds = total_timeout_seconds
        self._connect_timeout_seconds = connect_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._clock = clock

    def fetch_page(self, url: str) -> PublicPage:
        current = url
        started = self._clock()
        for redirect_count in range(self._max_redirects + 1):
            self._check_elapsed(started)
            parsed = _validated_url(current)
            hostname = parsed.hostname
            assert hostname is not None
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addresses = self._resolve_global_addresses(hostname, port)
            connect_ip = addresses[0]
            host_header = hostname
            if parsed.port is not None:
                host_header = f"{hostname}:{parsed.port}"
            try:
                response = self._transport.request(
                    url=current,
                    connect_ip=connect_ip,
                    port=port,
                    host_header=host_header,
                    server_hostname=hostname,
                    connect_timeout=self._connect_timeout_seconds,
                    read_timeout=self._read_timeout_seconds,
                    max_response_bytes=self._max_response_bytes,
                )
            except (TimeoutError, socket.timeout, OSError):
                raise TransientIntegrationError("public_page_unavailable") from None
            self._check_elapsed(started)
            if response.status_code in _REDIRECT_STATUSES:
                if redirect_count >= self._max_redirects:
                    raise PermanentIntegrationError("public_page_redirect_limit")
                if not response.location:
                    raise PermanentIntegrationError("public_page_redirect_invalid")
                current = urljoin(current, response.location)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                raise TransientIntegrationError("public_page_unavailable")
            if response.status_code >= 400:
                raise PermanentIntegrationError("public_page_request_rejected")
            content_type = (
                (response.content_type or "").split(";", 1)[0].strip().casefold()
            )
            if content_type not in _TEXT_CONTENT_TYPES:
                raise PermanentIntegrationError("public_page_content_type_invalid")
            if (
                response.content_length is not None
                and response.content_length > self._max_response_bytes
            ):
                raise PermanentIntegrationError("public_page_too_large")
            body = self._bounded_body(response.body_chunks)
            text = _decode_text(body, response.content_type)
            if len(text) > self._max_decoded_characters:
                raise PermanentIntegrationError("public_page_too_large")
            return PublicPage(url=current, text=text, content_type=content_type)
        raise AssertionError("bounded redirect loop exhausted")

    def _resolve_global_addresses(self, hostname: str, port: int) -> tuple[str, ...]:
        try:
            addresses = self._resolver.resolve(hostname, port)
        except (TimeoutError, socket.timeout, OSError):
            raise TransientIntegrationError("public_page_unavailable") from None
        if not addresses:
            raise TransientIntegrationError("public_page_unavailable")
        normalized: list[str] = []
        try:
            for value in addresses:
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
                    raise PermanentIntegrationError("public_page_address_rejected")
                normalized.append(address.compressed)
        except ValueError:
            raise PermanentIntegrationError("public_page_address_rejected") from None
        return tuple(sorted(set(normalized)))

    def _bounded_body(self, chunks: Iterable[bytes]) -> bytes:
        result = bytearray()
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise PermanentIntegrationError("public_page_response_invalid")
            result.extend(chunk)
            if len(result) > self._max_response_bytes:
                raise PermanentIntegrationError("public_page_too_large")
        return bytes(result)

    def _check_elapsed(self, started: float) -> None:
        if self._clock() - started > self._total_timeout_seconds:
            raise TransientIntegrationError("public_page_unavailable")


def _validated_url(url: str):
    try:
        URLContactCandidate(
            candidate_id="public-page.validation",
            kind="linked_site",
            value=url,
            source_type="linked_public_page",
            source_url=url,
            validation_state="unvalidated",
        )
        parsed = urlsplit(url)
        parsed.port
    except (ValidationError, ValueError, TypeError):
        raise PermanentIntegrationError("public_page_url_invalid") from None
    return parsed


def _decode_text(body: bytes, content_type: str | None) -> str:
    charset = "utf-8"
    if content_type:
        for part in content_type.split(";")[1:]:
            key, separator, value = part.partition("=")
            if separator and key.strip().casefold() == "charset":
                candidate = value.strip().strip('"').casefold()
                if candidate in {"utf-8", "us-ascii", "iso-8859-1"}:
                    charset = candidate
                break
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


__all__ = ["PublicPage", "PublicPageGateway", "RawPageResponse"]
