"""A confirmed spam DSN authorizes exactly one delayed, snapshot-preserving resend."""

from copy import deepcopy
from datetime import timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, func

from ..db import AccessToken
from ..errors import ApiError
from ..usage import Ledger
from .jobs import utcnow
from .models import EmailBounceRetry, EmailPreview, EmailSend
from . import safety


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def by_preview(session, preview_id):
    return session.scalar(
        select(EmailBounceRetry).where(EmailBounceRetry.preview_id == preview_id)
    )


def human_reply(session, original_send_id, retry_preview_id=None):
    from .inbox import EmailReply

    send_ids = select(EmailSend.id).where(
        (EmailSend.id == original_send_id) | (EmailSend.preview_id == retry_preview_id)
    )
    return (
        session.scalar(
            select(EmailReply.id)
            .where(EmailReply.send_id.in_(send_ids), EmailReply.kind == "human")
            .limit(1)
        )
        is not None
    )


def observe(session, send, diagnostic, now):
    """In the inbox transaction: deduplicate, schedule, or record a final failure."""
    preview = session.get(EmailPreview, send.preview_id)
    guard = safety.locked(session, preview.message["from"])
    retry = by_preview(session, preview.id)
    if retry is not None:
        # An explicit failed DSN resolves even an uncertain retry as failed.
        fail(session, retry, now)
        return
    if diagnostic["category"] != "spam_blocked":
        return
    if aware(send.created_at) < aware(guard.retry_enabled_at):
        return  # Never replay pre-rollout mail or backfill historical failures.
    if session.get(EmailBounceRetry, send.id) or human_reply(session, send.id):
        return
    child = EmailPreview(
        id=str(uuid4()),
        token_id=preview.token_id,
        template_id=preview.template_id,
        template_version=preview.template_version,
        message=deepcopy(preview.message),
        created_at=preview.created_at,
    )
    session.add(child)
    session.flush()
    session.add(
        EmailBounceRetry(
            original_send_id=send.id,
            preview_id=child.id,
            due_at=now + timedelta(seconds=30),
            state="queued",
        )
    )


def fail(session, retry, now):
    if retry.failed_at is None:
        retry.failed_at = now
        retry.state = "failed"
        original = session.get(EmailSend, retry.original_send_id)
        sender = session.get(EmailPreview, original.preview_id).message["from"]
        session.flush()
        safety.observe_retry_failure(session, sender, now)


def preflight(session, preview_id, key):
    """Called under sender safety lock, at the final send reservation boundary."""
    retry = by_preview(session, preview_id)
    if retry is None:
        return None, preview_id
    if key != "bounce-retry:" + retry.original_send_id:
        raise ApiError(
            409, "bounce_retry_managed", "This resend is managed by the server."
        )
    if retry.state != "queued" or aware(retry.due_at) > utcnow():
        raise ApiError(409, "bounce_retry_not_due", "This resend is not ready.")
    original = session.get(EmailSend, retry.original_send_id)
    token = session.get(AccessToken, original.token_id)
    if not token or token.revoked_at or "email:send" not in token.scopes:
        raise ApiError(
            409, "bounce_retry_access_revoked", "Resend authorization was revoked."
        )
    if human_reply(session, original.id, retry.preview_id):
        raise ApiError(
            409, "bounce_retry_human_reply", "A human already replied; do not resend."
        )
    return retry, original.preview_id


def finish(session, preview_id, outcome, now):
    retry = by_preview(session, preview_id)
    if retry is None or retry.failed_at is not None:
        return  # Do not overwrite a DSN received while the transport was in flight.
    if outcome["state"] == "failed":
        fail(session, retry, now)
    else:
        retry.state = outcome["state"]


def details(retry, send):
    if retry is None:
        return None
    return {
        "state": retry.state,
        "due_at": retry.due_at,
        "failed_at": retry.failed_at,
        "cancel_reason": retry.cancel_reason,
        "send_id": send.id if send else None,
        "code": send.code if send else None,
        "diagnostics": send.diagnostics if send else None,
    }


def pending_retries(sessions):
    from ..outreach import OutreachRecipient, OutreachTask

    with sessions() as session:
        return list(
            session.scalars(
                select(EmailBounceRetry.original_send_id)
                .join(EmailSend, EmailSend.id == EmailBounceRetry.original_send_id)
                .join(EmailPreview, EmailPreview.id == EmailSend.preview_id)
                .join(
                    safety.SenderSafety,
                    safety.SenderSafety.sender
                    == func.lower(EmailPreview.message["from"].as_string()),
                )
                .outerjoin(
                    OutreachRecipient, OutreachRecipient.preview_id == EmailPreview.id
                )
                .outerjoin(OutreachTask, OutreachTask.id == OutreachRecipient.task_id)
                .where(
                    EmailBounceRetry.state == "queued",
                    EmailBounceRetry.due_at <= utcnow(),
                    safety.SenderSafety.reason.is_(None),
                    (OutreachTask.id.is_(None)) | (OutreachTask.state == "sending"),
                )
                .order_by(EmailBounceRetry.due_at)
                .limit(20)
            )
        )


def process_retry(sessions, original_send_id, settings, transport):
    from .sending import SendStore
    from ..outreach import OutreachRecipient, OutreachTask

    with sessions() as session:
        retry = session.get(EmailBounceRetry, original_send_id)
        if retry is None or retry.state != "queued" or aware(retry.due_at) > utcnow():
            return
        original = session.get(EmailSend, original_send_id)
        task = session.scalar(
            select(OutreachTask)
            .join(OutreachRecipient)
            .where(OutreachRecipient.preview_id == original.preview_id)
        )
        run_id = task.run_id if task else "bounce-retry:" + original.id

        def tracked(config, message, send_id):
            ledger = Ledger(sessions)
            key = "smtp:" + send_id
            ledger.start(key, original.token_id, run_id, "smtp", "send")
            try:
                outcome = transport(config, message, send_id)
            except Exception:
                ledger.finish(key, "unknown")
                raise
            ledger.finish(key, outcome["state"])
            return outcome

        try:
            SendStore(sessions).send(
                original.token_id,
                retry.preview_id,
                "bounce-retry:" + original.id,
                settings,
                tracked,
            )
        except ApiError as exc:
            if exc.code in {
                "email_send_throttled",
                "email_sender_paused",
                "outreach_task_paused",
                "bounce_retry_not_due",
            }:
                return  # No attempt; a later tick or explicit batch resume may proceed.
            with sessions() as update_session:
                # Serialize cancellation with inbox observation and reservations.
                sender = session.get(EmailPreview, original.preview_id).message["from"]
                safety.locked(update_session, sender)
                record = update_session.get(EmailBounceRetry, original.id)
                if record.state == "queued":
                    record.state = "cancelled"
                    record.cancel_reason = exc.code
                update_session.commit()
