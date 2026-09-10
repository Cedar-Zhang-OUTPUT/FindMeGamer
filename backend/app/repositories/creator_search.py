"""Read views and short serialized transitions for one-click searches."""

from sqlalchemy import select
from app.core.idempotency import utc_now
from app.db.models.creator_search import CreatorSearch, CreatorSearchUnit
from app.db.models.discovery import DiscoveryQuery
from app.db.models.discovery_evaluation import EvaluationRun
from app.db.models.jobs import acquire_job_change_lock
from app.repositories.discovery_evaluation import items_for, steps_for, expired

ACTIVE = {"queued", "running", "stopping"}


def lock_search(session, identity):
    acquire_job_change_lock(session)
    return session.scalar(
        select(CreatorSearch)
        .where(CreatorSearch.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def units_for(session, identity):
    return list(
        session.scalars(
            select(CreatorSearchUnit)
            .where(CreatorSearchUnit.search_id == identity)
            .order_by(CreatorSearchUnit.ordinal)
        )
    )


def search_expired(task):
    return (
        task.status in ACTIVE
        and task.lease_token is not None
        and task.lease_expires_at is not None
        and task.lease_expires_at <= utc_now()
    )


def search_view(session, task):
    units = units_for(session, task.id)
    query = session.get(DiscoveryQuery, task.query_id) if task.query_id else None
    run = session.get(EvaluationRun, task.evaluation_id) if task.evaluation_id else None
    items = items_for(session, run.id) if run else []
    steps = steps_for(session, run.id) if run else []
    unknown = (
        search_expired(task)
        or any(
            expired(s) or s.error_code == "evaluation_outcome_unknown" for s in steps
        )
        or (
            task.error_code == "search_outcome_unknown" and not task.acknowledge_unknown
        )
    )
    failed = any(
        u.profile_status == "failed" or u.email_status == "failed" for u in units
    ) or any(s.status == "failed" or expired(s) for s in steps)
    stage = (
        run.stage
        if task.stage in {"screening", "deep_match", "ranking"}
        and run
        and run.stage in {"screening", "deep_match", "ranking"}
        else task.stage
    )
    return {
        **{
            key: getattr(task, key)
            for key in (
                "id",
                "activity_id",
                "plan_id",
                "query_id",
                "evaluation_id",
                "parent_search_id",
                "stop_requested",
                "created_at",
                "updated_at",
            )
        },
        "status": "failed" if unknown else task.status,
        "stage": stage,
        "error_code": "search_outcome_unknown" if unknown else task.error_code,
        "outcome_unknown": unknown,
        "retryable": unknown
        or task.status == "stopped"
        or task.status == "failed"
        or (task.status == "partial" and failed),
        "counts": {
            "discovered": (
                len(units)
                if task.scope_frozen
                else max(
                    0,
                    (query.result_count if query else 0)
                    - len(task.excluded_candidate_ids or []),
                )
            ),
            "profile_ready": sum(
                u.profile_status in {"ready", "reused"} for u in units
            ),
            "profile_reused": sum(u.profile_status == "reused" for u in units),
            "profile_failed": sum(u.profile_status == "failed" for u in units),
            "email_available": sum(u.email_status == "available" for u in units),
            "email_missing": sum(u.email_status == "missing" for u in units),
            "email_failed": sum(u.email_status == "failed" for u in units),
            "evaluated": sum(i.screening_selected is not None for i in items),
            "matched": sum(i.match_brief is not None for i in items),
        },
    }


def unit_view(unit):
    return {
        key: getattr(unit, key)
        for key in (
            "candidate_id",
            "creator_id",
            "platform",
            "profile_status",
            "email_status",
            "analysis_job_id",
            "profile_error_code",
            "email_error_code",
        )
    }
