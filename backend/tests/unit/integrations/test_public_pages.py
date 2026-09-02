from __future__ import annotations

import socket
import ssl

import pytest

from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.public_pages import (
    PinnedHTTPTransport,
    PublicPageGateway,
    RawPageResponse,
    SocketResolver,
    _PinnedHTTPSConnection,
)


class Resolver:
    def __init__(self, answers: dict[str, tuple[str, ...]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, int]] = []

    def resolve(
        self, hostname: str, port: int, *, deadline=None, clock=None
    ) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        value = self.answers[hostname]
        return value


class Transport:
    def __init__(self, responses: list[RawPageResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs) -> RawPageResponse:
        self.calls.append(kwargs)
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def _response(
    *,
    status: int = 200,
    content_type: str = "text/html; charset=utf-8",
    body: bytes = b"Contact team@example.com",
    location: str | None = None,
) -> RawPageResponse:
    return RawPageResponse(
        status_code=status,
        content_type=content_type,
        content_length=len(body),
        location=location,
        body_chunks=(body,),
    )


class Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_redirects_reresolve_and_pin_each_validated_address() -> None:
    resolver = Resolver(
        {
            "creator.example": ("93.184.216.34",),
            "contact.example": ("142.250.72.14",),
        }
    )
    transport = Transport(
        [
            _response(status=302, body=b"", location="https://contact.example/page"),
            _response(body=b"partnerships@example.com"),
        ]
    )
    gateway = PublicPageGateway(resolver=resolver, transport=transport)

    page = gateway.fetch_page("https://creator.example/about")

    assert page.url == "https://contact.example/page"
    assert page.text == "partnerships@example.com"
    assert resolver.calls == [("creator.example", 443), ("contact.example", 443)]
    assert [
        (call["connect_ip"], call["host_header"], call["server_hostname"])
        for call in transport.calls
    ] == [
        ("93.184.216.34", "creator.example", "creator.example"),
        ("142.250.72.14", "contact.example", "contact.example"),
    ]


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.1",),
        ("169.254.169.254",),
        ("224.0.0.1",),
        ("0.0.0.0",),
        ("93.184.216.34", "127.0.0.1"),
        ("::1",),
        ("fe80::1",),
    ],
)
def test_rejects_if_any_resolved_address_is_not_global(addresses) -> None:
    transport = Transport([_response()])
    gateway = PublicPageGateway(
        resolver=Resolver({"creator.example": addresses}), transport=transport
    )

    with pytest.raises(PermanentIntegrationError, match="public_page_address_rejected"):
        gateway.fetch_page("https://creator.example/about")

    assert transport.calls == []


def test_dns_rebinding_redirect_is_rejected_before_second_connection() -> None:
    resolver = Resolver(
        {"creator.example": ("93.184.216.34",), "evil.example": ("127.0.0.1",)}
    )
    transport = Transport(
        [_response(status=302, body=b"", location="https://evil.example/admin")]
    )
    gateway = PublicPageGateway(resolver=resolver, transport=transport)

    with pytest.raises(PermanentIntegrationError, match="public_page_address_rejected"):
        gateway.fetch_page("https://creator.example/about")

    assert len(transport.calls) == 1


def test_malformed_redirect_location_is_a_typed_page_failure() -> None:
    transport = Transport([_response(status=302, body=b"", location="http://[::1")])
    gateway = PublicPageGateway(
        resolver=Resolver({"creator.example": ("93.184.216.34",)}),
        transport=transport,
    )

    with pytest.raises(PermanentIntegrationError, match="public_page_redirect_invalid"):
        gateway.fetch_page("https://creator.example/about")

    assert len(transport.calls) == 1


def test_redirect_limit_content_type_and_size_are_bounded() -> None:
    resolver = Resolver({"creator.example": ("93.184.216.34",)})
    redirects = Transport(
        [
            _response(status=302, body=b"", location="/one"),
            _response(status=302, body=b"", location="/two"),
        ]
    )
    with pytest.raises(PermanentIntegrationError, match="public_page_redirect_limit"):
        PublicPageGateway(
            resolver=resolver, transport=redirects, max_redirects=1
        ).fetch_page("https://creator.example/start")

    wrong_type = Transport([_response(content_type="application/pdf")])
    with pytest.raises(PermanentIntegrationError, match="public_page_content_type"):
        PublicPageGateway(resolver=resolver, transport=wrong_type).fetch_page(
            "https://creator.example/about"
        )

    oversized_declared = Transport(
        [RawPageResponse(200, "text/html", 9, None, (b"123",))]
    )
    with pytest.raises(PermanentIntegrationError, match="public_page_too_large"):
        PublicPageGateway(
            resolver=resolver, transport=oversized_declared, max_response_bytes=8
        ).fetch_page("https://creator.example/about")

    oversized_stream = Transport(
        [RawPageResponse(200, "text/plain", None, None, (b"1234", b"56789"))]
    )
    with pytest.raises(PermanentIntegrationError, match="public_page_too_large"):
        PublicPageGateway(
            resolver=resolver, transport=oversized_stream, max_response_bytes=8
        ).fetch_page("https://creator.example/about")


