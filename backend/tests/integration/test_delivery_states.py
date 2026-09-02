from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.idempotency import IdempotencyRecord
from app.db.models.outreach import Delivery, DeliverySendState, SendBatch
from tests.integration.test_send_batch_api import (
    _configure,
    _create_batch,
    _payload,
    _published_match,
)


def test_create_commits_before_dispatch_and_replay_heals_broker_failure(
    auth_client,
    session: Session,
    outreach_batch_dispatcher,
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Dispatch Creator", "dispatch@example.com")]
    )
    _configure(auth_client)
    payload = _payload(task, creators)
    key = f"delivery-dispatch-{uuid4().hex}"
    outreach_batch_dispatcher.error = RuntimeError(
        "redis://user:password@private.example:6379"
    )

    failed = _create_batch(auth_client, payload, key)

    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "outreach_queue_unavailable"
    assert failed.json()["error"]["retryable"] is True
    assert "password" not in failed.text
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 1
    assert session.scalar(select(func.count()).select_from(Delivery)) == 1
    record = session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.key == key)
    )
    assert record is not None
    batch_id = UUID(record.response_body["id"])
    assert outreach_batch_dispatcher.calls == [batch_id]

    outreach_batch_dispatcher.error = None
    replay = _create_batch(auth_client, payload, key)

    assert replay.status_code == 201
    assert UUID(replay.json()["id"]) == batch_id
    assert outreach_batch_dispatcher.calls == [batch_id, batch_id]
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 1
    assert session.scalar(select(func.count()).select_from(Delivery)) == 1


def test_resend_commits_replacement_before_dispatch_and_replays_same_batch(
    auth_client,
    session: Session,
    outreach_batch_dispatcher,
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Resend Creator", "resend@example.com")]
    )
    _configure(auth_client)
    created = _create_batch(
        auth_client, _payload(task, creators), f"resend-seed-{uuid4().hex}"
    )
    old = session.get(Delivery, UUID(created.json()["deliveries"][0]["id"]))
    assert old is not None
    old.send_state = DeliverySendState.SENT
    old.sending_at = old.created_at
    old.sent_at = old.created_at
    session.commit()
    outreach_batch_dispatcher.calls.clear()
    outreach_batch_dispatcher.error = RuntimeError("broker unavailable")
    key = f"resend-dispatch-{uuid4().hex}"
    path = f"/api/v1/outreach/deliveries/{old.id}/resend"

    failed = auth_client.post(path, headers={"Idempotency-Key": key})

    assert failed.status_code == 503
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 2
    assert session.scalar(select(func.count()).select_from(Delivery)) == 2
    record = session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.key == key)
    )
    assert record is not None
    replacement_batch_id = UUID(record.response_body["id"])

    outreach_batch_dispatcher.error = None
    replay = auth_client.post(path, headers={"Idempotency-Key": key})

    assert replay.status_code == 201
    assert UUID(replay.json()["id"]) == replacement_batch_id
    assert outreach_batch_dispatcher.calls == [
        replacement_batch_id,
        replacement_batch_id,
    ]


def test_batch_aggregate_tracks_mixed_terminal_states(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(
        session,
        [
            ("Sent Creator", "sent@example.com"),
            ("Failed Creator", "failed@example.com"),
        ],
    )
    _configure(auth_client)
    created = _create_batch(
        auth_client, _payload(task, creators), f"aggregate-{uuid4().hex}"
    )
    batch = session.get(SendBatch, UUID(created.json()["id"]))
    deliveries = session.scalars(
        select(Delivery)
        .where(Delivery.send_batch_id == batch.id)
        .order_by(Delivery.creator_id)
    ).all()
    assert batch is not None and len(deliveries) == 2

    from app.workers.outreach_tasks import DeliveryTaskStore
    from contextlib import contextmanager
    from datetime import UTC, datetime

    @contextmanager
    def factory():
        yield session

    store = DeliveryTaskStore(
        session_factory=factory,
        clock=lambda: datetime(2027, 9, 2, 14, 0, tzinfo=UTC),
    )
    assert store.claim(deliveries[0].id, retrying=False) is not None
    assert store.claim(deliveries[1].id, retrying=False) is not None
    store.mark_sent(deliveries[0].id)
    store.mark_failed(
        deliveries[1].id,
        code="smtp_rejected",
        message="SMTP rejected the request.",
        retryable=False,
    )

    session.expire_all()
    assert session.get(SendBatch, batch.id).state.value == "partially_failed"
