"""Idempotent Outreach Delivery publication and SMTP execution."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr
import hmac
from functools import lru_cache
from time import sleep
from uuid import UUID

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import EncryptedValue, SecretCipher
from app.core.database import session_scope
from app.db.models.outreach import (
    Delivery,
    DeliverySendState,
    SendBatch,
    SendBatchState,
)
from app.db.models.settings import ServiceSecret, SharedSettings
from app.outreach.batches import response_token_digest
from app.outreach.rate_limit import SMTPRateLimitError, SMTPRateLimiter
from app.outreach.smtp import (
    SMTPConfig,
    SMTPGateway,
    SMTPPermanentError,
    SMTPTransientError,
)
from app.repositories.settings import SHARED_SETTINGS_ID, SMTP_PUBLIC_FIELDS
from app.schemas.outreach import (
    ACCEPTED_RESPONSE_URL_PLACEHOLDER,
    DECLINED_RESPONSE_URL_PLACEHOLDER,
)
from app.workers.analysis_tasks import RetryPolicy, random_jitter
from app.workers.celery_app import celery_app


SEND_DELIVERY_TASK_NAME = "find_me_gamer.outreach.send_delivery"
_TEMPORARY_CODE = "smtp_temporarily_unavailable"
_TEMPORARY_MESSAGE = "SMTP is temporarily unavailable."
_PERMANENT_CODE = "smtp_rejected"
_PERMANENT_MESSAGE = "SMTP rejected the request."
_PREPARATION_CODE = "outreach_delivery_invalid"
_PREPARATION_MESSAGE = "Outreach delivery could not be prepared."

SessionFactory = Callable[[], AbstractContextManager[Session]]


class RetryableDeliveryError(RuntimeError):
    """An allowlisted failure for which Celery should retry the same Delivery."""


class SafeOutreachTaskError(RuntimeError):
    """Celery metadata that never includes SMTP, credential, or token details."""

    def __init__(self) -> None:
        super().__init__(_TEMPORARY_CODE)


@dataclass(frozen=True, slots=True)
class DeliverySnapshot:
    id: UUID
    recipient_email: str
    rendered_subject: str
    rendered_markdown: str
    rendered_html: str
    sender_name: str
    sender_address: str
    reply_to: str
    response_token_digest: str


@dataclass(frozen=True, slots=True)
class SMTPRuntimeSettings:
    host: str
    port: int
    encryption: str
    username: str
    from_name: str
    reply_to: str
    rate_per_minute: int
    encrypted_password: EncryptedValue


def _aware_utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise RetryableDeliveryError(_TEMPORARY_CODE)
    return value.astimezone(UTC)


def _parse_delivery_id(raw_delivery_id: object) -> UUID | None:
    if not isinstance(raw_delivery_id, str) or len(raw_delivery_id) != 36:
        return None
    try:
        value = UUID(raw_delivery_id)
    except ValueError:
        return None
    if str(value) != raw_delivery_id or value.int == 0:
        return None
    return value


def _recompute_batch(session: Session, send_batch_id: UUID) -> None:
    batch = session.scalar(
        select(SendBatch).where(SendBatch.id == send_batch_id).with_for_update()
    )
    if batch is None:
        return
    states = list(
        session.scalars(
            select(Delivery.send_state)
            .where(Delivery.send_batch_id == send_batch_id)
            .order_by(Delivery.id)
            .with_for_update()
        )
    )
    if not states:
        return
    if all(state is DeliverySendState.QUEUED for state in states):
        batch.state = SendBatchState.QUEUED
    elif all(state is DeliverySendState.SENT for state in states):
        batch.state = SendBatchState.SENT
    elif all(state is DeliverySendState.FAILED for state in states):
        batch.state = SendBatchState.FAILED
    elif all(
        state in {DeliverySendState.SENT, DeliverySendState.FAILED} for state in states
    ):
        batch.state = SendBatchState.PARTIALLY_FAILED
    else:
        batch.state = SendBatchState.SENDING


def _lock_delivery_after_batch(session: Session, delivery_id: UUID) -> Delivery | None:
    located = session.get(Delivery, delivery_id)
    if located is None:
        return None
    session.scalar(
        select(SendBatch).where(SendBatch.id == located.send_batch_id).with_for_update()
    )
    return session.scalar(
        select(Delivery)
        .where(Delivery.id == delivery_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


class DeliveryTaskStore:
    """Short transactional Delivery transitions used by the SMTP executor."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def claim(self, delivery_id: UUID, *, retrying: bool) -> DeliverySnapshot | None:
        del retrying
        with self._session_factory() as session:
            delivery = _lock_delivery_after_batch(session, delivery_id)
            if delivery is None or delivery.superseded_at is not None:
                session.commit()
                return None
            if delivery.send_state is not DeliverySendState.QUEUED:
                session.commit()
                return None
            delivery.send_state = DeliverySendState.SENDING
            delivery.sending_at = _aware_utc(self._clock)
            snapshot = DeliverySnapshot(
                id=delivery.id,
                recipient_email=delivery.recipient_email,
                rendered_subject=delivery.rendered_subject,
                rendered_markdown=delivery.rendered_markdown,
                rendered_html=delivery.rendered_html,
                sender_name=delivery.sender_name,
                sender_address=delivery.sender_address,
                reply_to=delivery.reply_to,
                response_token_digest=delivery.response_token_digest,
            )
            _recompute_batch(session, delivery.send_batch_id)
            session.commit()
            return snapshot

    def release_for_retry(self, delivery_id: UUID) -> bool:
        with self._session_factory() as session:
            delivery = _lock_delivery_after_batch(session, delivery_id)
            if (
                delivery is None
                or delivery.superseded_at is not None
                or delivery.send_state is not DeliverySendState.SENDING
            ):
                session.commit()
                return False
            delivery.send_state = DeliverySendState.QUEUED
            delivery.sending_at = None
            delivery.sent_at = None
            delivery.failed_at = None
            delivery.smtp_error_code = None
            delivery.smtp_error_message = None
            delivery.smtp_retryable = False
            _recompute_batch(session, delivery.send_batch_id)
            session.commit()
            return True

    def load_smtp_settings(self) -> SMTPRuntimeSettings:
        with self._session_factory() as session:
            settings = session.get(SharedSettings, SHARED_SETTINGS_ID)
            secret = session.scalar(
                select(ServiceSecret).where(ServiceSecret.service == "smtp")
            )
            metadata = (
                settings.service_connection_state.get("smtp")
                if settings is not None
                and isinstance(settings.service_connection_state, dict)
                else None
            )
            if not isinstance(metadata, dict) or secret is None or settings is None:
                session.commit()
                raise RetryableDeliveryError(_TEMPORARY_CODE)
            public = {field: metadata.get(field) for field in SMTP_PUBLIC_FIELDS}
            required_strings = ("host", "username", "from_name", "reply_to")
            if (
                any(
                    not isinstance(public[field], str) or not public[field].strip()
                    for field in required_strings
                )
                or not isinstance(public["port"], int)
                or isinstance(public["port"], bool)
                or not 1 <= public["port"] <= 65_535
                or public["encryption"] not in {"tls", "starttls", "none"}
                or not 1 <= settings.smtp_rate_per_minute <= 60
            ):
                session.commit()
                raise RetryableDeliveryError(_TEMPORARY_CODE)
            runtime = SMTPRuntimeSettings(
                host=str(public["host"]),
                port=int(public["port"]),
                encryption=str(public["encryption"]),
                username=str(public["username"]),
                from_name=str(public["from_name"]),
                reply_to=str(public["reply_to"]),
                rate_per_minute=settings.smtp_rate_per_minute,
                encrypted_password=EncryptedValue(
                    ciphertext=bytes(secret.ciphertext), nonce=bytes(secret.nonce)
                ),
            )
            session.commit()
            return runtime

    def mark_sent(self, delivery_id: UUID) -> bool:
        with self._session_factory() as session:
            delivery = _lock_delivery_after_batch(session, delivery_id)
            if (
                delivery is None
                or delivery.superseded_at is not None
                or delivery.send_state is not DeliverySendState.SENDING
            ):
                session.commit()
                return False
            delivery.send_state = DeliverySendState.SENT
            delivery.sent_at = _aware_utc(self._clock)
            delivery.failed_at = None
            delivery.smtp_error_code = None
            delivery.smtp_error_message = None
            delivery.smtp_retryable = False
            _recompute_batch(session, delivery.send_batch_id)
            session.commit()
            return True

    def mark_failed(
        self,
        delivery_id: UUID,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> bool:
        allowed = {
            (_PERMANENT_CODE, _PERMANENT_MESSAGE, False),
            (_PREPARATION_CODE, _PREPARATION_MESSAGE, False),
            (_TEMPORARY_CODE, _TEMPORARY_MESSAGE, True),
        }
        if (code, message, retryable) not in allowed:
            raise ValueError("invalid safe Outreach failure")
        with self._session_factory() as session:
            delivery = _lock_delivery_after_batch(session, delivery_id)
            if (
                delivery is None
                or delivery.superseded_at is not None
                or delivery.send_state is not DeliverySendState.SENDING
            ):
                session.commit()
                return False
            delivery.send_state = DeliverySendState.FAILED
            delivery.failed_at = _aware_utc(self._clock)
            delivery.sent_at = None
            delivery.smtp_error_code = code
            delivery.smtp_error_message = message
            delivery.smtp_retryable = retryable
            _recompute_batch(session, delivery.send_batch_id)
            session.commit()
            return True


class DeliveryExecutor:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        secret_cipher: SecretCipher,
        smtp_gateway: SMTPGateway,
        smtp_rate_limiter: SMTPRateLimiter,
        external_base_url: str,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], object] = sleep,
    ) -> None:
        self._store = DeliveryTaskStore(session_factory=session_factory, clock=clock)
        self._secret_cipher = secret_cipher
        self._smtp_gateway = smtp_gateway
        self._smtp_rate_limiter = smtp_rate_limiter
        self._external_base_url = external_base_url.rstrip("/")
        self._sleeper = sleeper

    def execute_raw(self, raw_delivery_id: object, *, retrying: bool) -> None:
        delivery_id = _parse_delivery_id(raw_delivery_id)
        if delivery_id is not None:
            self.execute(delivery_id, retrying=retrying)

    def execute(self, delivery_id: UUID, *, retrying: bool) -> None:
        snapshot = self._store.claim(delivery_id, retrying=retrying)
        if snapshot is None:
            return
        try:
            runtime = self._store.load_smtp_settings()
            try:
                password = self._secret_cipher.decrypt(runtime.encrypted_password)
            except Exception:
                raise RetryableDeliveryError(_TEMPORARY_CODE) from None
            config = SMTPConfig(
                host=runtime.host,
                port=runtime.port,
                encryption=runtime.encryption,
                username=runtime.username,
                password=password,
                from_name=runtime.from_name,
                reply_to=runtime.reply_to,
            )
            del password
            message = self._message(snapshot)
            while True:
                try:
                    delay = self._smtp_rate_limiter.acquire(
                        str(SHARED_SETTINGS_ID), runtime.rate_per_minute
                    )
                except SMTPRateLimitError:
                    raise RetryableDeliveryError(_TEMPORARY_CODE) from None
                if delay <= 0:
                    break
                self._sleeper(delay)
            self._smtp_gateway.send(config, message)
        except SMTPPermanentError:
            self._store.mark_failed(
                delivery_id,
                code=_PERMANENT_CODE,
                message=_PERMANENT_MESSAGE,
                retryable=False,
            )
            return
        except RetryableDeliveryError:
            raise
        except SMTPTransientError:
            raise RetryableDeliveryError(_TEMPORARY_CODE) from None
        except Exception:
            raise RetryableDeliveryError(_TEMPORARY_CODE) from None
        self._store.mark_sent(delivery_id)

    def fail_exhausted_retry(self, delivery_id: UUID) -> None:
        self._store.mark_failed(
            delivery_id,
            code=_TEMPORARY_CODE,
            message=_TEMPORARY_MESSAGE,
            retryable=True,
        )

    def release_for_retry(self, delivery_id: UUID) -> bool:
        return self._store.release_for_retry(delivery_id)

    def _message(self, snapshot: DeliverySnapshot) -> EmailMessage:
        raw_token = self._secret_cipher.derive_outreach_response_token(snapshot.id)
        if not hmac.compare_digest(
            response_token_digest(raw_token), snapshot.response_token_digest
        ):
            del raw_token
            self._store.mark_failed(
                snapshot.id,
                code=_PREPARATION_CODE,
                message=_PREPARATION_MESSAGE,
                retryable=False,
            )
            raise SMTPPermanentError(_PREPARATION_MESSAGE)
        accepted_url = f"{self._external_base_url}/r/{raw_token}?choice=accepted"
        declined_url = f"{self._external_base_url}/r/{raw_token}?choice=declined"
        try:
            plain = snapshot.rendered_markdown
            html = _substitute_response_links(
                snapshot.rendered_html, accepted_url, declined_url
            )
        except ValueError:
            self._store.mark_failed(
                snapshot.id,
                code=_PREPARATION_CODE,
                message=_PREPARATION_MESSAGE,
                retryable=False,
            )
            raise SMTPPermanentError(_PREPARATION_MESSAGE) from None
        finally:
            del raw_token
        message = EmailMessage()
        message["From"] = formataddr((snapshot.sender_name, snapshot.sender_address))
        message["Reply-To"] = snapshot.reply_to
        message["To"] = snapshot.recipient_email
        message["Subject"] = snapshot.rendered_subject
        message["Message-ID"] = f"<{snapshot.id}@find-me-gamer.local>"
        message.set_content(plain)
        message.add_alternative(html, subtype="html")
        return message


