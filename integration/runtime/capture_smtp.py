"""Capture the SMTP transport in the isolated harness; never open a socket."""

from email.message import EmailMessage
from email.utils import getaddresses
import os
from pathlib import Path
from uuid import uuid4

from app.outreach.smtp import SMTPGateway


class CaptureSMTPConnection:
    def starttls(self, *, context) -> None:
        pass

    def login(self, username: str, password: str) -> None:
        if (username, password) != (
            "sender@example.com",
            "synthetic-smtp-integration-key",
        ):
            raise AssertionError("Unexpected integration SMTP identity")

    def send_message(self, message: EmailMessage) -> dict[str, object]:
        recipients = getaddresses(message.get_all("To", []))
        if not recipients or any(
            not email.endswith("@example.com") for _, email in recipients
        ):
            raise AssertionError("Unexpected integration SMTP recipient")
        state = Path(os.environ["FAKE_STATE_DIR"])
        (state / f"smtp-{uuid4()}.eml").write_bytes(message.as_bytes())
        with (state / "calls.log").open("a", encoding="utf-8") as stream:
            stream.write("smtp send_message\n")
        return {}

    def quit(self) -> None:
        pass

    def close(self) -> None:
        pass


def capture_gateway() -> SMTPGateway:
    def resolve(host: str, port: int) -> tuple[str, ...]:
        if (host, port) != ("smtp.integration.invalid", 465):
            raise AssertionError("Unexpected integration SMTP destination")
        # A syntactically public address exercises SMTPGateway's SSRF checks;
        # the capture factory below never connects to it or performs DNS.
        return ("8.8.8.8",)

    return SMTPGateway(
        resolver=resolve,
        factory=lambda *_args: CaptureSMTPConnection(),
    )
