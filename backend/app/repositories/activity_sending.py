"""Atomic final confirmation freezes actual eligible member content once."""

from uuid import UUID
from sqlalchemy import select
from app.api.routes.activity import _get, _error
from app.db.models.activity_sending import ActivitySendBatch, ActivityDelivery
from app.discovery.evaluation_snapshot import digest
from app.outreach.activity_qualification import qualify
from app.schemas.activity_sending import SendBatchView, DeliveryView
from app.outreach.activity_invitation_identity import blocking_delivery
from app.core.idempotency import utc_now


def delivery_view(row):
    result = {key: getattr(row, key) for key in DeliveryView.model_fields}
    if sending_expired(row):
        result.update(
            state="unknown", error_code="smtp_outcome_unknown", retryable=False
        )
    return DeliveryView.model_validate(result).model_dump(mode="json")


def sending_expired(row):
    return (
        row.state == "sending"
        and row.lease_expires_at is not None
        and row.lease_expires_at <= utc_now()
    )


def batch_view(session, row):
    deliveries = session.scalars(
        select(ActivityDelivery)
        .where(ActivityDelivery.send_batch_id == row.id)
        .order_by(ActivityDelivery.input_order, ActivityDelivery.id)
    ).all()
    return SendBatchView(
        id=row.id,
        activity_id=row.activity_id,
        composition_id=row.composition_id,
        created_at=row.created_at,
        qualification=row.qualification_snapshot,
        deliveries=[delivery_view(delivery) for delivery in deliveries],
    ).model_dump(mode="json")


def final_send(session, composition_id, value):
    request_hash = digest(
        {
            "composition_id": str(composition_id),
            "request": value.model_dump(mode="json"),
        }
    )
    old = session.scalar(
        select(ActivitySendBatch).where(
            ActivitySendBatch.request_id == value.request_id
        )
    )
    if old:
        if old.request_hash != request_hash:
            raise _error(
                409,
                "final_send_request_conflict",
                "This request already belongs to a different final confirmation.",
            )
        return batch_view(session, old)
    qualified = qualify(session, composition_id, value.excluded)
    blocked = next(
        (
            m
            for m in qualified["members"]
            if m["blocking_delivery_id"] and m["status"] != "excluded"
        ),
        None,
    )
    if blocked:
        raise _error(
            409,
            "account_already_invited",
            f"This account already has invitation Delivery {blocked['blocking_delivery_id']}. Review that record before further action.",
        )
    if qualified["qualification_token"] != value.qualification_token:
        raise _error(
            409,
            "qualification_changed",
            "Source information or sending choices changed. Review the current qualification.",
        )
    if not qualified["send_ready"]:
        raise _error(
            422,
            "qualification_not_ready",
            "Repair or explicitly exclude incomplete members, and keep at least one eligible recipient.",
        )
    row = ActivitySendBatch(
        activity_id=UUID(qualified["activity_id"]),
        composition_id=composition_id,
        request_id=value.request_id,
        request_hash=request_hash,
        qualification_snapshot=qualified,
    )
    session.add(row)
    session.flush()
    for index, member in enumerate(qualified["members"]):
        if member["status"] == "eligible":
            session.add(
                ActivityDelivery(
                    send_batch_id=row.id,
                    draft_id=UUID(member["draft_id"]),
                    recipient_snapshot_id=UUID(member["recipient_snapshot_id"]),
                    input_order=index,
                    snapshot=member
                    | {
                        "sender": qualified["sender"],
                        "sending_account_token": qualified["sending_account_token"],
                    },
                )
            )
    session.flush()
    return batch_view(session, row)


def retry_delivery(session, identity, value):
    row = session.scalar(
        select(ActivityDelivery)
        .where(ActivityDelivery.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        row = _get(session, ActivityDelivery, identity)
    if row.attempt != value.expected_attempt or row.state not in {"failed", "queued"}:
        raise _error(
            409,
            "delivery_retry_not_allowed",
            "Refresh the record. Only a definite failure or pending dispatch can be retried.",
        )
    batch = _get(session, ActivitySendBatch, row.send_batch_id)
    previous = blocking_delivery(
        session, batch.activity_id, row.snapshot["identity"], excluding=row.id
    )
    if previous:
        raise _error(
            409,
            "account_already_invited",
            f"This account already has invitation Delivery {previous.id}. Do not retry the old failure.",
        )
    row.state, row.retryable, row.error_code = "queued", False, None
    row.lease_token, row.lease_expires_at = None, None
    session.flush()
    return delivery_view(row)


def resolve_delivery(session, identity, value):
    row = session.scalar(
        select(ActivityDelivery)
        .where(ActivityDelivery.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        row = _get(session, ActivityDelivery, identity)
    if row.attempt != value.expected_attempt or (
        row.state != "unknown" and not sending_expired(row)
    ):
        raise _error(
            409,
            "delivery_not_unknown",
            "Only an unresolved unknown submission can be verified.",
        )
    now = utc_now()
    row.resolution = {
        "outcome": value.outcome,
        "source_note": value.source_note,
        "at": now.isoformat(),
        "attempt": row.attempt,
    }
    row.lease_token, row.lease_expires_at = None, None
    row.state = "sent" if value.outcome == "sent" else "failed"
    row.sent_at = now if value.outcome == "sent" else None
    row.failed_at = now if value.outcome == "not_sent" else None
    row.retryable = value.outcome == "not_sent"
    row.error_code = "submission_verified_not_sent" if row.retryable else None
    session.flush()
    return delivery_view(row)
