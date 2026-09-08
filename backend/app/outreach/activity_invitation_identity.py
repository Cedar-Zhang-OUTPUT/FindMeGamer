"""Normal invitations are unique per Activity/platform account, not per mutable email."""

from sqlalchemy import select
from app.db.models.activity_sending import ActivitySendBatch, ActivityDelivery


def blocking_delivery(session, activity_id, identity, *, excluding=None):
    statement = (
        select(ActivityDelivery)
        .join(ActivitySendBatch, ActivityDelivery.send_batch_id == ActivitySendBatch.id)
        .where(
            ActivitySendBatch.activity_id == activity_id,
            ActivityDelivery.state.in_(["queued", "sending", "sent", "unknown"]),
            ActivityDelivery.snapshot["identity"]["platform"].astext
            == identity["platform"],
            ActivityDelivery.snapshot["identity"]["account_id"].astext
            == identity["account_id"],
        )
    )
    if excluding is not None:
        statement = statement.where(ActivityDelivery.id != excluding)
    return session.scalar(
        statement.order_by(ActivityDelivery.created_at, ActivityDelivery.id).limit(1)
    )
