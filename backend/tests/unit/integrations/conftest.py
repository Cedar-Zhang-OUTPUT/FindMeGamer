import socket
from typing import NoReturn

import httpx
import pytest


class GatewayByteStream(httpx.SyncByteStream):
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
                raise httpx.ReadTimeout("gateway-stream-timeout-canary")
            self.yielded += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def prohibit_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_network(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("gateway unit tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_network)
    monkeypatch.setattr(socket, "create_connection", blocked_network)


@pytest.fixture
def gateway_byte_stream_factory():
    return GatewayByteStream
