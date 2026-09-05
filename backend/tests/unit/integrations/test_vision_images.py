from __future__ import annotations

import base64
import socket

import pytest

from app.integrations.errors import IntegrationError, PermanentIntegrationError
from app.integrations.public_pages import PinnedHTTPTransport, RawPageResponse
from app.integrations.vision_images import VisionImageLoader


JPEG = b"\xff\xd8\xff\xe0image-bytes\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\nimage-bytes"
GIF = b"GIF89aimage-bytes"
WEBP = b"RIFF\x10\x00\x00\x00WEBPimage-bytes"
URL = "https://images.example/thumbnail.jpg"


class Resolver:
    def __init__(self, answers=None):
        self.answers = answers or {"images.example": ("142.250.72.14",)}
        self.calls = []

    def resolve(self, hostname, port, *, deadline, clock):
        self.calls.append((hostname, port, deadline))
        value = self.answers[hostname]
        if isinstance(value, Exception):
            raise value
        return value


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def response(body=JPEG, *, content_type="image/jpeg", status=200, location=None):
    return RawPageResponse(status, content_type, len(body), location, (body,))


@pytest.mark.parametrize(
    ("body", "mime"),
    [(JPEG, "jpeg"), (PNG, "png"), (GIF, "gif"), (WEBP, "webp")],
)
def test_load_embeds_detected_image_bytes_and_pins_ip_with_tls_hostname(body, mime):
    transport = Transport(response(body, content_type="application/octet-stream"))
    loader = VisionImageLoader(resolver=Resolver(), transport=transport)

    result = loader.load(URL)

    assert result == f"data:image/{mime};base64,{base64.b64encode(body).decode()}"
    call = transport.calls[0]
    assert call["connect_ip"] == "142.250.72.14"
    assert call["server_hostname"] == call["host_header"] == "images.example"
    assert call["port"] == 443
    assert call["max_response_bytes"] == 4 * 1024 * 1024


@pytest.mark.parametrize(
    "url",
    [
        "http://images.example/image.jpg",
        "https://127.0.0.1/image.jpg",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/image.jpg",
        "https://user:secret@images.example/image.jpg",
        "file:///private/image.jpg",
        "https://localhost/image.jpg",
        "https://images.example:0/image.jpg",
    ],
)
def test_unsafe_urls_are_rejected_without_resolving_or_connecting(url):
    resolver, transport = Resolver(), Transport()

    with pytest.raises(IntegrationError, match="vision_image_url_invalid"):
        VisionImageLoader(resolver=resolver, transport=transport).load(url)

    assert resolver.calls == transport.calls == []


@pytest.mark.parametrize(
    "addresses",
    [
        ("10.0.0.1",),
        ("169.254.169.254",),
        ("142.250.72.14", "127.0.0.1"),
        ("142.250.72.14", "::1"),
        ("224.0.0.1",),
        ("fe80::1",),
    ],
)
def test_every_dns_answer_must_be_public(addresses):
    resolver = Resolver({"images.example": addresses})
    transport = Transport()

    with pytest.raises(IntegrationError, match="vision_image_address_rejected"):
        VisionImageLoader(resolver=resolver, transport=transport).load(URL)

    assert transport.calls == []


def test_redirect_revalidates_and_resolves_destination_with_same_deadline():
    resolver = Resolver(
        {"images.example": ("142.250.72.14",), "cdn.example": ("93.184.216.34",)}
    )
    transport = Transport(
        response(b"", status=302, location="https://cdn.example/final.jpg"),
        response(),
    )

    assert (
        VisionImageLoader(resolver=resolver, transport=transport)
        .load(URL)
        .startswith("data:image/jpeg;base64,")
    )
    assert [call[0] for call in resolver.calls] == ["images.example", "cdn.example"]
    assert resolver.calls[0][2] == resolver.calls[1][2]
    assert transport.calls[1]["connect_ip"] == "93.184.216.34"
    assert transport.calls[1]["server_hostname"] == "cdn.example"


@pytest.mark.parametrize(
    "location", ["http://images.example/plain.jpg", "https://127.0.0.1/private"]
)
def test_redirect_cannot_downgrade_tls_or_introduce_ip_literal(location):
    resolver = Resolver()
    transport = Transport(response(b"", status=302, location=location))

    with pytest.raises(IntegrationError, match="vision_image_url_invalid"):
        VisionImageLoader(resolver=resolver, transport=transport).load(URL)

    assert len(transport.calls) == len(resolver.calls) == 1


def test_redirect_to_private_dns_is_blocked_before_connection():
    resolver = Resolver(
        {"images.example": ("142.250.72.14",), "metadata.example": ("169.254.169.254",)}
    )
    transport = Transport(
        response(b"", status=302, location="https://metadata.example/private")
    )

    with pytest.raises(IntegrationError, match="vision_image_address_rejected"):
        VisionImageLoader(resolver=resolver, transport=transport).load(URL)

    assert len(transport.calls) == 1


def test_at_most_three_redirects_are_followed():
    transport = Transport(*[response(b"", status=302, location="/again")] * 4)

    with pytest.raises(IntegrationError, match="vision_image_redirect_limit"):
        VisionImageLoader(resolver=Resolver(), transport=transport).load(URL)

    assert len(transport.calls) == 4


