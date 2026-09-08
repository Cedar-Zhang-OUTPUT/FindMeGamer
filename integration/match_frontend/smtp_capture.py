"""Private synthetic SMTP transport; never resolve DNS or open a socket.

The real SMTPGateway is imported only by capture_gateway. Worker, repository,
qualification and unknown-outcome handling remain the application's real code.
"""

from email.message import EmailMessage
from email.utils import getaddresses
import json
import os
from pathlib import Path
import re
import smtplib
from uuid import uuid4

MODES = {"success", "fail_before", "reject", "unknown_after_capture"}


def _private_state(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o777 != 0o700:
        raise ValueError("A private synthetic SMTP state directory is required")
    return directory


def _mode(directory):
    path = directory / "smtp-control.json"
    if not path.exists() and not path.is_symlink():
        return "success"
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o777 != 0o600:
        raise ValueError("Synthetic SMTP control must be private")
    value = json.loads(path.read_text())
    if (
        not isinstance(value, dict)
        or set(value) != {"mode"}
        or not isinstance(value["mode"], str)
        or value["mode"] not in MODES
    ):
        raise ValueError("Unsupported synthetic SMTP control")
    return value["mode"]


def _event(directory, status):
    # Call sites supply fixed labels only; never log message content or identity.
    line = json.dumps({"endpoint": "smtp", "status": status}) + "\n"
    descriptor = os.open(
        directory / "smtp-events.jsonl", os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600
    )
    try:
        os.write(descriptor, line.encode())
    finally:
        os.close(descriptor)


class CaptureSMTPConnection:
    def __init__(self, state_directory):
        self.state = _private_state(state_directory)
        self.mode = _mode(self.state)
        self.authenticated = False
        self.closed = False
        if self.mode == "fail_before":
            _event(self.state, "fail_before")
            raise smtplib.SMTPConnectError(421, b"synthetic_failure_before_connection")

    def starttls(self, *, context):
        raise smtplib.SMTPNotSupportedError("Synthetic capture requires implicit TLS")

    def login(self, username, password):
        self.authenticated = False
        if self.closed:
            raise smtplib.SMTPServerDisconnected("Synthetic connection is closed")
        if (username, password) != ("sender@example.com", "synthetic-smtp-integration-key"):
            raise smtplib.SMTPAuthenticationError(535, b"synthetic_identity_rejected")
        self.authenticated = True

    def send_message(self, message: EmailMessage):
        if self.closed:
            raise smtplib.SMTPServerDisconnected("Synthetic connection is closed")
        if not self.authenticated:
            raise smtplib.SMTPAuthenticationError(535, b"synthetic_login_required")
        if not isinstance(message, EmailMessage):
            raise smtplib.SMTPDataError(550, b"synthetic_message_rejected")
        to_headers = message.get_all("To", [])
        recipients = getaddresses(to_headers)
        senders = getaddresses(message.get_all("From", []))
        if (
            len(to_headers) != 1
            or len(recipients) != 1
            or re.fullmatch(r"[^@\s<>;,]+@example\.com", recipients[0][1]) is None
            or len(senders) != 1
            or senders[0][1] != "sender@example.com"
            or any(name.lower() in {"sender", "cc", "bcc"} or name.lower().startswith("resent-") for name in message.keys())
        ):
            raise smtplib.SMTPDataError(550, b"synthetic_envelope_rejected")
        if self.mode == "reject":
            _event(self.state, "rejected")
            raise smtplib.SMTPRecipientsRefused({recipients[0][1]: (550, b"synthetic_rejection")})
        descriptor = os.open(
            self.state / f"smtp-{uuid4()}.eml", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(message.as_bytes())
        _event(self.state, "captured")
        if self.mode == "unknown_after_capture":
            _event(self.state, "unknown_after_capture")
            raise smtplib.SMTPServerDisconnected("Synthetic disconnect after capture")
        return {}

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


def capture_gateway(state_directory):
    from app.outreach.smtp import SMTPGateway

    directory = _private_state(state_directory)

    def resolve(host, port):
        if (host, port) != ("smtp.integration.invalid", 465):
            raise ValueError("Unexpected synthetic SMTP destination")
        # Satisfies the real gateway's public-address check, but is never dialed.
        return ("8.8.8.8",)

    def factory(host, address, port, encryption, context, timeout):
        if (host, address, port, encryption) != ("smtp.integration.invalid", "8.8.8.8", 465, "tls"):
            raise ValueError("Unexpected synthetic SMTP transport")
        return CaptureSMTPConnection(directory)

    return SMTPGateway(resolver=resolve, factory=factory)
