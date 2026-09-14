from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, or_

from app.core.database import session_scope
from app.db.models.discover import DiscoverJob
from app.workers.celery_app import celery_app


def get_discover_service():
    from app.discovery.runtime import build_discover_service

    return build_discover_service()


@celery_app.task(
    name="find_me_gamer.discover.run",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_discover(job_id):
    try:
        parsed = UUID(job_id)
    except (ValueError, TypeError, AttributeError):
        return
    get_discover_service().execute(parsed)


def sweep_discover(*, session_factory=session_scope, dispatch=None, clock=None):
    now = (clock or (lambda: datetime.now(UTC)))()
    with session_factory() as session:
        rows = session.scalars(
            select(DiscoverJob)
            .where(
                DiscoverJob.status.in_(["queued", "running"]),
                or_(DiscoverJob.lease_until.is_(None), DiscoverJob.lease_until <= now),
                or_(
                    DiscoverJob.dispatched_at.is_(None),
                    DiscoverJob.dispatched_at <= now - timedelta(minutes=2),
                ),
            )
            .order_by(DiscoverJob.updated_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        ).all()
        identifiers = [row.id for row in rows]
        for row in rows:
            row.dispatched_at = now
        session.commit()
    for identifier in identifiers:
        try:
            if dispatch:
                dispatch(str(identifier))
            else:
                run_discover.apply_async(args=[str(identifier)], retry=False)
        except Exception:
            # The publication reservation expires and Beat retries this same ID.
            pass
    return len(identifiers)


@celery_app.task(name="find_me_gamer.discover.sweep", ignore_result=True)
def sweep_discover_jobs():
    return sweep_discover()