def _substitute_response_links(value: str, accepted_url: str, declined_url: str) -> str:
    if (
        value.count(ACCEPTED_RESPONSE_URL_PLACEHOLDER) != 1
        or value.count(DECLINED_RESPONSE_URL_PLACEHOLDER) != 1
    ):
        raise ValueError("invalid response placeholders")
    return value.replace(ACCEPTED_RESPONSE_URL_PLACEHOLDER, accepted_url, 1).replace(
        DECLINED_RESPONSE_URL_PLACEHOLDER, declined_url, 1
    )


@lru_cache
def get_delivery_executor() -> DeliveryExecutor:
    settings = get_settings()
    redis_client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.redis_connect_timeout_seconds,
        socket_timeout=settings.redis_read_timeout_seconds,
    )
    return DeliveryExecutor(
        session_factory=session_scope,
        secret_cipher=SecretCipher.from_file(settings.master_key_file),
        smtp_gateway=SMTPGateway(),
        smtp_rate_limiter=SMTPRateLimiter(redis_client),
        external_base_url=settings.external_base_url,
    )


def _retry_policy() -> RetryPolicy:
    settings = get_settings()
    return RetryPolicy(
        max_retries=settings.outreach_task_max_retries,
        base_delay_seconds=settings.outreach_retry_base_delay_seconds,
        max_delay_seconds=settings.outreach_retry_max_delay_seconds,
    )


