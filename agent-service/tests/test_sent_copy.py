"""SMTP acceptance and Sent storage are independent, idempotent side effects."""

from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy import select

from test_email_sending import sending, preview, send
from test_smtp_delivery import smtp_server


@pytest.fixture
def archive_env(sending, smtp_server, monkeypatch):
    import imaplib
    from fmg_agent.email.models import EmailSend
    from fmg_agent.mailboxes import MailboxRegistry

    app, client, owner, _, _ = sending
    config = app.state.settings
    config.smtp_host = "127.0.0.1"
    config.smtp_port = smtp_server.server_address[1]
    config.smtp_encryption = "none"
    config.smtp_allow_insecure_loopback = True
    # model_copy lets these tests fail on missing behavior, not on new field access.
    app.state.settings = config.model_copy(
        update={
            "smtp_save_sent_copy": True,
            "imap_sent_folder": "Sent",
            "imap_host": "imap.example.com",
            "imap_username": "publisher@example.com",
            "imap_password": config.smtp_password,
        }
    )
    app.state.mailboxes = MailboxRegistry.load(app.state.settings)
    from fmg_agent.email.smtp import deliver

    app.state.smtp_transport = deliver

    class Mailbox:
        messages = []
        mode = "ok"
        reads = 0

        def __init__(self, host, port, *, ssl_context, timeout):
            assert host == "imap.example.com"
            assert ssl_context.verify_mode
            assert timeout <= 20

        def login(self, user, password):
            assert user == "publisher@example.com"
            return "OK", []

        def select(self, folder, readonly=False):
            assert folder == '"Sent"'
            assert readonly is True
            return "OK", [b"0"]

        def uid(self, command, charset, *criteria):
            assert command == "search"
            assert criteria[:2] == ("HEADER", "Message-ID")
            # Critical: SMTP state is already durable before touching IMAP.
            with app.state.sessions() as session:
                rows = session.scalars(select(EmailSend)).all()
                assert rows and all(r.state == "sent" for r in rows)
            self.__class__.reads += 1
            if self.mode == "search_error":
                return "NO", [b"private provider error"]
            mid = criteria[2].strip('"')
            matches = [
                str(i + 1).encode()
                for i, raw in enumerate(self.messages)
                if str(BytesParser(policy=policy.default).parsebytes(raw)["Message-ID"])
                == mid
            ]
            return "OK", [b" ".join(matches)]

        def append(self, folder, flags, date_time, raw):
            assert folder == '"Sent"'
            assert flags == r"(\Seen)"
            if self.mode == "reject":
                return "NO", [b"private provider error secret-password"]
            self.messages.append(raw)
            if self.mode == "lost_ack":
                raise TimeoutError("secret-password")
            return "OK", [b"[APPENDUID 1 1] appended"]

        def logout(self):
            return "BYE", []

    monkeypatch.setattr(imaplib, "IMAP4_SSL", Mailbox)
    return app, client, owner, smtp_server, Mailbox


def test_accepted_message_is_saved_with_same_mime_and_no_duplicate_send(archive_env):
    app, client, owner, smtp, box = archive_env
    pid = preview(client, owner).json()["data"]["id"]
    data = send(client, owner, pid).json()["data"]
    assert data["state"] == "sent"
    assert data["diagnostics"]["sent_copy"]["state"] == "saved"
    assert len(box.messages) == 1
    assert box.messages[0] == smtp.messages[0]
    mail = BytesParser(policy=policy.default).parsebytes(box.messages[0])
    assert mail["Message-ID"] == f'<fmg-{data["id"]}@example.com>'
    assert mail.get_body(preferencelist=("html",)) is not None
    assert any(p.get_content_type() == "image/png" for p in mail.walk())
    assert send(client, owner, pid).json()["data"]["id"] == data["id"]
    assert len(smtp.messages) == len(box.messages) == 1


@pytest.mark.parametrize(
    "mode,archive_state",
    [
        ("reject", "failed"),
        ("search_error", "failed"),
        ("lost_ack", "unknown"),
    ],
)
def test_archive_errors_never_change_acceptance_or_resend(
    archive_env, mode, archive_state
):
    app, client, owner, smtp, box = archive_env
    box.mode = mode
    pid = preview(client, owner).json()["data"]["id"]
    response = send(client, owner, pid)
    data = response.json()["data"]
    assert data["state"] == "sent" and data["code"] is None
    assert data["diagnostics"]["sent_copy"]["state"] == archive_state
    assert "secret-password" not in response.text
    send(client, owner, pid)
    assert len(smtp.messages) == 1