@pytest.mark.parametrize(
    ("body", "mime"),
    [
        (b"", "image/jpeg"),
        (b"<html>not an image</html>", "image/jpeg"),
        (b"<svg></svg>", "image/svg+xml"),
        (JPEG, "text/html"),
        (b"RIFF1234WAVEaudio", "image/webp"),
    ],
)
def test_rejects_empty_or_unsupported_content_even_with_image_content_type(body, mime):
    with pytest.raises(IntegrationError, match="vision_image_content_invalid"):
        VisionImageLoader(
            resolver=Resolver(), transport=Transport(response(body, content_type=mime))
        ).load(URL)


@pytest.mark.parametrize("declared", [True, False])
def test_declared_and_streamed_body_cannot_exceed_four_mib(declared):
    oversized = 4 * 1024 * 1024 + 1
    raw = RawPageResponse(
        200,
        "image/jpeg",
        oversized if declared else None,
        None,
        (JPEG,) if declared else (b"x" * oversized,),
    )

    with pytest.raises(IntegrationError, match="vision_image_too_large"):
        VisionImageLoader(resolver=Resolver(), transport=Transport(raw)).load(URL)


def test_total_deadline_includes_dns_and_redirects():
    now = [100.0]

    class SlowResolver(Resolver):
        def resolve(self, *args, **kwargs):
            value = super().resolve(*args, **kwargs)
            now[0] += 8.0
            return value

    transport = Transport(response(b"", status=302, location="/second"), response())
    loader = VisionImageLoader(
        resolver=SlowResolver(), transport=transport, clock=lambda: now[0]
    )

    with pytest.raises(IntegrationError, match="vision_image_unavailable"):
        loader.load(URL)

    assert len(transport.calls) == 1


def test_total_deadline_includes_body_stream():
    now = [100.0]

    def chunks():
        now[0] += 16.0
        yield JPEG

    raw = RawPageResponse(200, "image/jpeg", None, None, chunks())
    with pytest.raises(IntegrationError, match="vision_image_unavailable"):
        VisionImageLoader(
            resolver=Resolver(), transport=Transport(raw), clock=lambda: now[0]
        ).load(URL)


@pytest.mark.parametrize("status", [404, 429, 503])
def test_non_success_http_status_is_a_safe_failure(status):
    with pytest.raises(IntegrationError) as caught:
        VisionImageLoader(
            resolver=Resolver(), transport=Transport(response(status=status))
        ).load(URL)

    assert caught.value.retryable == (status != 404)


@pytest.mark.parametrize("stage", ["dns", "request", "stream"])
def test_network_errors_hide_sensitive_details(stage, caplog):
    sentinel = "secret-key-response-canary"
    resolver = Resolver()
    transport = Transport(response())
    if stage == "dns":
        resolver = Resolver({"images.example": socket.timeout(sentinel)})
    elif stage == "request":
        transport = Transport(OSError(sentinel))
    else:

        def chunks():
            raise OSError(sentinel)
            yield b""

        transport = Transport(RawPageResponse(200, "image/jpeg", None, None, chunks()))

    with pytest.raises(IntegrationError) as caught:
        VisionImageLoader(resolver=resolver, transport=transport).load(URL)

    assert caught.value.retryable
    assert sentinel not in str(caught.value)
    assert sentinel not in caplog.text


def test_transport_protocol_error_is_a_safe_vision_failure():
    with pytest.raises(IntegrationError, match="vision_image_response_invalid"):
        VisionImageLoader(
            resolver=Resolver(),
            transport=Transport(
                PermanentIntegrationError("public_page_response_invalid")
            ),
        ).load(URL)


@pytest.mark.parametrize("image_request", [False, True])
def test_transport_uses_scoped_headers_without_credentials(monkeypatch, image_request):
    requests = []

    class Response:
        status = 200

        def getheaders(self):
            return [("Content-Type", "image/jpeg"), ("Content-Length", str(len(JPEG)))]

        def getheader(self, name):
            return dict(self.getheaders()).get(name)

        def read(self, amount):
            if requests[0].get("read"):
                return b""
            requests[0]["read"] = True
            return JPEG

    class Connection:
        sock = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, target, *, headers):
            requests.append({"headers": headers})

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        "app.integrations.public_pages._PinnedHTTPSConnection", Connection
    )
    if image_request:
        VisionImageLoader(resolver=Resolver()).load(URL)
    else:
        PinnedHTTPTransport().request(
            url=URL,
            connect_ip="142.250.72.14",
            port=443,
            host_header="images.example",
            server_hostname="images.example",
            connect_timeout=5.0,
            read_timeout=8.0,
            max_response_bytes=4 * 1024 * 1024,
            deadline=115.0,
            clock=lambda: 100.0,
        )

    headers = requests[0]["headers"]
    assert headers == {
        "Host": "images.example",
        "Connection": "close",
        "Accept": (
            "image/jpeg,image/png,image/gif,image/webp"
            if image_request
            else "text/html,text/plain,application/xhtml+xml"
        ),
        "User-Agent": (
            "FindMeGamer/1.0 vision-analysis"
            if image_request
            else "FindMeGamer/1.0 contact-discovery"
        ),
    }
