from contextlib import contextmanager
from datetime import UTC, datetime
from email.message import EmailMessage
from uuid import UUID, uuid4

from celery.exceptions import Retry
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.db.models.outreach import Delivery, DeliverySendState, SendBatch
from app.db.models.settings import ServiceSecret
from app.outreach.smtp import SMTPPermanentError, SMTPTransientError
from app.outreach.rate_limit import SMTPRateLimitError
from app.schemas.outreach import (
    ACCEPTED_RESPONSE_URL_PLACEHOLDER,
    DECLINED_RESPONSE_URL_PLACEHOLDER,
)
from app.workers.outreach_tasks import (
    DeliveryExecutor,
    DeliveryTaskStore,
    enqueue_send_batch,
    send_delivery,
)
from tests.integration.test_send_batch_api import (
    _configure,
    _create_batch,
    _payload,
    _published_match,
)


NOW = datetime(2027, 9, 2, 13, 0, tzinfo=UTC)


class SequenceLimiter:
    def __init__(self, *results: float | Exception) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, int]] = []

    def acquire(self, workspace: str, per_minute: int) -> float:
        self.calls.append((workspace, per_minute))
        result = self.results.pop(0) if self.results else 0.0
        if isinstance(result, Exception):
            raise result
        return result


class RecordingGateway:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[object, EmailMessage]] = []

    def send(self, config: object, message: EmailMessage) -> object:
        self.calls.append((config, message))
        if self.error is not None:
            raise self.error
        return object()


def _session_factory(session: Session):
    @contextmanager
    def factory():
        yield session

    return factory


def _queued_delivery(auth_client, session: Session) -> tuple[SendBatch, Delivery]:
    task, creators, _campaign = _published_match(
        session, [(f"Creator {uuid4().hex[:6]}", "creator@example.com")]
    )
    _configure(auth_client)
    response = _create_batch(
        auth_client,
        _payload(task, creators),
        f"worker-seed-{uuid4().hex}",
    )
    assert response.status_code == 201, response.text
    delivery = session.get(Delivery, UUID(response.json()["deliveries"][0]["id"]))
    batch = session.get(SendBatch, UUID(response.json()["id"]))
    assert delivery is not None and batch is not None
    assert (
        delivery.rendered_html.count(ACCEPTED_RESPONSE_URL_PLACEHOLDER),
        delivery.rendered_html.count(DECLINED_RESPONSE_URL_PLACEHOLDER),
    ) == (1, 1)
    return batch, delivery


def _executor(
    session: Session,
    gateway: RecordingGateway,
    limiter: SequenceLimiter | None = None,
    *,
    sleeps: list[float] | None = None,
) -> DeliveryExecutor:
    recorded_sleeps = sleeps if sleeps is not None else []
    return DeliveryExecutor(
        session_factory=_session_factory(session),
        secret_cipher=SecretCipher(bytes(range(32))),
        smtp_gateway=gateway,
        smtp_rate_limiter=limiter or SequenceLimiter(0),
        external_base_url="https://demo.findmegamer.example",
        clock=lambda: NOW,
        sleeper=recorded_sleeps.append,
    )


def test_smtp_acceptance_is_sent_not_delivered(auth_client, session: Session) -> None:
    batch, delivery = _queued_delivery(auth_client, session)
    gateway = RecordingGateway()

    _executor(session, gateway).execute(delivery.id, retrying=False)

    session.expire_all()
    saved = session.get(Delivery, delivery.id)
    saved_batch = session.get(SendBatch, batch.id)
    assert saved is not None and saved_batch is not None
    assert saved.send_state is DeliverySendState.SENT, (
        saved.smtp_error_code,
        saved.smtp_error_message,
    )
    assert saved.sent_at == NOW
    assert not hasattr(saved, "delivered_at")
    assert saved_batch.state.value == "sent"
    assert len(gateway.calls) == 1


