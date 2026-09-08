"""Same-list projection: no GET creates activity, tracking, reply or delivery."""

from sqlalchemy import select, or_
from app.api.routes.activity import _get, _error
from app.db.models.discovery import Activity
from app.db.models.profiles import CreatorProfile
from app.db.models.activity_outreach import (
    ActivitySelection,
    RecipientSnapshot,
    RecipientBatch,
)
from app.db.models.activity_sending import ActivitySendBatch, ActivityDelivery
from app.db.models.activity_collaboration import ActivityCollaboration, ActivityResponse
from app.repositories.activity_preparation import (
    get_selection,
    identity,
    saved_identity,
)
from app.repositories.creator_library import effective_fields
from app.repositories.activity_sending import delivery_view
from app.schemas.activity_collaboration import ActivityInvitation


def invitation(session, row):
    activity = _get(session, Activity, row.activity_id)
    creator = _get(session, CreatorProfile, row.creator_id)
    tracking = session.get(ActivityCollaboration, row.id)
    recipients = session.execute(
        select(RecipientSnapshot, RecipientBatch)
        .join(RecipientBatch, RecipientSnapshot.batch_id == RecipientBatch.id)
        .where(RecipientSnapshot.selection_id == row.id)
        .order_by(
            RecipientBatch.created_at, RecipientBatch.id, RecipientSnapshot.input_order
        )
    ).all()
    memberships = [
        dict(
            recipient_batch_id=batch.id,
            recipient_snapshot_id=member.id,
            input_order=member.input_order,
            created_at=batch.created_at,
            snapshot=member.snapshot,
        )
        for member, batch in recipients
    ]
    recipient_ids = {str(member.id) for member, _ in recipients}
    deliveries = (
        session.scalars(
            select(ActivityDelivery).where(
                ActivityDelivery.recipient_snapshot_id.in_(
                    [member.id for member, _ in recipients]
                )
            )
        ).all()
        if recipients
        else []
    )
    delivery_map = {
        (str(d.send_batch_id), str(d.recipient_snapshot_id)): d for d in deliveries
    }
    history = []
    for batch in session.scalars(
        select(ActivitySendBatch)
        .where(ActivitySendBatch.activity_id == row.activity_id)
        .order_by(ActivitySendBatch.created_at.desc(), ActivitySendBatch.id.desc())
    ):
        for member in batch.qualification_snapshot.get("members", []):
            recipient_id = member["recipient_snapshot_id"]
            if recipient_id not in recipient_ids:
                continue
            delivery = delivery_map.get((str(batch.id), recipient_id))
            history.append(
                dict(
                    send_batch_id=batch.id,
                    composition_id=batch.composition_id,
                    draft_id=member["draft_id"],
                    recipient_snapshot_id=recipient_id,
                    created_at=batch.created_at,
                    qualification_status=member["status"],
                    exclusion_reason=member["exclusion_reason"],
                    delivery=delivery_view(delivery) if delivery else None,
                )
            )
    actual_deliveries = [h["delivery"] for h in history if h["delivery"]]
    # B allows explicitly retrying an older definite failure after a newer failure.
    # An effective invitation must not be masked by that newer failed batch.
    effective = next(
        (
            d
            for d in actual_deliveries
            if d["state"] in {"queued", "sending", "sent", "unknown"}
        ),
        actual_deliveries[0] if actual_deliveries else None,
    )
    sending = effective["state"] if effective else "not_sent"
    sent_dates = [
        d["sent_at"] for d in actual_deliveries if d["state"] == "sent" and d["sent_at"]
    ]
    responses = [
        dict(
            id=r.id,
            revision=r.revision,
            outcome=r.outcome,
            source_note=r.source_note,
            responded_at=r.responded_at,
            recorded_at=r.recorded_at,
        )
        for r in session.scalars(
            select(ActivityResponse)
            .where(ActivityResponse.selection_id == row.id)
            .order_by(ActivityResponse.revision.desc())
        )
    ]
    invitation_state = (
        responses[0]["outcome"]
        if responses
        else ("awaiting_response" if sent_dates else "not_invited")
    )
    name = (
        effective_fields(creator).name
        if identity(creator) == saved_identity(row)
        else None
    )
    if not name and memberships:
        name = memberships[-1]["snapshot"].get("name")
    return ActivityInvitation.model_validate(
        dict(
            selection_id=row.id,
            creator_id=row.creator_id,
            activity_id=activity.id,
            activity_name=activity.name,
            selected=row.active,
            identity=saved_identity(row),
            display_name=name,
            revision=tracking.revision if tracking else 0,
            sending_state=sending,
            invitation_state=invitation_state,
            follow_up_state=tracking.follow_up_state if tracking else "not_followed_up",
            cooperation_state=tracking.cooperation_state if tracking else "not_started",
            notes=tracking.notes if tracking else "",
            invited_at=max(sent_dates) if sent_dates else None,
            responses=responses,
            memberships=memberships,
            send_history=history,
        )
    ).model_dump(mode="json")


def list_invitations(
    session,
    *,
    activity_id=None,
    creator_id=None,
    sending_state=None,
    invitation_state=None,
    follow_up_state=None,
    limit=50,
    offset=0,
):
    statement = select(ActivitySelection).where(
        or_(
            ActivitySelection.active.is_(True),
            select(RecipientSnapshot.id)
            .where(RecipientSnapshot.selection_id == ActivitySelection.id)
            .exists(),
            select(ActivityCollaboration.selection_id)
            .where(ActivityCollaboration.selection_id == ActivitySelection.id)
            .exists(),
        )
    )
    if activity_id is not None:
        statement = statement.where(ActivitySelection.activity_id == activity_id)
    if creator_id is not None:
        statement = statement.where(
            or_(
                ActivitySelection.creator_id == creator_id,
                select(RecipientSnapshot.id)
                .where(
                    RecipientSnapshot.selection_id == ActivitySelection.id,
                    RecipientSnapshot.snapshot["creator_id"].astext == str(creator_id),
                )
                .exists(),
            )
        )
    items = []
    for row in session.scalars(
        statement.order_by(ActivitySelection.created_at, ActivitySelection.id)
    ):
        item = invitation(session, row)
        if all(
            wanted is None or item[field] == wanted
            for field, wanted in (
                ("sending_state", sending_state),
                ("invitation_state", invitation_state),
                ("follow_up_state", follow_up_state),
            )
        ):
            items.append(item)
    return dict(
        items=items[offset : offset + limit],
        total=len(items),
        limit=limit,
        offset=offset,
    )


def update_tracking(session, activity_id, selection_id, value, *, response=False):
    row = get_selection(session, activity_id, selection_id)
    tracking = session.get(ActivityCollaboration, row.id)
    if value.expected_revision != (tracking.revision if tracking else 0):
        raise _error(
            409,
            "collaboration_revision_conflict",
            "This Activity relationship changed. Refresh before editing.",
        )
    if tracking is None:
        tracking = ActivityCollaboration(selection_id=row.id, revision=0)
        session.add(tracking)
        session.flush()
    tracking.revision += 1
    if response:
        session.add(
            ActivityResponse(
                selection_id=row.id,
                revision=tracking.revision,
                outcome=value.outcome,
                source_note=value.source_note,
                responded_at=value.responded_at,
            )
        )
    else:
        for field, changed in value.model_dump(exclude_unset=True).items():
            if field != "expected_revision":
                setattr(tracking, field, changed)
    session.flush()
    return invitation(session, row)