def test_dns_and_transport_timeouts_are_safe_typed_failures() -> None:
    class TimeoutResolver:
        def resolve(self, hostname: str, port: int, *, deadline=None, clock=None):
            raise socket.timeout("private resolver detail")

    with pytest.raises(TransientIntegrationError, match="public_page_unavailable"):
        PublicPageGateway(
            resolver=TimeoutResolver(), transport=Transport([])
        ).fetch_page("https://creator.example/about")

    resolver = Resolver({"creator.example": ("93.184.216.34",)})
    transport = Transport([TimeoutError("private transport detail")])
    with pytest.raises(TransientIntegrationError, match="public_page_unavailable"):
        PublicPageGateway(resolver=resolver, transport=transport).fetch_page(
            "https://creator.example/about"
        )


def test_invalid_public_url_is_rejected_without_dns_or_transport() -> None:
    resolver = Resolver({})
    transport = Transport([])
    gateway = PublicPageGateway(resolver=resolver, transport=transport)

    with pytest.raises(PermanentIntegrationError, match="public_page_url_invalid"):
        gateway.fetch_page("http://127.0.0.1/private")

    assert resolver.calls == []
    assert transport.calls == []


def test_unicode_host_uses_ascii_idna_for_policy_dns_host_and_sni() -> None:
    url = "https://例子.测试/contact"
    ascii_host = "xn--fsqu00a.xn--0zwm56d"
    resolver = Resolver({ascii_host: ("93.184.216.34",)})
    transport = Transport([_response()])

    page = PublicPageGateway(resolver=resolver, transport=transport).fetch_page(url)

    assert page.url == url
    assert resolver.calls == [(ascii_host, 443)]
    assert transport.calls[0]["host_header"] == ascii_host
    assert transport.calls[0]["server_hostname"] == ascii_host


def test_idna_deviation_character_is_normalized_before_ascii_case_folding() -> None:
    url = "https://faß.de/contact"
    ascii_host = "xn--fa-hia.de"
    resolver = Resolver(
        {
            ascii_host: ("93.184.216.34",),
            "fass.de": ("93.184.216.34",),
        }
    )
    transport = Transport([_response()])

    page = PublicPageGateway(resolver=resolver, transport=transport).fetch_page(url)

    assert page.url == url
    assert resolver.calls == [(ascii_host, 443)]
    assert transport.calls[0]["host_header"] == ascii_host
    assert transport.calls[0]["server_hostname"] == ascii_host


def test_absolute_deadline_is_passed_to_resolver_and_transport() -> None:
    clock = Clock()

    class DeadlineResolver(Resolver):
        def resolve(self, hostname, port, *, deadline, clock: object):
            assert deadline == 101.0
            assert clock is expected_clock
            return super().resolve(hostname, port)

    expected_clock = clock
    resolver = DeadlineResolver({"creator.example": ("93.184.216.34",)})
    transport = Transport([_response()])

    PublicPageGateway(
        resolver=resolver,
        transport=transport,
        total_timeout_seconds=1.0,
        clock=clock,
    ).fetch_page("https://creator.example/about")

    assert transport.calls[0]["deadline"] == 101.0
    assert transport.calls[0]["clock"] is clock


def test_socket_resolver_rejects_dns_result_that_arrives_after_deadline(
    monkeypatch,
) -> None:
    clock = Clock()

    def late_getaddrinfo(*args, **kwargs):
        clock.value = 101.1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", late_getaddrinfo)

    with pytest.raises(socket.timeout):
        SocketResolver().resolve("creator.example", 443, deadline=101.0, clock=clock)


def test_total_deadline_is_enforced_during_streaming_body_reads() -> None:
    clock = Clock()

    def slow_chunks():
        clock.value += 0.8
        yield b"first"
        clock.value += 0.8
        yield b"second"

    gateway = PublicPageGateway(
        resolver=Resolver({"creator.example": ("93.184.216.34",)}),
        transport=Transport(
            [RawPageResponse(200, "text/html", None, None, slow_chunks())]
        ),
        total_timeout_seconds=1.0,
        clock=clock,
    )

    with pytest.raises(TransientIntegrationError, match="public_page_unavailable"):
        gateway.fetch_page("https://creator.example/about")


class _HeaderResponse:
    status = 200

    def __init__(self, headers: list[tuple[str, str]]) -> None:
        self._headers = headers

    def getheaders(self) -> list[tuple[str, str]]:
        return self._headers

    def getheader(self, name: str):
        values = [
            value for key, value in self._headers if key.casefold() == name.casefold()
        ]
        return values[0] if values else None

    def read(self, amount: int) -> bytes:
        return b""


