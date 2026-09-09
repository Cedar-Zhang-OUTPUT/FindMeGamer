"""Immutable recipient lists, not final mail or sending authorizations."""

from copy import deepcopy
from collections import Counter
from uuid import uuid4
from sqlalchemy import select, func
from app.api.routes.activity import _error, _get
from app.db.models.activity_outreach import RecipientBatch, RecipientSnapshot
from app.db.models.discovery import Activity
from app.discovery.evaluation_snapshot import digest
from app.discovery.activity_context import activity_context
from app.repositories.activity_preparation import (
    preparation,
    get_selection,
    check_revision,
)
from app.schemas.activity_outreach import RecipientBatchSummary


def get_batch(session, activity_id, batch_id):
    batch = _get(session, RecipientBatch, batch_id)
    if batch.activity_id != activity_id:
        raise _error(
            404,
            "recipient_batch_not_found",
            "Recipient batch not found in this Activity.",
        )
    return batch


def batch_summary(session, batch):
    count = session.scalar(
        select(func.count())
        .select_from(RecipientSnapshot)
        .where(RecipientSnapshot.batch_id == batch.id)
    )
    # Final template/sender/sending eligibility is deliberately not implemented yet.
    return RecipientBatchSummary.model_validate(
        {
            "id": batch.id,
            "activity_id": batch.activity_id,
            "request_id": batch.request_id,
            "status": "frozen",
            "send_ready": False,
            "created_at": batch.created_at,
            "recipient_count": count,
            "needs_repair_count": count,
            "send_ready_count": 0,
        }
    ).model_dump(mode="json")


def batch_detail(session, batch):
    recipients = []
    rows = session.scalars(
        select(RecipientSnapshot)
        .where(RecipientSnapshot.batch_id == batch.id)
        .order_by(RecipientSnapshot.input_order, RecipientSnapshot.id)
    ).all()
    for row in rows:
        current = preparation(
            session, get_selection(session, batch.activity_id, row.selection_id)
        )
        recipients.append(
            {
                "id": str(row.id),
                "selection_id": str(row.selection_id),
                "snapshot": row.snapshot,
                "preparation": current,
                "source_changed": current["context_token"] != row.context_token,
                "current_missing_fields": list(current["missing_fields"]),
            }
        )
    addresses = Counter(
        r["preparation"]["selected_contact"]["email"].casefold()
        for r in recipients
        if r["preparation"]["selected_contact"]
    )
    for recipient in recipients:
        contact = recipient["preparation"]["selected_contact"]
        if contact and addresses[contact["email"].casefold()] > 1:
            recipient["current_missing_fields"].append("duplicate_email")
    return {
        **batch_summary(session, batch),
        "source_snapshot": batch.source_snapshot,
        "recipients": recipients,
    }


def freeze_batch(session, activity_id, value):
    activity = _get(session, Activity, activity_id)
    request_hash = digest(
        {"activity_id": str(activity_id), "request": value.model_dump(mode="json")}
    )
    old = session.scalar(
        select(RecipientBatch).where(RecipientBatch.request_id == value.request_id)
    )
    if old:
        if old.activity_id != activity_id or old.request_hash != request_hash:
            raise _error(
                409,
                "recipient_batch_request_conflict",
                "This request ID already belongs to another frozen list.",
            )
        return batch_detail(session, old)
    prepared = []
    for wanted in value.recipients:
        selection = get_selection(session, activity_id, wanted.selection_id)
        check_revision(selection, wanted.expected_revision)
        current = preparation(session, selection)
        if current["context_token"] != wanted.context_token:
            raise _error(
                409,
                "preparation_context_changed",
                "Read current recipient information before freezing it.",
            )
        if not current["freeze_ready"]:
            raise _error(
                422,
                "recipient_not_ready",
                "Only active explicitly selected members can enter a preparation batch.",
            )
        prepared.append(current)
    batch = RecipientBatch(
        id=uuid4(),
        activity_id=activity_id,
        request_id=value.request_id,
        request_hash=request_hash,
        source_snapshot=activity_context(activity),
    )
    session.add(batch)
    session.flush()
    for index, current in enumerate(prepared):
        snapshot = deepcopy(current)
        snapshot["contact_options"] = []  # freeze only the explicitly chosen address
        session.add(
            RecipientSnapshot(
                id=uuid4(),
                batch_id=batch.id,
                selection_id=current["id"],
                context_token=current["context_token"],
                snapshot=snapshot,
                input_order=index,
            )
        )
    session.flush()
    return batch_detail(session, batch)
