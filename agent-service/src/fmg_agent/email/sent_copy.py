"""Save accepted SMTP mail, never send it. No automatic retries after APPEND."""

from datetime import timezone
from email import policy
from email.parser import BytesParser
from email.utils import format_datetime
import imaplib
import ssl

from sqlalchemy import select

from .models import EmailPreview, EmailSend
from .mime import build_message
from .jobs import utcnow


def enabled(config):
    return config.email_transport == "smtp" and config.smtp_save_sent_copy


def _quote(value):
    if (
        not value
        or not value.isascii()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Invalid IMAP argument")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _append(config, raw):
    client = None
    attempted = False
    try:
        if (
            not config.imap_host
            or config.imap_username.casefold() != config.smtp_from.casefold()
            or config.imap_auth != "password"
            or not config.imap_password.get_secret_value()
        ):
            return {"state": "failed", "code": "sent_copy_configuration_invalid"}
        mid = str(BytesParser(policy=policy.default).parsebytes(raw)["Message-ID"])
        folder = _quote(config.imap_sent_folder)
        client = imaplib.IMAP4_SSL(
            config.imap_host,
            config.imap_port,
            ssl_context=ssl.create_default_context(),
            timeout=10,
        )
        client.login(config.imap_username, config.imap_password.get_secret_value())
        # EXAMINE avoids flag/expunge changes; APPEND is the sole mailbox write.
        if client.select(folder, readonly=True)[0] != "OK":
            return {"state": "failed", "code": "sent_copy_folder_unavailable"}
        status, ids = client.uid("search", None, "HEADER", "Message-ID", _quote(mid))
        if status != "OK" or not ids or not isinstance(ids[0], bytes):
            return {"state": "failed", "code": "sent_copy_search_failed"}
        if ids[0].strip():
            return {"state": "already_exists", "code": None}
        attempted = True
        status, _ = client.append(folder, r"(\Seen)", None, raw)
        if status != "OK":
            return {"state": "failed", "code": "sent_copy_append_rejected"}
        return {"state": "saved", "code": None}
    except Exception:
        # Do not publish provider errors, credentials, or original mail content.
        return {
            "state": "unknown" if attempted else "failed",
            "code": (
                "sent_copy_confirmation_lost" if attempted else "sent_copy_unavailable"
            ),
        }
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def archive_sent_copy(sessions, send_id, config, *, raw=None):
    """Internal/admin operation. Caller selects the original mailbox's settings.

    Only accepted sends qualify. PostgreSQL's row lock serializes repairs;
    an uncertain APPEND is reconciled by Message-ID before any new APPEND.
    No SMTP is invoked, including on repair or failure.
    """
    if not enabled(config):
        return {"state": "disabled", "code": None}
    with sessions() as session:
        row = session.scalar(
            select(EmailSend).where(EmailSend.id == send_id).with_for_update()
        )
        if row is None or row.state != "sent":
            return {"state": "skipped", "code": "sent_copy_not_accepted"}
        preview = session.get(EmailPreview, row.preview_id)
        if preview is None or preview.message.get("from") != config.smtp_from:
            return {"state": "failed", "code": "sent_copy_sender_mismatch"}
        previous = (row.diagnostics or {}).get("sent_copy", {})
        if previous.get("state") in {"saved", "already_exists"}:
            return previous
        if raw is None:
            # Explicit admin repair uses the frozen preview, not today's template.
            mail = build_message(
                dict(
                    preview.message,
                    _smtp_date=format_datetime(
                        row.created_at.replace(tzinfo=timezone.utc)
                    ),
                ),
                row.id,
            )
            raw = mail.as_bytes(policy=policy.SMTP)
        result = _append(config, raw)
        row.diagnostics = {**(row.diagnostics or {}), "sent_copy": result}
        row.updated_at = utcnow()
        session.commit()
        return result
