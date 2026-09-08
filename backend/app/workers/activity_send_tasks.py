"""Frozen Activity email execution with explicit verification for uncertain submits."""

from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr
from uuid import UUID, uuid4
from sqlalchemy import select
from redis import Redis
from app.core.config import get_settings
from app.core.crypto import SecretCipher, EncryptedValue
from app.core.database import session_scope
from app.core.idempotency import utc_now
from app.db.models.activity_sending import ActivityDelivery
from app.discovery.evaluation_snapshot import digest
from app.outreach.activity_qualification import account_state
from app.outreach.smtp import (
    SMTPConfig,
    SMTPGateway,
    SMTPUnknownOutcome,
    SMTPPermanentError,
    SMTPTransientError,
)
from app.outreach.rate_limit import SMTPRateLimiter
from app.repositories.settings import SettingsRepository, SHARED_SETTINGS_ID
from app.repositories.activity_sending import sending_expired
from app.workers.celery_app import celery_app


class CeleryActivitySendDispatcher:
    def dispatch(self, identity, *, delay=0):
        kwargs = {"countdown": delay} if delay else {}
        celery_app.send_task(
            "find_me_gamer.outreach.send_activity_delivery",
            args=[str(identity)],
            **kwargs,
        )


def lock_delivery(session, identity):
    return session.scalar(
        select(ActivityDelivery)
        .where(ActivityDelivery.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def frozen_message(identity, snapshot):
    sender = snapshot["sender"]
    message = EmailMessage()
    message["From"] = formataddr((sender["name"], sender["address"]))
    message["To"] = snapshot["recipient_email"]
    message["Reply-To"] = sender["reply_to"]
    message["Subject"] = snapshot["subject"]
    message["Message-ID"] = f"<{identity}@{sender['address'].rsplit('@', 1)[1]}>"
    message.set_content(snapshot["text"])
    message.add_alternative(snapshot["html"], subtype="html")
    return message


def run_delivery(
    identity,
    *,
    session_factory=session_scope,
    smtp_gateway=None,
    secret_cipher=None,
    limiter=None,
    dispatcher=None,
):
    smtp_gateway = smtp_gateway or SMTPGateway()
    dispatcher = dispatcher or CeleryActivitySendDispatcher()
    settings = get_settings()
    owned_redis = None
    if limiter is None:
        owned_redis = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_read_timeout_seconds,
        )
        limiter = SMTPRateLimiter(owned_redis)
    try:
        _execute(
            identity,
            session_factory=session_factory,
            smtp_gateway=smtp_gateway,
            secret_cipher=secret_cipher,
            limiter=limiter,
            dispatcher=dispatcher,
        )
    finally:
        if owned_redis is not None:
            owned_redis.close()


def _execute(
    identity, *, session_factory, smtp_gateway, secret_cipher, limiter, dispatcher
):
    with session_factory() as session:
        row = lock_delivery(session, identity)
        if row is None:
            return
        if sending_expired(row):
            row.state, row.error_code, row.retryable = (
                "unknown",
                "smtp_outcome_unknown",
                False,
            )
            row.lease_token = None
            return
        if row.state != "queued":
            return
        token, attempt = uuid4(), row.attempt + 1
        row.state, row.attempt, row.lease_token = "sending", attempt, token
        row.sending_at, row.failed_at, row.sent_at = utc_now(), None, None
        row.lease_expires_at = utc_now() + timedelta(seconds=300)
        row.error_code, row.retryable = None, False
        snapshot = row.snapshot
        public, configured = account_state(session)
        if (
            not configured
            or digest({"public": public, "configured": configured})
            != snapshot["sending_account_token"]
        ):
            row.state, row.error_code, row.retryable = (
                "failed",
                "sending_account_changed",
                True,
            )
            row.failed_at, row.lease_token, row.lease_expires_at = utc_now(), None, None
            return
        repository = SettingsRepository(session)
        secret = repository.get_connection("smtp")
        encrypted = EncryptedValue(ciphertext=secret.ciphertext, nonce=secret.nonce)
        rate = repository.get_smtp_settings().smtp_rate_per_minute
    state, error, delay = "sent", None, 0
    try:
        cipher = secret_cipher or SecretCipher.from_file(get_settings().master_key_file)
        config = SMTPConfig(**public, password=cipher.decrypt(encrypted))
        message = frozen_message(identity, snapshot)
        delay = limiter.acquire(str(SHARED_SETTINGS_ID), rate)
        if delay > 0:
            state = "queued"
        else:
            receipt = smtp_gateway.send(config, message)
            if receipt.accepted_recipients != 1:
                raise SMTPPermanentError("SMTP rejected the request.")
    except SMTPUnknownOutcome:
        state, error = "unknown", "smtp_outcome_unknown"
    except SMTPPermanentError:
        state, error = "failed", "smtp_rejected"
    except SMTPTransientError:
        state, error = "failed", "smtp_temporarily_unavailable"
    except Exception:
        state, error = "failed", "smtp_preparation_failed"
    with session_factory() as session:
        row = lock_delivery(session, identity)
        if (
            row is None
            or row.state != "sending"
            or row.attempt != attempt
            or row.lease_token != token
        ):
            return
        if sending_expired(row):
            state, error = "unknown", "smtp_outcome_unknown"
        row.state, row.error_code = state, error
        row.retryable = state == "failed"
        row.lease_token, row.lease_expires_at = None, None
        if state == "sent":
            row.sent_at = utc_now()
        elif state in {"failed", "unknown"}:
            row.failed_at = utc_now()
        elif state == "queued":
            row.sending_at = None
    if state == "queued":
        try:
            dispatcher.dispatch(identity, delay=delay)
        except Exception:
            # The existing queued row is visible and can be explicitly redispatched.
            return


@celery_app.task(name="find_me_gamer.outreach.send_activity_delivery")
def send_activity_delivery(identity):
    run_delivery(UUID(identity))
