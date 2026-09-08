"""Short transaction control operations; callers commit and dispatch afterwards."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from app.db.models.discovery import DiscoveryAttempt, DiscoveryBatch, DiscoveryQuery
from app.db.models.jobs import acquire_job_change_lock


class DiscoveryConflict(ValueError):
    pass


def lock_query(session, query_id):
    acquire_job_change_lock(session)
    return session.scalar(
        select(DiscoveryQuery)
        .where(DiscoveryQuery.id == query_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def invalidate_expired(session, query):
    attempts = session.scalars(
        select(DiscoveryAttempt)
        .join(DiscoveryBatch)
        .where(
            DiscoveryBatch.query_id == query.id, DiscoveryAttempt.status == "in_flight"
        )
        .with_for_update()
    ).all()
    live = False
    for attempt in attempts:
        if attempt.lease_expires_at > datetime.now(UTC):
            live = True
            continue
        attempt.status = "outcome_unknown"
        attempt.lease_token = uuid4()
        batch = session.get(DiscoveryBatch, attempt.batch_id)
        batch.status = "outcome_unknown"
        batch.reason = "outcome_unknown"
        query.status = "outcome_unknown"
    session.flush()
    return live


def start_batch(session, query, acknowledge_unknown=False):
    query = lock_query(session, query.id)
    if invalidate_expired(session, query):
        raise DiscoveryConflict("A provider page is still in flight.")
    active = session.scalar(
        select(DiscoveryBatch).where(
            DiscoveryBatch.query_id == query.id,
            DiscoveryBatch.status.in_(["queued", "running"]),
        )
    )
    if active:
        raise DiscoveryConflict("A discovery batch is already active.")
    unknown = session.scalar(
        select(DiscoveryAttempt.id)
        .join(DiscoveryBatch)
        .where(
            DiscoveryBatch.query_id == query.id,
            DiscoveryAttempt.status == "outcome_unknown",
        )
        .limit(1)
    )
    if unknown and not acknowledge_unknown:
        raise DiscoveryConflict(
            "A provider outcome is unknown; acknowledge_unknown is required."
        )
    if unknown:
        for attempt in session.scalars(
            select(DiscoveryAttempt)
            .join(DiscoveryBatch)
            .where(
                DiscoveryBatch.query_id == query.id,
                DiscoveryAttempt.status == "outcome_unknown",
            )
        ):
            attempt.status = "acknowledged_unknown"
            attempt.lease_token = uuid4()
    limits = query.conditions
    if query.result_count >= limits.get("result_limit", 600):
        raise DiscoveryConflict("The query result limit has been reached.")
    if query.requests_reserved >= limits.get(
        "total_request_budget", 120
    ) or query.scanned_reserved >= limits.get("total_scan_budget", 6000):
        raise DiscoveryConflict("The query budget has been exhausted.")
    ordinal = (
        session.scalar(
            select(func.max(DiscoveryBatch.ordinal)).where(
                DiscoveryBatch.query_id == query.id
            )
        )
        or 0
    ) + 1
    batch = DiscoveryBatch(
        query_id=query.id,
        ordinal=ordinal,
        initial_result_count=query.result_count,
        target_count=limits.get("batch_target", 100),
    )
    session.add(batch)
    query.provider_states = {
        platform: (
            {**state, "status": "ready"}
            if state.get("status")
            in ("failed", "partial", "missing_connection", "unavailable")
            else state
        )
        for platform, state in query.provider_states.items()
    }
    query.status = "queued"
    query.stop_requested = False
    session.flush()
    return batch


def stop_query(session, query):
    query = lock_query(session, query.id)
    query.stop_requested = True
    query.status = "stopped"
    for batch in session.scalars(
        select(DiscoveryBatch).where(
            DiscoveryBatch.query_id == query.id, DiscoveryBatch.status == "queued"
        )
    ):
        batch.status = "stopped"
        batch.reason = "stopped"
    session.flush()
