import socket
from typing import NoReturn

import pytest


@pytest.fixture(autouse=True)
def prohibit_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_network(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("gateway unit tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_network)
    monkeypatch.setattr(socket, "create_connection", blocked_network)
