import gzip

import httpx
import pytest

from app.integrations.http import (
    InvalidContentLength,
    ResponseTooLarge,
    read_bounded_bytes,
    streaming_response,
)


class TrackingByteStream(httpx.SyncByteStream):
    def __init__(
        self,
        chunks: list[bytes],
        *,
        error_after: int | None = None,
    ) -> None:
        self.chunks = chunks
        self.error_after = error_after
        self.yielded = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            if self.error_after is not None and self.yielded == self.error_after:
                raise httpx.ReadTimeout("stream-timeout-canary")
            self.yielded += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


def _client_for_stream(
    stream: TrackingByteStream,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers=headers, stream=stream)
        )
    )


def test_bounded_reader_stops_chunked_body_at_first_overflow_and_closes() -> None:
    stream = TrackingByteStream([b"1234", b"56", b"must-not-be-read"])
    client = _client_for_stream(stream)

    with pytest.raises(ResponseTooLarge):
        with streaming_response(
            client,
            "GET",
            "https://provider.example/data",
            timeout=httpx.Timeout(1.0),
        ) as response:
            read_bounded_bytes(response, max_bytes=5)

    assert stream.yielded == 2
    assert stream.closed is True


def test_bounded_reader_does_not_trust_small_content_length() -> None:
    stream = TrackingByteStream([b"1234", b"56", b"must-not-be-read"])
    client = _client_for_stream(stream, headers={"Content-Length": "1"})

    with pytest.raises(ResponseTooLarge):
        with streaming_response(
            client,
            "GET",
            "https://provider.example/data",
            timeout=httpx.Timeout(1.0),
        ) as response:
            read_bounded_bytes(response, max_bytes=5)

    assert stream.yielded == 2
    assert stream.closed is True


def test_bounded_reader_stops_after_one_chunk_larger_than_cap() -> None:
    stream = TrackingByteStream([b"123456", b"must-not-be-read"])
    client = _client_for_stream(stream)

    with pytest.raises(ResponseTooLarge):
        with streaming_response(
            client,
            "GET",
            "https://provider.example/data",
            timeout=httpx.Timeout(1.0),
        ) as response:
            read_bounded_bytes(response, max_bytes=5)

    assert stream.yielded == 1
    assert stream.closed is True


def test_bounded_reader_rejects_large_declared_length_before_body() -> None:
    stream = TrackingByteStream([b"must-not-be-read"])
    client = _client_for_stream(stream, headers={"Content-Length": "6"})

    with pytest.raises(ResponseTooLarge):
        with streaming_response(
            client,
            "GET",
            "https://provider.example/data",
            timeout=httpx.Timeout(1.0),
        ) as response:
            read_bounded_bytes(response, max_bytes=5)

    assert stream.yielded == 0
    assert stream.closed is True


def test_bounded_reader_rejects_unbounded_decimal_length_before_integer_parse() -> None:
    stream = TrackingByteStream([b"must-not-be-read"])
    client = _client_for_stream(stream, headers={"Content-Length": "9" * 5_000})

    with pytest.raises(ResponseTooLarge):
        with streaming_response(
            client,
            "GET",
            "https://provider.example/data",
            timeout=httpx.Timeout(1.0),
        ) as response:
            read_bounded_bytes(response, max_bytes=5)

    assert stream.yielded == 0
    assert stream.closed is True


def test_bounded_reader_enforces_cap_on_decompressed_bytes() -> None:
    stream = TrackingByteStream([gzip.compress(b"1234567890")])
    client = _client_for_stream(stream, headers={"Content-Encoding": "gzip"})

    with pytest.raises(ResponseTooLarge):
        with streaming_response(
            client,
            "GET",
            "https://provider.example/data",
            timeout=httpx.Timeout(1.0),
        ) as response:
            read_bounded_bytes(response, max_bytes=5)

    assert stream.yielded == 1
    assert stream.closed is True


def test_streaming_response_closes_when_body_read_times_out() -> None:
    stream = TrackingByteStream([b"123", b"unused"], error_after=1)
    client = _client_for_stream(stream)

    with pytest.raises(httpx.ReadTimeout, match="stream-timeout-canary"):
        with streaming_response(
            client,
            "GET",
            "https://provider.example/data",
            timeout=httpx.Timeout(1.0),
        ) as response:
            read_bounded_bytes(response, max_bytes=10)

    assert stream.yielded == 1
    assert stream.closed is True


@pytest.mark.parametrize("content_length", ["", "-1", "1.5", "1, 2"])
def test_bounded_reader_rejects_invalid_content_length(content_length: str) -> None:
    stream = TrackingByteStream([b"must-not-be-read"])
    client = _client_for_stream(stream, headers={"Content-Length": content_length})

    with pytest.raises(InvalidContentLength):
        with streaming_response(
            client,
            "GET",
            "https://provider.example/data",
            timeout=httpx.Timeout(1.0),
        ) as response:
            read_bounded_bytes(response, max_bytes=5)

    assert stream.yielded == 0
    assert stream.closed is True


def test_bounded_reader_returns_exact_valid_decoded_bytes() -> None:
    stream = TrackingByteStream([b'{"ok":', b"true}"])
    client = _client_for_stream(stream)

    with streaming_response(
        client,
        "GET",
        "https://provider.example/data",
        timeout=httpx.Timeout(1.0),
    ) as response:
        body = read_bounded_bytes(response, max_bytes=11)

    assert body == b'{"ok":true}'
    assert stream.yielded == 2
    assert stream.closed is True
