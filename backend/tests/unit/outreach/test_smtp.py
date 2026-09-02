from email.message import EmailMessage
import smtplib
import ssl

import pytest

from app.outreach.smtp import (
    SMTPConfig,
    SMTPGateway,
    SMTPPermanentError,
    SMTPTransientError,
)


def smtp_config(**changes: object) -> SMTPConfig:
    values = {
        "host": "smtp.example.com",
        "port": 465,
        "encryption": "tls",
        "username": "sender@example.com",
        "password": "smtp-secret",
        "from_name": "Find Me Gamer",
        "reply_to": "reply@example.com",
    }
    values.update(changes)
    return SMTPConfig(**values)


class FakeSMTP:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.factory_calls: list[tuple[str, str, int, ssl.SSLContext]] = []
        self.failure: Exception | None = None
        self.refused: dict[str, tuple[int, bytes]] = {}

    def factory(
        self,
        hostname: str,
        address: str,
        port: int,
        encryption: str,
        context: ssl.SSLContext,
        timeout: float,
    ) -> "FakeSMTP":
        del encryption, timeout
        self.factory_calls.append((hostname, address, port, context))
        self.events.append("connect")
        return self

    def starttls(self, *, context: ssl.SSLContext) -> None:
        assert context is self.factory_calls[-1][3]
        self.events.append("starttls")

    def login(self, username: str, password: str) -> None:
        assert username == "sender@example.com"
        assert password
        self.events.append("login")
        if self.failure is not None:
            raise self.failure

    def send_message(self, message: EmailMessage) -> dict[str, tuple[int, bytes]]:
        assert message["To"] == "company@example.com"
        self.events.append("send")
        if self.failure is not None:
            raise self.failure
        return self.refused

    def quit(self) -> None:
        self.events.append("quit")

    def close(self) -> None:
        self.events.append("close")


def gateway(fake: FakeSMTP) -> SMTPGateway:
    return SMTPGateway(
        factory=fake.factory,
        resolver=lambda host, port: ("8.8.8.8",),
    )


def message() -> EmailMessage:
    value = EmailMessage()
    value["From"] = "sender@example.com"
    value["To"] = "company@example.com"
    value["Subject"] = "SMTP test"
    value.set_content("Diagnostic message")
    return value


def test_starttls_is_established_before_login() -> None:
    fake = FakeSMTP()

    gateway(fake).probe(smtp_config(encryption="starttls", port=587))

    assert fake.events[:3] == ["connect", "starttls", "login"]


@pytest.mark.parametrize(
    ("encryption", "expected"),
    [
        ("tls", ["connect", "login", "quit", "close"]),
        ("none", ["connect", "login", "quit", "close"]),
    ],
)
def test_tls_and_plain_modes_authenticate_without_starttls(
    encryption: str, expected: list[str]
) -> None:
    fake = FakeSMTP()

    gateway(fake).probe(smtp_config(encryption=encryption))

    assert fake.events == expected


@pytest.mark.parametrize("encryption", ["tls", "starttls"])
def test_encrypted_modes_use_verified_tls_and_vetted_address(encryption: str) -> None:
    fake = FakeSMTP()

    gateway(fake).probe(smtp_config(encryption=encryption))

    hostname, address, port, context = fake.factory_calls[0]
    assert (hostname, address, port) == ("smtp.example.com", "8.8.8.8", 465)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "https://smtp.example.com",
        "user@smtp.example.com",
        "smtp.example.com/path",
        "smtp.example.com\nattacker",
        "smtp example.com",
    ],
)
def test_smtp_host_rejects_non_host_syntax_without_resolving(host: str) -> None:
    fake = FakeSMTP()
    resolver_called = False

    def resolver(_host: str, _port: int) -> tuple[str, ...]:
        nonlocal resolver_called
        resolver_called = True
        return ("8.8.8.8",)

    smtp = SMTPGateway(factory=fake.factory, resolver=resolver)

    with pytest.raises(SMTPPermanentError, match="SMTP host is not allowed"):
        smtp.probe(smtp_config(host=host))

    assert resolver_called is False
    assert fake.factory_calls == []


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.1",),
        ("169.254.1.1",),
        ("224.0.0.1",),
        ("0.0.0.0",),
        ("192.0.2.1",),
        ("8.8.8.8", "10.0.0.1"),
    ],
)
def test_smtp_rejects_any_non_global_resolved_address(
    addresses: tuple[str, ...],
) -> None:
    fake = FakeSMTP()
    smtp = SMTPGateway(factory=fake.factory, resolver=lambda host, port: addresses)

    with pytest.raises(SMTPPermanentError, match="SMTP host is not allowed"):
        smtp.probe(smtp_config())

    assert fake.factory_calls == []


def test_smtp_config_repr_never_contains_password() -> None:
    config = smtp_config(password="never-show-this")

    assert "never-show-this" not in repr(config)
    assert "password" not in repr(config)


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (
            smtplib.SMTPAuthenticationError(535, b"credential leaked"),
            SMTPPermanentError,
        ),
        (smtplib.SMTPDataError(550, b"mailbox rejected"), SMTPPermanentError),
        (smtplib.SMTPDataError(451, b"try later"), SMTPTransientError),
        (smtplib.SMTPConnectError(554, b"connection rejected"), SMTPTransientError),
        (smtplib.SMTPServerDisconnected("connection lost"), SMTPTransientError),
        (TimeoutError("host timed out"), SMTPTransientError),
        (ConnectionError("connection refused"), SMTPTransientError),
    ],
)
def test_probe_classifies_errors_safely_and_always_closes(
    failure: Exception, error_type: type[Exception]
) -> None:
    fake = FakeSMTP()
    fake.failure = failure

    with pytest.raises(error_type) as caught:
        gateway(fake).probe(smtp_config(password="never-echo"))

    assert str(caught.value) in {
        "SMTP rejected the request.",
        "SMTP is temporarily unavailable.",
    }
    assert "never-echo" not in str(caught.value)
    assert fake.events[-1] == "close"


def test_complete_recipient_refusal_is_permanent_and_connection_closes() -> None:
    fake = FakeSMTP()
    fake.refused = {"company@example.com": (550, b"recipient detail")}

    with pytest.raises(SMTPPermanentError, match="SMTP rejected the request"):
        gateway(fake).send(smtp_config(), message())

    assert fake.events[-1] == "close"


def test_send_authenticates_then_sends_exactly_once_and_returns_receipt() -> None:
    fake = FakeSMTP()

    receipt = gateway(fake).send(smtp_config(), message())

    assert fake.events == ["connect", "login", "send", "quit", "close"]
    assert receipt.accepted_recipients == 1
