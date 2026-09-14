from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, or_

from app.core.database import session_scope
from app.db.models.discover_batch import DiscoverAnalysisBatch
from app.db.models.match import MatchTask, MatchStatus
from app.discovery.service import PUBLICATION_RETRY
from app.workers.celery_app import celery_app


def get_discover_batch_service():
    from app.discovery.runtime import build_discover_batch_service

    return build_discover_batch_service()


@celery_app.task(
    name="find_me_gamer.discover_batch.run",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_discover_batch(batch_id):
    try:
        parsed = UUID(batch_id)
    except (ValueError, TypeError, AttributeError):
        return
    get_discover_batch_service().execute(parsed)


def sweep_discover_batches(*, session_factory=session_scope, dispatch=None, clock=None):
    now = (clock or (lambda: datetime.now(UTC)))()
    with session_factory() as session:
        queued_match = select(MatchTask.id).where(
            MatchTask.status == MatchStatus.QUEUED
        )
        rows = session.scalars(
            select(DiscoverAnalysisBatch)
            .where(
                or_(
                    DiscoverAnalysisBatch.status.in_(["queued", "running"]),
                    DiscoverAnalysisBatch.match_task_id.in_(queued_match),
                ),
                or_(
                    DiscoverAnalysisBatch.dispatched_at.is_(None),
                    DiscoverAnalysisBatch.dispatched_at <= now - PUBLICATION_RETRY,
                ),
            )
            .order_by(DiscoverAnalysisBatch.updated_at)
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
                run_discover_batch.apply_async(args=[str(identifier)], retry=False)
        except Exception:
            pass
    return len(identifiers)


@celery_app.task(name="find_me_gamer.discover_batch.sweep", ignore_result=True)
def sweep_discover_analysis_batches():
    return sweep_discover_batches()