class _Connection:
    instances: list["_Connection"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.sock = None
        self.closed = False
        self.__class__.instances.append(self)

    def request(self, *args, **kwargs) -> None:
        return None

    def getresponse(self) -> _HeaderResponse:
        return _HeaderResponse(self.headers)

    def close(self) -> None:
        self.closed = True


def test_unicode_request_target_is_ascii_encoded_without_double_encoding(
    monkeypatch,
) -> None:
    class Connection(_Connection):
        instances = []

        def request(self, method, target, *, headers) -> None:
            target.encode("ascii")
            self.target = target

        def getresponse(self) -> _HeaderResponse:
            return _HeaderResponse([("Content-Type", "text/html")])

    monkeypatch.setattr(
        "app.integrations.public_pages._PinnedHTTPConnection", Connection
    )
    clock = Clock()

    PinnedHTTPTransport().request(
        url="http://creator.example/路径?q=雪&keep=%2F",
        connect_ip="93.184.216.34",
        port=80,
        host_header="creator.example",
        server_hostname="creator.example",
        connect_timeout=1.0,
        read_timeout=1.0,
        max_response_bytes=100,
        deadline=101.0,
        clock=clock,
    )

    assert Connection.instances[0].target == "/%E8%B7%AF%E5%BE%84?q=%E9%9B%AA&keep=%2F"


def test_request_target_encoding_failure_is_a_typed_page_error(monkeypatch) -> None:
    class Connection(_Connection):
        instances = []

        def request(self, method, target, *, headers) -> None:
            target.encode("ascii")

    monkeypatch.setattr(
        "app.integrations.public_pages._PinnedHTTPConnection", Connection
    )
    clock = Clock()

    with pytest.raises(PermanentIntegrationError, match="public_page_url_invalid"):
        PinnedHTTPTransport().request(
            url="http://creator.example/" + chr(0xD800),
            connect_ip="93.184.216.34",
            port=80,
            host_header="creator.example",
            server_hostname="creator.example",
            connect_timeout=1.0,
            read_timeout=1.0,
            max_response_bytes=100,
            deadline=101.0,
            clock=clock,
        )


@pytest.mark.parametrize(
    "headers",
    [
        [("Content-Length", "9" * 5_000)],
        [("Content-Length", "1"), ("Content-Length", "1")],
        [("Content-Length", "1"), ("Content-Length", "2")],
        [("Content-Length", "+12")],
        [("Content-Length", "１２")],
    ],
)
def test_malformed_or_duplicate_content_length_is_typed_and_closes_connection(
    monkeypatch, headers
) -> None:
    class Connection(_Connection):
        pass

    Connection.headers = headers
    Connection.instances = []
    monkeypatch.setattr(
        "app.integrations.public_pages._PinnedHTTPConnection", Connection
    )
    clock = Clock()

    with pytest.raises(PermanentIntegrationError, match="public_page_response_invalid"):
        PinnedHTTPTransport().request(
            url="http://creator.example/about",
            connect_ip="93.184.216.34",
            port=80,
            host_header="creator.example",
            server_hostname="creator.example",
            connect_timeout=1.0,
            read_timeout=1.0,
            max_response_bytes=100,
            deadline=101.0,
            clock=clock,
        )

    assert Connection.instances[0].closed is True


def test_pinned_transport_checks_deadline_before_every_body_read(monkeypatch) -> None:
    clock = Clock()

    class Socket:
        def settimeout(self, timeout: float) -> None:
            assert 0 < timeout <= 1.0

    class Response(_HeaderResponse):
        def __init__(self) -> None:
            super().__init__([("Content-Type", "text/html")])
            self.reads = 0

        def read(self, amount: int) -> bytes:
            self.reads += 1
            clock.value += 0.6
            return b"chunk"

    class Connection(_Connection):
        instances = []

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.sock = Socket()

        def getresponse(self) -> Response:
            return Response()

    monkeypatch.setattr(
        "app.integrations.public_pages._PinnedHTTPConnection", Connection
    )

    with pytest.raises(socket.timeout):
        PinnedHTTPTransport().request(
            url="http://creator.example/about",
            connect_ip="93.184.216.34",
            port=80,
            host_header="creator.example",
            server_hostname="creator.example",
            connect_timeout=1.0,
            read_timeout=1.0,
            max_response_bytes=100,
            deadline=101.0,
            clock=clock,
        )

    assert Connection.instances[0].closed is True


def test_tls_handshake_failure_closes_raw_socket(monkeypatch) -> None:
    class RawSocket:
        closed = False

        def close(self) -> None:
            self.closed = True

    class FailingContext:
        def wrap_socket(self, raw_socket, *, server_hostname):
            raise ssl.SSLError("handshake failed")

    raw_socket = RawSocket()
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: raw_socket)
    connection = _PinnedHTTPSConnection(
        "creator.example",
        connect_ip="93.184.216.34",
        port=443,
        timeout=1.0,
        context=FailingContext(),
    )

    with pytest.raises(ssl.SSLError, match="handshake failed"):
        connection.connect()

    assert raw_socket.closed is True
