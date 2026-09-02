from __future__ import annotations

import socket

import pytest

from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.public_pages import (
    PublicPageGateway,
    RawPageResponse,
)


class Resolver:
    def __init__(self, answers: dict[str, tuple[str, ...]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, int]] = []

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
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
        def resolve(self, hostname: str, port: int):
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
