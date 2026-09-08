"""Safe SMTP connection boundary for probes and outbound messages."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage
from ipaddress import ip_address
import re
import smtplib
import socket
import ssl
from typing import Literal, Protocol


SMTPEncryption = Literal["tls", "starttls", "none"]
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class SMTPError(RuntimeError):
    """A safe SMTP failure that contains no upstream response text."""


class SMTPPermanentError(SMTPError):
    """SMTP rejected an operation that should not be retried unchanged."""


class SMTPTransientError(SMTPError):
    """SMTP failed in a way that may succeed on a later attempt."""


class SMTPUnknownOutcome(SMTPError):
    """Submission may have succeeded; never automatically send it again."""


@dataclass(frozen=True, slots=True)
class SMTPConfig:
    host: str
    port: int
    encryption: SMTPEncryption
    username: str
    password: str = field(repr=False)
    from_name: str
    reply_to: str


@dataclass(frozen=True, slots=True)
class SMTPReceipt:
    accepted_recipients: int


class SMTPConnection(Protocol):
    def starttls(self, *, context: ssl.SSLContext) -> object: ...

    def login(self, username: str, password: str) -> object: ...

    def send_message(self, message: EmailMessage) -> dict[str, object]: ...

    def quit(self) -> object: ...

    def close(self) -> object: ...


SMTPFactory = Callable[
    [str, str, int, SMTPEncryption, ssl.SSLContext, float], SMTPConnection
]
SMTPResolver = Callable[[str, int], Sequence[str]]


def _is_global_unicast(value: str) -> bool:
    address = ip_address(value)
    return address.is_global and not any(
        (
            address.is_loopback,
            address.is_private,
            address.is_link_local,
            address.is_multicast,
            address.is_unspecified,
            address.is_reserved,
        )
    )


def normalize_smtp_host(value: str) -> str:
    """Validate and normalize an SMTP hostname without resolving it."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("SMTP host is not allowed.")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("SMTP host is not allowed.")
    normalized = value.casefold().rstrip(".")
    if not normalized or normalized == "localhost" or normalized.endswith(".localhost"):
        raise ValueError("SMTP host is not allowed.")
    try:
        parsed_address = ip_address(normalized)
    except ValueError:
        if (
            len(normalized) > 253
            or any(
                marker in normalized
                for marker in (":", "/", "\\", "@", "?", "#", "[", "]")
            )
            or any(not _HOST_LABEL.fullmatch(label) for label in normalized.split("."))
        ):
            raise ValueError("SMTP host is not allowed.") from None
    else:
        if not _is_global_unicast(normalized):
            raise ValueError("SMTP host is not allowed.")
    return normalized


def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(result[4][0] for result in results))


class _HostnameSMTPSSL(smtplib.SMTP_SSL):
    def __init__(self, tls_hostname: str, *, context: ssl.SSLContext, timeout: float):
        self._tls_hostname = tls_hostname
        super().__init__(host="", context=context, timeout=timeout)

    def _get_socket(self, host: str, port: int, timeout: float):
        raw_socket = smtplib.SMTP._get_socket(self, host, port, timeout)
        return self.context.wrap_socket(raw_socket, server_hostname=self._tls_hostname)


def _production_factory(
    hostname: str,
    address: str,
    port: int,
    encryption: SMTPEncryption,
    context: ssl.SSLContext,
    timeout: float,
) -> SMTPConnection:
    if encryption == "tls":
        connection: smtplib.SMTP = _HostnameSMTPSSL(
            hostname, context=context, timeout=timeout
        )
    else:
        connection = smtplib.SMTP(timeout=timeout)
    connection.connect(address, port)
    connection._host = hostname
    return connection


class SMTPGateway:
    def __init__(
        self,
        *,
        factory: SMTPFactory = _production_factory,
        resolver: SMTPResolver = _resolve_addresses,
        timeout: float = 10.0,
    ) -> None:
        self._factory = factory
        self._resolver = resolver
        self._timeout = timeout

    def probe(self, config: SMTPConfig) -> None:
        self._run(config, None)

    def send(self, config: SMTPConfig, message: EmailMessage) -> SMTPReceipt:
        return self._run(config, message)

    def _run(self, config: SMTPConfig, message: EmailMessage | None) -> SMTPReceipt:
        connection: SMTPConnection | None = None
        submitting = False
        try:
            try:
                host = normalize_smtp_host(config.host)
            except ValueError:
                raise SMTPPermanentError("SMTP host is not allowed.") from None
            addresses = tuple(self._resolver(host, config.port))
            if not addresses or any(
                not _is_global_unicast(address) for address in addresses
            ):
                raise SMTPPermanentError("SMTP host is not allowed.")
            context = ssl.create_default_context()
            connection = self._factory(
                host,
                addresses[0],
                config.port,
                config.encryption,
                context,
                self._timeout,
            )
            if config.encryption == "starttls":
                connection.starttls(context=context)
            connection.login(config.username, config.password)
            if message is None:
                return SMTPReceipt(accepted_recipients=0)
            submitting = True
            refusals = connection.send_message(message)
            recipients = len(message.get_all("To", []))
            accepted = max(0, recipients - len(refusals))
            if recipients and accepted == 0:
                raise SMTPPermanentError("SMTP rejected the request.")
            return SMTPReceipt(accepted_recipients=accepted)
        except SMTPError:
            raise
        except Exception as error:
            if submitting and not isinstance(
                error, (smtplib.SMTPResponseException, smtplib.SMTPRecipientsRefused)
            ):
                raise SMTPUnknownOutcome(
                    "SMTP submission outcome is unknown. Verify before sending again."
                ) from None
            raise _classify_smtp_error(error) from None
        finally:
            if connection is not None:
                try:
                    connection.quit()
                except Exception:
                    pass
                try:
                    connection.close()
                except Exception:
                    pass


def _classify_smtp_error(error: Exception) -> SMTPError:
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return SMTPPermanentError("SMTP rejected the request.")
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return SMTPPermanentError("SMTP rejected the request.")
    if isinstance(error, smtplib.SMTPConnectError):
        return SMTPTransientError("SMTP is temporarily unavailable.")
    if isinstance(error, smtplib.SMTPResponseException):
        if 500 <= error.smtp_code <= 599:
            return SMTPPermanentError("SMTP rejected the request.")
        return SMTPTransientError("SMTP is temporarily unavailable.")
    if isinstance(error, (smtplib.SMTPNotSupportedError, smtplib.SMTPSenderRefused)):
        return SMTPPermanentError("SMTP rejected the request.")
    if isinstance(
        error,
        (TimeoutError, ConnectionError, OSError, smtplib.SMTPServerDisconnected),
    ):
        return SMTPTransientError("SMTP is temporarily unavailable.")
    return SMTPTransientError("SMTP is temporarily unavailable.")


__all__ = [
    "SMTPConfig",
    "SMTPError",
    "SMTPGateway",
    "SMTPPermanentError",
    "SMTPReceipt",
    "SMTPTransientError",
    "SMTPUnknownOutcome",
    "normalize_smtp_host",
]
