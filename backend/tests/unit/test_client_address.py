import pytest

from app.core.client_address import ClientAddressResolver


def test_untrusted_peer_cannot_spoof_forwarded_client_address() -> None:
    resolver = ClientAddressResolver(["172.16.0.0/12"])

    assert (
        resolver.resolve("203.0.113.9", "198.51.100.44, 192.0.2.10")
        == "203.0.113.9"
    )


def test_trusted_proxy_chain_resolves_nearest_untrusted_origin() -> None:
    resolver = ClientAddressResolver(["172.16.0.0/12", "10.0.0.0/8"])

    assert (
        resolver.resolve("172.18.0.2", "192.0.2.10, 198.51.100.44, 10.1.2.3")
        == "198.51.100.44"
    )


@pytest.mark.parametrize(
    ("peer", "forwarded_for", "expected"),
    [
        ("172.18.0.2", "not-an-ip", "172.18.0.2"),
        ("not-an-ip", "198.51.100.44", "unknown"),
        ("2001:0db8:0:0::1", None, "2001:db8::1"),
    ],
)
def test_client_address_falls_back_safely_on_unusable_input(
    peer: str | None, forwarded_for: str | None, expected: str
) -> None:
    resolver = ClientAddressResolver(["172.16.0.0/12"])

    assert resolver.resolve(peer, forwarded_for) == expected
