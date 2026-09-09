"""Run under the discovery change lock; no preparation or sending side effects."""

from sqlalchemy import select
from app.db.models.discovery import (
    Activity,
    DiscoveryQuery,
    DiscoveryCandidate,
    DiscoveryBatch,
)
from app.db.models.activity_outreach import ActivitySelection
from app.db.models.profiles import CreatorProfile
from app.core.creator_identity import creator_account_key


def initialize_first_batch(session, batch_id):
    batch = session.get(DiscoveryBatch, batch_id)
    if (
        batch is None
        or batch.ordinal != 1
        or batch.status not in ("completed", "stopped", "outcome_unknown")
    ):
        return
    query = session.get(DiscoveryQuery, batch.query_id)
    activity = session.get(Activity, query.activity_id)
    if activity.initial_selection_initialized:
        return
    first_query = session.scalar(
        select(DiscoveryQuery.id)
        .where(DiscoveryQuery.activity_id == activity.id)
        .order_by(DiscoveryQuery.created_at, DiscoveryQuery.id)
        .limit(1)
    )
    if first_query != query.id:
        return
    existing = set(
        session.execute(
            select(ActivitySelection.platform, ActivitySelection.account_id).where(
                ActivitySelection.activity_id == activity.id
            )
        ).all()
    )
    for candidate in session.scalars(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.query_id == query.id)
        .order_by(DiscoveryCandidate.ordinal)
    ):
        if (candidate.platform, candidate.account_id) in existing:
            continue
        creator = session.get(CreatorProfile, candidate.creator_id)
        if (
            creator.platform != candidate.platform
            or creator_account_key(creator) != candidate.account_id
            or creator.identity_revision != candidate.identity_revision
        ):
            continue
        session.add(
            ActivitySelection(
                activity_id=activity.id,
                creator_id=creator.id,
                candidate_id=candidate.id,
                platform=candidate.platform,
                account_id=candidate.account_id,
                identity_revision=candidate.identity_revision,
            )
        )
    activity.initial_selection_initialized = True
    session.flush()
