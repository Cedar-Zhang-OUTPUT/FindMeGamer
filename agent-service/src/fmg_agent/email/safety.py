"""Durable sender circuit breaker; only an administrator can release a hold."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, String, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..errors import ApiError


class SenderSafety(Base):
    __tablename__ = "email_sender_safety"
    sender: Mapped[str] = mapped_column(String(254), primary_key=True)
    reason: Mapped[str | None] = mapped_column(String(60))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def locked(session, sender):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    sender = sender.casefold()
    session.execute(insert(SenderSafety).values(sender=sender).on_conflict_do_nothing())
    return session.scalar(
        select(SenderSafety).where(SenderSafety.sender == sender).with_for_update()
    )


def check(session, sender):
    row = locked(session, sender)
    if row.reason:
        raise ApiError(
            409,
            "email_sender_paused",
            "Sending is paused for this mailbox. An administrator must review delivery failures and explicitly release the hold; no send attempt was created.",
        )


def status(session, sender):
    row = session.get(SenderSafety, sender.casefold())
    return {
        "state": "paused" if row and row.reason else "ready",
        "reason": row.reason if row else None,
        "paused_at": row.paused_at if row else None,
    }


def trip(session, sender, reason, now=None):
    from ..outreach import OutreachTask, OutreachRecipient
    from .models import EmailPreview, EmailSend

    row = locked(session, sender)
    if not row.reason:
        row.reason = reason
        row.paused_at = now or datetime.now(timezone.utc)
    # Do not rewrite completed historical batches that retain a stored 'sending' state.
    active = (
        select(OutreachRecipient.task_id)
        .join(EmailPreview, EmailPreview.id == OutreachRecipient.preview_id)
        .outerjoin(EmailSend, EmailSend.preview_id == EmailPreview.id)
        .where(
            func.lower(EmailPreview.message["from"].as_string()) == sender.casefold(),
            (EmailSend.id.is_(None)) | (EmailSend.state == "sending"),
        )
    )
    session.execute(
        update(OutreachTask)
        .where(OutreachTask.state == "sending", OutreachTask.id.in_(active))
        .values(state="blocked")
    )


def observe_bounce(session, sender, now):
    from .inbox import EmailReply
    from .models import EmailPreview, EmailSend

    # Serialize counting and the final send reservation on the same sender row.
    locked(session, sender)
    count = session.scalar(
        select(
            func.count(
                func.distinct(func.lower(EmailPreview.message["to"].as_string()))
            )
        )
        .select_from(EmailReply)
        .join(EmailSend, EmailSend.id == EmailReply.send_id)
        .join(EmailPreview, EmailPreview.id == EmailSend.preview_id)
        .where(
            func.lower(EmailPreview.message["from"].as_string()) == sender.casefold(),
            EmailReply.kind == "bounce",
            EmailReply.diagnostics["category"].as_string() == "spam_blocked",
            EmailReply.received_at >= (now - timedelta(minutes=15)).isoformat(),
        )
    )
    if count >= 3:
        trip(session, sender, "outbound_spam_blocked", now)
