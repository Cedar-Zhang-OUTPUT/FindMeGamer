"""Syntactic admission only. Network fetchers must also pin validated DNS IPs."""

from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit


def public_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme not in {"https", "http"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
            or "\\" in value
            or any(ord(c) < 33 for c in value)
        ):
            raise ValueError()
        if host.lower().rstrip(".") in {
            "localhost",
            "metadata.google.internal",
        } or host.lower().endswith(".localhost"):
            raise ValueError()
        try:
            address = ip_address(host)
        except ValueError:
            host.encode("idna")
        else:
            if not address.is_global:
                raise ValueError()
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, "")
        )
    except (ValueError, UnicodeError):
        raise ValueError(
            "Use a public HTTP(S) profile URL without credentials."
        ) from None
