"""Socket-free capture transport contracts, not a worker/send-flow acceptance."""

import builtins
from contextlib import contextmanager
from dataclasses import replace
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import importlib.util
import json
from pathlib import Path
import smtplib
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class SMTPCaptureContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / "smtp_capture.py").exists(), "Socket-free SMTP capture transport is missing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        for target in ("socket.getaddrinfo", "socket.create_connection", "socket.socket"):
            guard = patch(target, side_effect=AssertionError("Network fallback is forbidden"))
            forbidden_call = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(forbidden_call.assert_not_called)
        spec = importlib.util.spec_from_file_location("smtp_capture_contract", HERE / "smtp_capture.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def message(self, recipient="creator@example.com"):
        message = EmailMessage()
        message["From"] = "Synthetic Sender <sender@example.com>"
        message["To"] = recipient
        message["Subject"] = "Synthetic capture only"
        message.set_content("Synthetic plain body; no external delivery.")
        return message

    def set_mode(self, mode):
        path = self.state / "smtp-control.json"
        path.write_text(json.dumps({"mode": mode}))
        path.chmod(0o600)

    def emls(self):
        return sorted(self.state.glob("smtp-*.eml"))

    def events(self):
        path = self.state / "smtp-events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def connection(self):
        connection = self.module.CaptureSMTPConnection(self.state)
        connection.login("sender@example.com", "synthetic-smtp-integration-key")
        return connection

    @contextmanager
    def real_gateway(self):
        # Load the actual stdlib SMTP boundary only; no app worker/repository imports.
        name = "app.outreach.smtp"
        spec = importlib.util.spec_from_file_location(name, ROOT / "backend/app/outreach/smtp.py")
        smtp = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {name: smtp}):
            spec.loader.exec_module(smtp)
            gateway = self.module.capture_gateway(self.state)
            self.assertIsInstance(gateway, smtp.SMTPGateway)
            config = smtp.SMTPConfig(
                host="smtp.integration.invalid",
                port=465,
                encryption="tls",
                username="sender@example.com",
                password="synthetic-smtp-integration-key",
                from_name="Synthetic Sender",
                reply_to="sender@example.com",
            )
            yield gateway, config, smtp

    def test_transport_import_is_stdlib_only_until_gateway_is_requested(self):
        original = builtins.__import__

        def no_backend(name, *args, **kwargs):
            if name == "app" or name.startswith("app."):
                raise AssertionError("Backend was eagerly imported")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=no_backend):
            spec = importlib.util.spec_from_file_location("standalone_smtp_capture", HERE / "smtp_capture.py")
            standalone = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(standalone)
            connection = standalone.CaptureSMTPConnection(self.state)
            connection.login("sender@example.com", "synthetic-smtp-integration-key")
            self.assertEqual(connection.send_message(self.message()), {})
        self.assertEqual(len(self.emls()), 1)

    def test_success_captures_one_private_eml_and_only_a_fixed_event(self):
        self.set_mode("success")
        connection = self.connection()
        self.assertEqual(connection.send_message(self.message()), {})
        connection.quit()
        connection.close()
        paths = self.emls()
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)
        captured = BytesParser(policy=policy.default).parsebytes(paths[0].read_bytes())
        self.assertEqual(str(captured["To"]), "creator@example.com")
        self.assertEqual(str(captured["From"]), "Synthetic Sender <sender@example.com>")
        self.assertEqual(captured.get_content(), "Synthetic plain body; no external delivery.\n")
        self.assertEqual(self.events(), [{"endpoint": "smtp", "status": "captured"}])
        self.assertEqual((self.state / "smtp-events.jsonl").stat().st_mode & 0o777, 0o600)

    def test_login_and_probe_never_capture_a_message(self):
        connection = self.connection()
        connection.quit()
        connection.close()
        with self.real_gateway() as (gateway, config, _):
            gateway.probe(config)
        self.assertEqual(self.emls(), [])
        self.assertEqual(self.events(), [])

    def test_unknown_outcome_captures_once_before_send_message_disconnects(self):
        self.set_mode("unknown_after_capture")
        connection = self.connection()
        with self.assertRaises(smtplib.SMTPServerDisconnected):
            connection.send_message(self.message())
        self.assertEqual(len(self.emls()), 1)
        self.assertEqual(self.emls()[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            self.events(),
            [{"endpoint": "smtp", "status": "captured"}, {"endpoint": "smtp", "status": "unknown_after_capture"}],
        )

    def test_reject_raises_explicit_smtp_refusal_without_capture(self):
        self.set_mode("reject")
        with self.assertRaises(smtplib.SMTPRecipientsRefused):
            self.connection().send_message(self.message())
        self.assertEqual(self.emls(), [])
        self.assertEqual(self.events(), [{"endpoint": "smtp", "status": "rejected"}])

    def test_fail_before_prevents_connection_and_creates_no_eml(self):
        self.set_mode("fail_before")
        with self.assertRaises(smtplib.SMTPConnectError):
            self.module.CaptureSMTPConnection(self.state)
        self.assertEqual(self.emls(), [])
        self.assertEqual(self.events(), [{"endpoint": "smtp", "status": "fail_before"}])

    def test_exact_synthetic_credentials_and_login_are_required(self):
        connection = self.module.CaptureSMTPConnection(self.state)
        with self.assertRaises(smtplib.SMTPAuthenticationError):
            connection.send_message(self.message())
        for username, password in (
            ("other@example.com", "synthetic-smtp-integration-key"),
            ("sender@example.com", "PRIVATE-KEY-MARKER"),
        ):
            with self.subTest(username=username):
                with self.assertRaises(smtplib.SMTPAuthenticationError):
                    connection.login(username, password)
        self.assertEqual(self.emls(), [])
        self.assertEqual(self.events(), [])

    def test_only_one_example_com_recipient_and_fixed_sender_are_accepted(self):
        connection = self.connection()
        messages = [self.message(value) for value in (
            "creator@real.invalid",
            "first@example.com, second@example.com",
            "someone@notexample.com",
            "someone@example.com.evil.invalid",
            "",
        )]
        for field, value in (
            ("Cc", "second@example.com"),
            ("Bcc", "hidden@example.com"),
            ("Resent-To", "other@example.com"),
            ("Resent-Bcc", "hidden@example.com"),
        ):
            message = self.message()
            message[field] = value
            messages.append(message)
        message = self.message()
        message.replace_header("From", "other@example.com")
        messages.append(message)
        for message in messages:
            with self.subTest(headers=list(message.items())):
                with self.assertRaises(smtplib.SMTPResponseException):
                    connection.send_message(message)
        self.assertEqual(self.emls(), [])
        self.assertEqual(self.events(), [])

    def test_sender_header_cannot_override_the_fixed_synthetic_sender(self):
        message = self.message()
        message["Sender"] = "other@example.com"
        with self.assertRaises(smtplib.SMTPResponseException):
            self.connection().send_message(message)
        self.assertEqual(self.emls(), [])
        self.assertEqual(self.events(), [])

    def test_control_is_only_read_from_private_state_and_fails_closed(self):
        self.state.chmod(0o755)
        with self.assertRaises(ValueError):
            self.module.CaptureSMTPConnection(self.state)
        self.state.chmod(0o700)
        for content in (
            {"mode": "unknown"},
            {"mode": "success", "destination": "external"},
            {},
            [],
        ):
            with self.subTest(content=content):
                path = self.state / "smtp-control.json"
                path.write_text(json.dumps(content))
                path.chmod(0o600)
                with self.assertRaises(ValueError):
                    self.module.CaptureSMTPConnection(self.state)
        self.set_mode("success")
        (self.state / "smtp-control.json").chmod(0o644)
        with self.assertRaises(ValueError):
            self.module.CaptureSMTPConnection(self.state)
        self.assertEqual(self.emls(), [])

    def test_real_gateway_keeps_success_and_unknown_classification_without_retry(self):
        with self.real_gateway() as (gateway, config, smtp):
            receipt = gateway.send(config, self.message())
            self.assertEqual(receipt.accepted_recipients, 1)
            self.assertEqual(len(self.emls()), 1)
            self.set_mode("unknown_after_capture")
            with self.assertRaises(smtp.SMTPUnknownOutcome):
                gateway.send(config, self.message())
            self.assertEqual(len(self.emls()), 2)
        self.assertEqual(
            self.events(),
            [{"endpoint": "smtp", "status": "captured"}, {"endpoint": "smtp", "status": "captured"}, {"endpoint": "smtp", "status": "unknown_after_capture"}],
        )

    def test_real_gateway_preserves_known_failures_without_capture(self):
        with self.real_gateway() as (gateway, config, smtp):
            for mode, expected in (("fail_before", smtp.SMTPTransientError), ("reject", smtp.SMTPPermanentError)):
                with self.subTest(mode=mode):
                    self.set_mode(mode)
                    with self.assertRaises(expected):
                        gateway.send(config, self.message())
        self.assertEqual(self.emls(), [])

    def test_real_gateway_refuses_any_other_target_encryption_or_identity(self):
        with self.real_gateway() as (gateway, config, smtp):
            for changes in (
                {"host": "other.invalid"},
                {"port": 587},
                {"encryption": "starttls"},
                {"encryption": "none"},
                {"username": "other@example.com"},
                {"password": "PRIVATE-KEY-MARKER"},
            ):
                with self.subTest(changes=tuple(changes)):
                    with self.assertRaises(smtp.SMTPError):
                        gateway.probe(replace(config, **changes))
        self.assertEqual(self.emls(), [])
        self.assertEqual(self.events(), [])


if __name__ == "__main__":
    unittest.main()
