"""Default choices are durable once, not a renderer mount side effect."""

from sqlalchemy import select

from app.db.models.discovery import Activity
from app.db.models.activity_outreach import ActivitySelection
from app.repositories.discovery import start_batch
from tests.integration.test_discovery_union import creator
from tests.integration.test_discovery_runtime import make_query, runtime, factories


def test_first_batch_selects_once_and_append_preserves_cancellation(session):
    for account in ("1234567", "2345678", "3456789"):
        creator(session, "instagram", account)
    query = make_query(
        session, providers=[{"platform": "instagram", "query": "game"}], batch_target=1
    )
    batch = start_batch(session, query)
    session.commit()
    kwargs = factories(
        session, lambda req: (_ for _ in ()).throw(AssertionError("No live API"))
    )
    runtime()(batch.id, **kwargs)
    rows = session.scalars(
        select(ActivitySelection).where(
            ActivitySelection.activity_id == query.activity_id
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].active
    assert session.get(Activity, query.activity_id).initial_selection_initialized
    rows[0].active = False
    rows[0].revision += 1
    session.commit()
    runtime()(batch.id, **kwargs)
    appended = start_batch(session, query)
    session.commit()
    runtime()(appended.id, **kwargs)
    session.expire_all()
    rows = session.scalars(
        select(ActivitySelection).where(
            ActivitySelection.activity_id == query.activity_id
        )
    ).all()
    assert len(rows) == 1
    assert not rows[0].active
    assert rows[0].revision == 1
    assert query.result_count == 2


def test_expired_first_batch_initializes_before_acknowledged_append(session):
    from datetime import UTC, datetime, timedelta
    from app.db.models.discovery import DiscoveryAttempt
    from app.workers.discovery_tasks import reserve
    from app.repositories.initial_selection import initialize_first_batch

    creator(session, "youtube", "UCaaaaaaa")
    query = make_query(session)
    first = start_batch(session, query)
    session.commit()
    reserved = reserve(session, first.id)
    session.get(DiscoveryAttempt, reserved[0]).lease_expires_at = datetime.now(
        UTC
    ) - timedelta(seconds=1)
    session.commit()
    second = start_batch(session, query, acknowledge_unknown=True)
    session.commit()
    assert session.get(Activity, query.activity_id).initial_selection_initialized
    rows = session.scalars(
        select(ActivitySelection).where(
            ActivitySelection.activity_id == query.activity_id
        )
    ).all()
    assert len(rows) == 1
    rows[0].active = False
    session.commit()
    from tests.integration.test_discovery_runtime import page

    runtime()(second.id, **factories(session, lambda req: page(req, ["UCbbbbbbb"])))
    initialize_first_batch(session, first.id)
    session.flush()
    rows = session.scalars(
        select(ActivitySelection).where(
            ActivitySelection.activity_id == query.activity_id
        )
    ).all()
    assert len(rows) == 1 and not rows[0].active


def test_empty_stopped_first_batch_consumes_default_once(session):
    from app.repositories.discovery import stop_query
    from app.db.models.discovery import DiscoveryQuery

    query = make_query(session)
    start_batch(session, query)
    stop_query(session, query)
    session.commit()
    assert session.get(Activity, query.activity_id).initial_selection_initialized
    creator(session, "instagram", "1234567")
    later = DiscoveryQuery(
        activity_id=query.activity_id,
        conditions={"providers": [{"platform": "instagram", "query": "game"}]},
    )
    session.add(later)
    session.flush()
    batch = start_batch(session, later)
    session.commit()
    runtime()(batch.id, **factories(session, lambda req: None))
    assert later.result_count == 1
    assert not session.scalars(
        select(ActivitySelection).where(
            ActivitySelection.activity_id == query.activity_id
        )
    ).all()
