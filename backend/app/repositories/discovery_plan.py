from sqlalchemy import select

from app.core.idempotency import utc_now
from app.db.models.discovery_plan import DiscoveryPlan
from app.db.models.jobs import acquire_job_change_lock


def lock_plan(session, plan_id):
    acquire_job_change_lock(session)
    return session.scalar(
        select(DiscoveryPlan)
        .where(DiscoveryPlan.id == plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def expired(plan):
    return (
        plan.status == "running"
        and plan.lease_expires_at is not None
        and plan.lease_expires_at <= utc_now()
    )


def plan_view(plan):
    stale = expired(plan)
    return {
        **{
            k: getattr(plan, k)
            for k in (
                "id",
                "activity_id",
                "conditions",
                "source_snapshot",
                "output",
                "attempt",
                "model",
                "query_id",
                "created_at",
            )
        },
        "status": "failed" if stale else plan.status,
        "error_code": "planning_outcome_unknown" if stale else plan.error_code,
        "retryable": True if stale else plan.retryable,
    }
