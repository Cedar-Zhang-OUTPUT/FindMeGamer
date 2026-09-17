"""Immutable previews and one SMTP attempt per preview; never promise exactly-once SMTP."""

from datetime import timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..errors import ApiError
from .enrichment import EMAIL
from .jobs import utcnow
from .models import EmailPreview, EmailSend
from .templates import get_template, render_template


def email_address(value):
    if (
        not isinstance(value, str)
        or not value.isascii()
        or len(value) > 254
        or not EMAIL.fullmatch(value)
    ):
        raise ValueError("Use one plain email address without display names.")
    return value


def smtp_ready(config):
    try:
        email_address(config.smtp_from)
    except ValueError:
        return False
    if not config.smtp_host:
        return False
    if config.smtp_encryption == "none":
        return config.smtp_allow_insecure_loopback and config.smtp_host in {
            "127.0.0.1",
            "::1",
        }
    return bool(config.smtp_username and config.smtp_password.get_secret_value())


def receipt(row):
    return {
        key: getattr(row, key)
        for key in ("id", "preview_id", "state", "code", "created_at", "updated_at")
    }


class SendStore:
    def __init__(self, sessions):
        self.sessions = sessions

    def preview(self, token_id, payload, config):
        definition = get_template(payload["template_id"], payload["template_version"])
        message = render_template(definition, payload["variables"])
        message.update(
            to=email_address(payload["to"]), **{"from": config.smtp_from or None}
        )
        with self.sessions() as session:
            row = EmailPreview(
                token_id=token_id,
                template_id=definition["id"],
                template_version=definition["version"],
                message=message,
            )
            session.add(row)
            session.commit()
            preview_id = row.id
        return self.get_preview(preview_id, token_id, config)

    def get_preview(self, preview_id, token_id, config):
        with self.sessions() as session:
            row = session.get(EmailPreview, preview_id)
            if row is None or row.token_id != token_id:
                raise ApiError(404, "preview_not_found", "Preview was not found.")
            return {
                "id": row.id,
                "template_id": row.template_id,
                "template_version": row.template_version,
                "message": row.message,
                "created_at": row.created_at,
                "send_ready": smtp_ready(config)
                and row.message["from"] == config.smtp_from,
            }

    def recover_interrupted(self):
        with self.sessions() as session:
            session.execute(
                update(EmailSend)
                .where(
                    EmailSend.state == "sending",
                    EmailSend.updated_at < utcnow() - timedelta(minutes=5),
                )
                .values(
                    state="unknown",
                    code="smtp_execution_interrupted",
                    updated_at=utcnow(),
                )
            )
            session.commit()

    def get_receipt(self, send_id, token_id):
        self.recover_interrupted()
        with self.sessions() as session:
            row = session.get(EmailSend, send_id)
            if row is None or row.token_id != token_id:
                raise ApiError(404, "send_not_found", "Send receipt was not found.")
            return receipt(row)

    def _existing(self, session, token_id, preview_id, key):
        row = session.scalar(
            select(EmailSend).where(
                EmailSend.token_id == token_id, EmailSend.idempotency_key == key
            )
        )
        if row is not None:
            if row.preview_id != preview_id:
                raise ApiError(
                    409,
                    "idempotency_conflict",
                    "This send key belongs to another preview.",
                )
            return receipt(row)
        row = session.scalar(
            select(EmailSend).where(EmailSend.preview_id == preview_id)
        )
        if row is not None:
            # Another request may commit between the two SELECTs under READ COMMITTED.
            if row.token_id == token_id and row.idempotency_key == key:
                return receipt(row)
            raise ApiError(
                409,
                "preview_already_sent",
                f"This preview already has a send attempt. Query receipt {row.id}.",
            )
        return None

    def send(self, token_id, preview_id, key, config, transport):
        preview = self.get_preview(preview_id, token_id, config)
        self.recover_interrupted()
        with self.sessions() as session:
            existing = self._existing(session, token_id, preview_id, key)
            if existing is not None:
                return existing
            if preview["message"].get("format") != "plain_text":
                raise ApiError(409, "preview_format_retired", "Create and approve a new plain-text draft; this older draft is no longer sendable.")
            if not smtp_ready(config):
                raise ApiError(
                    503, "configuration_missing", "SMTP is not configured for sending."
                )
            if preview["message"]["from"] != config.smtp_from:
                raise ApiError(
                    409,
                    "sender_changed",
                    "The sender changed; create and confirm a new preview.",
                )
            created = preview["created_at"]
            if created.replace(tzinfo=timezone.utc) < utcnow() - timedelta(days=30):
                raise ApiError(
                    409, "preview_expired", "Create and confirm a fresh preview."
                )
            row = EmailSend(
                token_id=token_id,
                preview_id=preview_id,
                idempotency_key=key,
                state="sending",
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = self._existing(session, token_id, preview_id, key)
                if existing is None:
                    raise
                return existing
            send_id = row.id
        # Durable reservation precedes the external side effect. No auto retry.
        try:
            outcome = transport(config, preview["message"], send_id)
            if outcome.get("state") not in {"sent", "failed", "unknown"}:
                raise ValueError()
        except Exception:
            outcome = {"state": "unknown", "code": "smtp_execution_uncertain"}
        with self.sessions() as session:
            session.execute(
                update(EmailSend)
                .where(EmailSend.id == send_id, EmailSend.state == "sending")
                .values(
                    state=outcome["state"],
                    code=outcome.get("code"),
                    updated_at=utcnow(),
                )
            )
            session.commit()
        return self.get_receipt(send_id, token_id)