def test_manual_archive_repair_reconciles_lost_ack_without_appending_or_sending(
    archive_env,
):
    app, client, owner, smtp, box = archive_env
    box.mode = "lost_ack"
    pid = preview(client, owner).json()["data"]["id"]
    data = send(client, owner, pid).json()["data"]
    from fmg_agent.email.sent_copy import archive_sent_copy

    box.mode = "ok"
    outcome = archive_sent_copy(app.state.sessions, data["id"], app.state.settings)
    assert outcome["state"] == "already_exists"
    assert len(smtp.messages) == len(box.messages) == 1


def test_rejected_archive_repair_preserves_original_smtp_bytes(archive_env):
    app, client, owner, smtp, box = archive_env
    box.mode = "reject"
    pid = preview(client, owner).json()["data"]["id"]
    data = send(client, owner, pid).json()["data"]
    from fmg_agent.email.sent_copy import archive_sent_copy

    box.mode = "ok"
    assert (
        archive_sent_copy(app.state.sessions, data["id"], app.state.settings)["state"]
        == "saved"
    )
    assert box.messages == smtp.messages


@pytest.mark.parametrize("smtp_mode", ["reject", "unknown"])
def test_not_accepted_mail_is_not_archived(archive_env, smtp_mode):
    app, client, owner, smtp, box = archive_env
    smtp.mode = smtp_mode
    pid = preview(client, owner).json()["data"]["id"]
    data = send(client, owner, pid).json()["data"]
    assert data["state"] != "sent"
    assert box.messages == [] and box.reads == 0


def test_mailbox_settings_do_not_inherit_another_mailbox_archive_configuration(
    tmp_path,
):
    from fmg_agent.config import Settings
    from fmg_agent.mailboxes import MailboxProfile, MailboxRegistry

    config = Settings(database_url=f"sqlite:///{tmp_path / 'x.db'}").model_copy(
        update={"smtp_save_sent_copy": True, "imap_sent_folder": "Other Sent"}
    )
    registry = MailboxRegistry(
        config,
        [
            MailboxProfile(id="second", smtp_from="second@example.com"),
        ],
        legacy=False,
    )
    selected = registry.settings_for("second")
    assert selected.smtp_save_sent_copy is False
    assert selected.imap_sent_folder == "Sent"


def test_manual_repair_refuses_another_sender_or_unaccepted_send(archive_env):
    from fmg_agent.email.sent_copy import archive_sent_copy

    app, client, owner, smtp, box = archive_env
    box.mode = "reject"
    pid = preview(client, owner).json()["data"]["id"]
    data = send(client, owner, pid).json()["data"]
    other = app.state.settings.model_copy(update={"smtp_from": "other@example.com"})
    assert (
        archive_sent_copy(app.state.sessions, data["id"], other)["code"]
        == "sent_copy_sender_mismatch"
    )
    from fmg_agent.email.models import EmailSend

    with app.state.sessions() as session:
        session.get(EmailSend, data["id"]).state = "unknown"
        session.commit()
    box.mode = "ok"
    assert (
        archive_sent_copy(app.state.sessions, data["id"], app.state.settings)["code"]
        == "sent_copy_not_accepted"
    )
    assert len(smtp.messages) == 1 and box.messages == []


def test_graph_receipt_does_not_invoke_smtp_archive_even_if_flag_set(archive_env):
    from fmg_agent.email.sent_copy import archive_sent_copy

    app, client, owner, smtp, box = archive_env
    config = app.state.settings.model_copy(
        update={"email_transport": "microsoft_graph"}
    )
    assert (
        archive_sent_copy(app.state.sessions, "not-needed", config)["state"]
        == "disabled"
    )
    assert box.messages == [] and box.reads == 0


def test_disabled_archive_keeps_existing_smtp_behavior(archive_env):
    from fmg_agent.mailboxes import MailboxRegistry

    app, client, owner, smtp, box = archive_env
    app.state.settings.smtp_save_sent_copy = False
    app.state.mailboxes = MailboxRegistry.load(app.state.settings)
    pid = preview(client, owner).json()["data"]["id"]
    data = send(client, owner, pid).json()["data"]
    assert data["state"] == "sent" and data["diagnostics"] is None
    assert len(smtp.messages) == 1
    assert box.messages == [] and box.reads == 0