def test_legacy_submission_unknown_is_terminal_without_automatic_retry(
    auth_client, session
):
    from app.outreach.smtp import SMTPUnknownOutcome

    _, delivery = _queued_delivery(auth_client, session)
    gateway = RecordingGateway(SMTPUnknownOutcome("Do not expose upstream text"))
    _executor(session, gateway).execute(delivery.id, retrying=False)
    session.expire_all()
    saved = session.get(Delivery, delivery.id)
    assert saved.send_state is DeliverySendState.FAILED
    assert saved.smtp_error_code == "smtp_outcome_unknown" and not saved.smtp_retryable
    public = auth_client.get(f"/api/v1/outreach/deliveries/{delivery.id}")
    assert public.status_code == 200, public.text
    assert public.json()["smtp_error"]["code"] == "smtp_outcome_unknown"
    assert not public.json()["smtp_error"]["retryable"]
    _executor(session, gateway).execute(delivery.id, retrying=False)
    assert len(gateway.calls) == 1


def test_actual_message_uses_snapshot_and_absolute_response_links_without_persisting_token(
    auth_client, session: Session
) -> None:
    _batch, delivery = _queued_delivery(auth_client, session)
    original_html = delivery.rendered_html
    digest = delivery.response_token_digest
    gateway = RecordingGateway()

    _executor(session, gateway).execute(delivery.id, retrying=False)

    config, message = gateway.calls[0]
    raw_token = SecretCipher(bytes(range(32))).derive_outreach_response_token(
        delivery.id
    )
    wire = message.get_body(preferencelist=("html",)).get_content()
    assert message["From"] == "Find Me Gamer Team <sender@example.com>"
    assert message["Reply-To"] == delivery.reply_to
    assert message["To"] == delivery.recipient_email
    assert message["Subject"] == delivery.rendered_subject
    assert message["Message-ID"] == f"<{delivery.id}@find-me-gamer.local>"
    assert (
        message.get_body(preferencelist=("plain",)).get_content().strip()
        == delivery.rendered_markdown
    )
    assert f"https://demo.findmegamer.example/r/{raw_token}?choice=accepted" in wire
    assert f"https://demo.findmegamer.example/r/{raw_token}?choice=declined" in wire
    assert ACCEPTED_RESPONSE_URL_PLACEHOLDER not in wire
    assert DECLINED_RESPONSE_URL_PLACEHOLDER not in wire
    assert getattr(config, "password") == "smtp-secret"
    session.expire(delivery)
    assert delivery.rendered_html == original_html
    assert delivery.response_token_digest == digest
    assert raw_token not in delivery.rendered_html


def test_normal_duplicate_delivery_does_not_call_smtp_twice(
    auth_client, session: Session
) -> None:
    _batch, delivery = _queued_delivery(auth_client, session)
    gateway = RecordingGateway()
    executor = _executor(session, gateway)

    executor.execute(delivery.id, retrying=False)
    executor.execute(delivery.id, retrying=False)

    assert len(gateway.calls) == 1


@pytest.mark.parametrize("raw_delivery_id", ["not-a-uuid", str(uuid4())])
def test_malformed_or_missing_delivery_is_a_safe_noop(
    session: Session, raw_delivery_id: str
) -> None:
    gateway = RecordingGateway()
    executor = _executor(session, gateway)

    executor.execute_raw(raw_delivery_id, retrying=False)

    assert gateway.calls == []


