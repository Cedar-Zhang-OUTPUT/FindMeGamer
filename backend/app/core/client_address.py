from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from ipaddress import ip_address, ip_network


IPAddress = IPv4Address | IPv6Address
IPNetwork = IPv4Network | IPv6Network


class ClientAddressResolver:
    def __init__(self, trusted_proxy_cidrs: list[str] | tuple[str, ...]) -> None:
        self._trusted_proxy_networks: tuple[IPNetwork, ...] = tuple(
            ip_network(cidr, strict=False) for cidr in trusted_proxy_cidrs
        )

    def resolve(self, peer: str | None, forwarded_for: str | None) -> str:
        peer_address = self._parse_address(peer)
        if peer_address is None:
            return "unknown"
        if not forwarded_for or not self._is_trusted(peer_address):
            return str(peer_address)

        forwarded_addresses: list[IPAddress] = []
        for value in forwarded_for.split(","):
            address = self._parse_address(value.strip())
            if address is None:
                return str(peer_address)
            forwarded_addresses.append(address)
        if not forwarded_addresses:
            return str(peer_address)

        candidate = peer_address
        for address in reversed(forwarded_addresses):
            if not self._is_trusted(candidate):
                break
            candidate = address
        return str(candidate)

    def _is_trusted(self, address: IPAddress) -> bool:
        return any(
            network.version == address.version and address in network
            for network in self._trusted_proxy_networks
        )

    @staticmethod
    def _parse_address(value: str | None) -> IPAddress | None:
        if value is None:
            return None
        try:
            return ip_address(value)
        except ValueError:
            return None