@celery_app.task(bind=True, name=SEND_DELIVERY_TASK_NAME, ignore_result=True)
def send_delivery(self, delivery_id: str) -> None:
    executor = get_delivery_executor()
    try:
        executor.execute_raw(delivery_id, retrying=self.request.retries > 0)
    except RetryableDeliveryError:
        parsed = _parse_delivery_id(delivery_id)
        policy = _retry_policy()
        if self.request.retries >= policy.max_retries:
            if parsed is not None:
                executor.fail_exhausted_retry(parsed)
            return
        if parsed is not None:
            executor.release_for_retry(parsed)
        raise self.retry(
            exc=SafeOutreachTaskError(),
            countdown=policy.countdown(
                self.request.retries,
                jitter=random_jitter(policy.base_delay_seconds),
            ),
            max_retries=policy.max_retries,
        )


def enqueue_send_batch(send_batch_id: UUID) -> int:
    if type(send_batch_id) is not UUID or send_batch_id.int == 0:
        raise ValueError("invalid Send Batch ID")
    with session_scope() as session:
        delivery_ids = list(
            session.scalars(
                select(Delivery.id)
                .where(
                    Delivery.send_batch_id == send_batch_id,
                    Delivery.send_state == DeliverySendState.QUEUED,
                    Delivery.superseded_at.is_(None),
                )
                .order_by(Delivery.id)
            )
        )
    for delivery_id in delivery_ids:
        send_delivery.apply_async(
            args=[str(delivery_id)], retry=False, ignore_result=True
        )
    return len(delivery_ids)


__all__ = [
    "DeliveryExecutor",
    "DeliveryTaskStore",
    "SEND_DELIVERY_TASK_NAME",
    "enqueue_send_batch",
    "send_delivery",
]