def test_transient_smtp_error_retries(
    auth_client, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _batch, delivery = _queued_delivery(auth_client, session)
    gateway = RecordingGateway(SMTPTransientError("unsafe upstream detail"))
    executor = _executor(session, gateway)
    monkeypatch.setattr(
        "app.workers.outreach_tasks.get_delivery_executor", lambda: executor
    )

    with pytest.raises(Retry):
        send_delivery.apply(args=[str(delivery.id)], throw=True)

    session.expire_all()
    saved = session.get(Delivery, delivery.id)
    assert saved is not None
    assert saved.send_state is DeliverySendState.QUEUED
    assert saved.sending_at is None
    assert saved.smtp_error_code is None
    assert saved.smtp_error_message is None


def test_duplicate_positive_retry_messages_share_one_fresh_claim(
    auth_client, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _batch, delivery = _queued_delivery(auth_client, session)
    executor = _executor(
        session,
        RecordingGateway(SMTPTransientError("unsafe upstream detail")),
    )
    monkeypatch.setattr(
        "app.workers.outreach_tasks.get_delivery_executor", lambda: executor
    )
    with pytest.raises(Retry):
        send_delivery.apply(args=[str(delivery.id)], throw=True)

    store = DeliveryTaskStore(
        session_factory=_session_factory(session), clock=lambda: NOW
    )
    first_retry_claim = store.claim(delivery.id, retrying=True)
    second_duplicate_retry_claim = store.claim(delivery.id, retrying=True)

    assert first_retry_claim is not None
    assert second_duplicate_retry_claim is None


def test_limiter_outage_retries_without_calling_smtp(
    auth_client, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _batch, delivery = _queued_delivery(auth_client, session)
    gateway = RecordingGateway()
    executor = _executor(
        session,
        gateway,
        SequenceLimiter(SMTPRateLimitError("redis secret")),
    )
    monkeypatch.setattr(
        "app.workers.outreach_tasks.get_delivery_executor", lambda: executor
    )

    with pytest.raises(Retry):
        send_delivery.apply(args=[str(delivery.id)], throw=True)

    assert gateway.calls == []
    session.expire_all()
    saved = session.get(Delivery, delivery.id)
    assert saved.send_state is DeliverySendState.QUEUED
    assert saved.sending_at is None


def test_missing_current_smtp_configuration_retries_without_calling_smtp(
    auth_client, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _batch, delivery = _queued_delivery(auth_client, session)
    session.query(ServiceSecret).filter_by(service="smtp").delete()
    session.commit()
    gateway = RecordingGateway()
    executor = _executor(session, gateway)
    monkeypatch.setattr(
        "app.workers.outreach_tasks.get_delivery_executor", lambda: executor
    )

    with pytest.raises(Retry):
        send_delivery.apply(args=[str(delivery.id)], throw=True)

    assert gateway.calls == []
    session.expire_all()
    saved = session.get(Delivery, delivery.id)
    assert saved.send_state is DeliverySendState.QUEUED
    assert saved.sending_at is None


def test_transient_retry_exhaustion_becomes_terminal_failed(
    auth_client, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch, delivery = _queued_delivery(auth_client, session)
    gateway = RecordingGateway(SMTPTransientError("upstream secret"))
    executor = _executor(session, gateway)
    monkeypatch.setattr(
        "app.workers.outreach_tasks.get_delivery_executor", lambda: executor
    )
    send_delivery.apply(args=[str(delivery.id)], retries=3, throw=True).get()

    session.expire_all()
    saved = session.get(Delivery, delivery.id)
    assert saved.send_state is DeliverySendState.FAILED
    assert saved.smtp_error_code == "smtp_temporarily_unavailable"
    assert saved.smtp_error_message == "SMTP is temporarily unavailable."
    assert saved.smtp_retryable is True
    assert session.get(SendBatch, batch.id).state.value == "failed"


def test_permanent_smtp_error_is_terminal_and_safe(
    auth_client, session: Session
) -> None:
    batch, delivery = _queued_delivery(auth_client, session)
    gateway = RecordingGateway(SMTPPermanentError("mailbox secret"))

    _executor(session, gateway).execute(delivery.id, retrying=False)

    session.expire_all()
    saved = session.get(Delivery, delivery.id)
    saved_batch = session.get(SendBatch, batch.id)
    assert saved is not None and saved_batch is not None
    assert saved.send_state is DeliverySendState.FAILED
    assert saved.smtp_error_code == "smtp_rejected"
    assert saved.smtp_error_message == "SMTP rejected the request."
    assert "secret" not in saved.smtp_error_message
    assert saved.failed_at == NOW
    assert saved_batch.state.value == "failed"


def test_positive_rate_limit_delay_reacquires_before_smtp(
    auth_client, session: Session
) -> None:
    _batch, delivery = _queued_delivery(auth_client, session)
    limiter = SequenceLimiter(0.25, 0.0)
    sleeps: list[float] = []
    gateway = RecordingGateway()

    _executor(session, gateway, limiter, sleeps=sleeps).execute(
        delivery.id, retrying=False
    )

    assert sleeps == [0.25]
    assert len(limiter.calls) == 2
    assert len(gateway.calls) == 1


@pytest.mark.parametrize(
    ("send_state", "superseded"),
    [
        (DeliverySendState.SENDING, False),
        (DeliverySendState.SENT, False),
        (DeliverySendState.FAILED, False),
        (DeliverySendState.QUEUED, True),
    ],
)
def test_nonqueued_or_superseded_delivery_is_a_safe_noop(
    auth_client,
    session: Session,
    send_state: DeliverySendState,
    superseded: bool,
) -> None:
    _batch, delivery = _queued_delivery(auth_client, session)
    delivery.send_state = send_state
    if send_state is not DeliverySendState.QUEUED:
        delivery.sending_at = NOW
    if send_state is DeliverySendState.SENT:
        delivery.sent_at = NOW
    if send_state is DeliverySendState.FAILED:
        delivery.failed_at = NOW
        delivery.smtp_error_code = "smtp_rejected"
        delivery.smtp_error_message = "SMTP rejected the request."
    if superseded:
        delivery.superseded_at = NOW
    session.commit()
    gateway = RecordingGateway()

    _executor(session, gateway).execute(
        delivery.id,
        retrying=send_state is DeliverySendState.SENDING,
    )

    assert gateway.calls == []


def test_enqueue_send_batch_publishes_only_current_queued_deliveries(
    auth_client,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, creators, _campaign = _published_match(
        session,
        [
            ("Queued Creator", "queued@example.com"),
            ("Sending Creator", "sending@example.com"),
            ("Sent Creator", "sent@example.com"),
            ("Failed Creator", "failed@example.com"),
            ("Superseded Creator", "superseded@example.com"),
        ],
    )
    _configure(auth_client)
    response = _create_batch(
        auth_client, _payload(task, creators), f"enqueue-{uuid4().hex}"
    )
    batch_id = UUID(response.json()["id"])
    deliveries = session.scalars(
        select(Delivery)
        .where(Delivery.send_batch_id == batch_id)
        .order_by(Delivery.creator_id)
    ).all()
    deliveries[1].send_state = DeliverySendState.SENDING
    deliveries[1].sending_at = NOW
    deliveries[2].send_state = DeliverySendState.SENT
    deliveries[2].sending_at = NOW
    deliveries[2].sent_at = NOW
    deliveries[3].send_state = DeliverySendState.FAILED
    deliveries[3].sending_at = NOW
    deliveries[3].failed_at = NOW
    deliveries[3].smtp_error_code = "smtp_rejected"
    deliveries[3].smtp_error_message = "SMTP rejected the request."
    deliveries[4].superseded_at = NOW
    session.flush()
    published: list[str] = []
    monkeypatch.setattr(
        "app.workers.outreach_tasks.session_scope", _session_factory(session)
    )
    monkeypatch.setattr(
        "app.workers.outreach_tasks.send_delivery.apply_async",
        lambda *, args, **_kwargs: published.append(args[0]),
    )

    count = enqueue_send_batch(batch_id)

    assert count == 1
    assert published == [str(deliveries[0].id)]
