"""Durable page execution: real DB, only the provider network is a fixture."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select


def runtime():
    from app.workers.discovery_tasks import run_discovery_batch

    return run_discovery_batch


def make_query(session, **conditions):
    from app.db.models.discovery import Activity, DiscoveryQuery
    from app.db.models.profiles import GameProfile

    game = GameProfile(canonical_url="https://example.test/game", sort_name="Game")
    session.add(game)
    session.flush()
    activity = Activity(
        game_id=game.id, name="Find creators", source_snapshot={"game": "frozen"}
    )
    session.add(activity)
    session.flush()
    query = DiscoveryQuery(
        activity_id=activity.id,
        source_snapshot=activity.source_snapshot,
        conditions={
            "providers": [{"platform": "youtube", "query": "game", "page_size": 2}],
            "filters": {},
            "batch_target": 100,
            "result_limit": 600,
            "batch_request_budget": 20,
            "batch_scan_budget": 1000,
            "total_request_budget": 120,
            "total_scan_budget": 6000,
            **conditions,
        },
    )
    session.add(query)
    session.flush()
    return query


def page(request, ids, more=False):
    from app.schemas.discovery import DiscoveredAccount, DiscoveryPage, DiscoveryCursor

    return DiscoveryPage(
        platform=request.platform,
        status="more" if more else "complete",
        accounts=[
            DiscoveredAccount(
                platform=request.platform,
                account_id=key,
                profile_url=f"https://www.youtube.com/channel/{key}",
                display_name=key,
                collected_at=datetime.now(UTC),
            )
            for key in ids
        ],
        next_cursor=(
            DiscoveryCursor(token="next", query_fingerprint=request.fingerprint())
            if more
            else None
        ),
        requests_used=2,
        provider_items_received=len(ids),
        coverage="search_index",
    )


def factories(session, callback):
    @contextmanager
    def session_factory():
        yield session

    class Gateway:
        def discover(self, request):
            # Reservation must already be committed before provider I/O.
            assert not session.in_transaction()
            return callback(request)

    @contextmanager
    def gateway_factory(platform):
        yield Gateway()

    return dict(session_factory=session_factory, gateway_factory=gateway_factory)


def test_atomic_dedup_order_and_continue_preserve_prior_results(session):
    from app.db.models.discovery import DiscoveryCandidate, DiscoveryAttempt
    from app.repositories.discovery import start_batch

    query = make_query(session, batch_target=1)
    batch = start_batch(session, query)
    session.commit()
    runtime()(
        batch.id,
        **factories(session, lambda req: page(req, ["UCaaaaaaa", "UCbbbbbbb"], True)),
    )
    assert query.result_count == 2
    assert batch.status == "completed"
    batch2 = start_batch(session, query)
    session.commit()
    runtime()(
        batch2.id,
        **factories(session, lambda req: page(req, ["UCaaaaaaa", "UCccccccc"])),
    )
    candidates = session.scalars(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.query_id == query.id)
        .order_by(DiscoveryCandidate.ordinal)
    ).all()
    assert [c.account_id for c in candidates] == ["UCaaaaaaa", "UCbbbbbbb", "UCccccccc"]
    assert all(not c.selected for c in candidates)
    assert query.result_count == 3
    assert len(session.scalars(select(DiscoveryAttempt)).all()) == 2


def test_duplicate_live_delivery_and_stop_inflight_never_start_next_page(session):
    from app.repositories.discovery import start_batch, stop_query, DiscoveryConflict

    query = make_query(session)
    batch = start_batch(session, query)
    session.commit()
    calls = []

    def callback(req):
        calls.append(req)
        runtime()(
            batch.id, **factories(session, lambda r: pytest.fail("duplicate paid call"))
        )
        with pytest.raises(DiscoveryConflict):
            start_batch(session, query)
        session.rollback()
        stop_query(session, query)
        session.commit()
        return page(req, ["UCaaaaaaa"], True)

    runtime()(batch.id, **factories(session, callback))
    assert query.status == "stopped"
    assert query.result_count == 1
    assert len(calls) == 1


def test_unknown_attempt_requires_acknowledgement_and_stale_response_is_ignored(
    session,
):
    from app.db.models.discovery import DiscoveryAttempt
    from app.repositories.discovery import start_batch, DiscoveryConflict

    query = make_query(session)
    batch = start_batch(session, query)
    session.commit()

    def callback(req):
        attempt = session.scalar(
            select(DiscoveryAttempt).where(DiscoveryAttempt.batch_id == batch.id)
        )
        attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        runtime()(
            batch.id,
            **factories(session, lambda r: pytest.fail("unknown automatic retry")),
        )
        with pytest.raises(DiscoveryConflict):
            start_batch(session, query)
        session.rollback()
        next_batch = start_batch(session, query, acknowledge_unknown=True)
        session.commit()
        assert next_batch.id != batch.id
        return page(req, ["UCaaaaaaa"])

    runtime()(batch.id, **factories(session, callback))
    assert query.result_count == 0
    assert query.requests_reserved == 2


def test_query_cap_and_budget_are_hard_limits(session):
    from app.repositories.discovery import start_batch

    query = make_query(session, result_limit=1)
    batch = start_batch(session, query)
    session.commit()
    runtime()(
        batch.id,
        **factories(session, lambda req: page(req, ["UCaaaaaaa", "UCbbbbbbb"], True)),
    )
    assert query.result_count == 1
    assert query.status == "completed"
    query2 = make_query(session, batch_request_budget=1)
    batch2 = start_batch(session, query2)
    session.commit()
    runtime()(
        batch2.id, **factories(session, lambda req: pytest.fail("over-budget call"))
    )
    assert query2.requests_reserved == 0
    assert batch2.reason == "budget_exhausted"


def test_unknown_exception_preserves_results_and_pauses_without_retry(session):
    from app.repositories.discovery import start_batch

    query = make_query(session)
    batch = start_batch(session, query)
    session.commit()
    calls = []

    def callback(req):
        calls.append(req)
        if len(calls) == 1:
            return page(req, ["UCaaaaaaa"], True)
        raise RuntimeError("secret provider response must never be stored")

    runtime()(batch.id, **factories(session, callback))
    assert query.result_count == 1
    assert query.status == "outcome_unknown"
    assert len(calls) == 2


def test_expired_response_cannot_publish_without_live_lease(session):
    from app.db.models.discovery import DiscoveryAttempt
    from app.repositories.discovery import start_batch

    query = make_query(session)
    batch = start_batch(session, query)
    session.commit()

    def callback(req):
        attempt = session.scalar(
            select(DiscoveryAttempt).where(DiscoveryAttempt.batch_id == batch.id)
        )
        attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        return page(req, ["UCaaaaaaa"])

    runtime()(batch.id, **factories(session, callback))
    assert query.result_count == 0
    assert query.status == "outcome_unknown"


def test_missing_unsupported_and_partial_are_explicit_and_never_retried(session):
    from app.repositories.discovery import start_batch
    from app.workers.discovery_tasks import MissingConnection
    from app.schemas.discovery import DiscoveryIssue

    query = make_query(
        session,
        providers=[
            {"platform": "twitch", "query": "game"},
            {"platform": "x", "query": "game", "page_size": 10},
            {"platform": "youtube", "query": "game", "page_size": 2},
        ],
    )
    batch = start_batch(session, query)
    session.commit()

    def callback(req):
        if req.platform == "x":
            raise MissingConnection()
        result = page(req, ["UCaaaaaaa"])
        result.status = "partial"
        result.issues = [DiscoveryIssue(code="partial_data")]
        return result

    runtime()(batch.id, **factories(session, callback))
    assert query.result_count == 1
    assert query.requests_reserved == 2
    assert query.provider_states["twitch"]["status"] == "not_supported"
    assert query.provider_states["x"]["status"] == "missing_connection"
    assert query.provider_states["youtube"]["status"] == "partial"
    assert query.status == "paused"
    assert batch.reason == "source_partial"


def test_import_failure_rolls_back_whole_page_and_becomes_unknown(session):
    from app.repositories.discovery import start_batch
    from app.db.models.discovery import DiscoveryCandidate

    query = make_query(session)
    batch = start_batch(session, query)
    session.commit()

    def callback(req):
        result = page(req, ["UCaaaaaaa", "invalid"])
        return result

    runtime()(batch.id, **factories(session, callback))
    assert query.result_count == 0
    assert query.status == "outcome_unknown"
    assert (
        session.scalar(
            select(DiscoveryCandidate.id).where(DiscoveryCandidate.query_id == query.id)
        )
        is None
    )


def test_committed_reservation_coordinates_independent_worker_and_stop_sessions(
    migrated_database, database_engine
):
    from sqlalchemy import delete
    from sqlalchemy.orm import sessionmaker
    from app.db.models.discovery import (
        Activity,
        DiscoveryAttempt,
        DiscoveryBatch,
        DiscoveryCandidate,
        DiscoveryQuery,
    )
    from app.db.models.profiles import CreatorProfile, GameProfile
    from app.repositories.discovery import start_batch, stop_query, DiscoveryConflict

    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    account_id = "UC" + uuid4().hex
    with factory() as setup:
        query = make_query(setup)
        batch = start_batch(setup, query)
        query_id, batch_id, activity_id = query.id, batch.id, query.activity_id
        game_id = setup.get(Activity, activity_id).game_id
        setup.commit()

    @contextmanager
    def sessions():
        with factory() as session:
            yield session

    class Gateway:
        def discover(self, request):
            with factory() as observer:
                assert observer.get(DiscoveryQuery, query_id).requests_reserved == 2
                assert (
                    observer.scalar(
                        select(DiscoveryAttempt.status).where(
                            DiscoveryAttempt.batch_id == batch_id
                        )
                    )
                    == "in_flight"
                )
            runtime()(batch_id, session_factory=sessions, gateway_factory=forbidden)
            with factory() as control:
                current = control.get(DiscoveryQuery, query_id)
                with pytest.raises(DiscoveryConflict):
                    start_batch(control, current)
                control.rollback()
                stop_query(control, current)
                control.commit()
            return page(request, [account_id], True)

    @contextmanager
    def forbidden(platform):
        pytest.fail("second worker performed duplicate I/O")
        yield

    @contextmanager
    def gateways(platform):
        yield Gateway()

    try:
        runtime()(batch_id, session_factory=sessions, gateway_factory=gateways)
        with factory() as observer:
            current = observer.get(DiscoveryQuery, query_id)
            assert (current.status, current.result_count) == ("stopped", 1)
            assert (
                observer.scalar(
                    select(DiscoveryCandidate.selected).where(
                        DiscoveryCandidate.query_id == query_id
                    )
                )
                is False
            )
    finally:
        with factory.begin() as cleanup:
            cleanup.execute(
                delete(DiscoveryCandidate).where(
                    DiscoveryCandidate.query_id == query_id
                )
            )
            cleanup.execute(
                delete(DiscoveryAttempt).where(DiscoveryAttempt.batch_id == batch_id)
            )
            cleanup.execute(
                delete(DiscoveryBatch).where(DiscoveryBatch.query_id == query_id)
            )
            cleanup.execute(delete(DiscoveryQuery).where(DiscoveryQuery.id == query_id))
            cleanup.execute(delete(Activity).where(Activity.id == activity_id))
            cleanup.execute(delete(GameProfile).where(GameProfile.id == game_id))
            cleanup.execute(
                delete(CreatorProfile).where(
                    CreatorProfile.platform_account_id == account_id
                )
            )


def test_explicit_continue_retries_failed_page_with_last_committed_cursor(session):
    from app.repositories.discovery import start_batch
    from app.schemas.discovery import DiscoveryPage, DiscoveryIssue

    query = make_query(session)
    batch = start_batch(session, query)
    session.commit()

    def callback(req):
        if req.cursor is None:
            return page(req, ["UCaaaaaaa"], True)
        return DiscoveryPage(
            platform="youtube",
            status="failed",
            coverage="search_index",
            requests_used=1,
            issues=[DiscoveryIssue(code="forbidden")],
        )

    runtime()(batch.id, **factories(session, callback))
    assert query.result_count == 1
    assert query.status == "paused"
    assert batch.reason == "provider_failed"
    batch2 = start_batch(session, query)
    session.commit()

    def resumed(req):
        assert req.cursor.token == "next"
        return page(req, ["UCbbbbbbb"])

    runtime()(batch2.id, **factories(session, resumed))
    assert query.result_count == 2
    assert query.provider_states["youtube"]["coverage"] == "search_index"


@pytest.mark.parametrize(
    "platform,reason,status",
    [
        ("x", "source_unavailable", "paused"),
        ("twitch", "library_only", "completed"),
    ],
)
def test_unavailable_sources_do_not_report_provider_exhaustion(
    session, platform, reason, status
):
    from app.repositories.discovery import start_batch
    from app.workers.discovery_tasks import MissingConnection

    query = make_query(
        session, providers=[{"platform": platform, "query": "game", "page_size": 10}]
    )
    batch = start_batch(session, query)
    session.commit()

    def callback(request):
        raise MissingConnection()

    runtime()(batch.id, **factories(session, callback))
    assert query.status == status
    assert batch.reason == reason


def test_production_gateway_uses_encrypted_settings_without_usage_probe(
    session, monkeypatch
):
    import httpx
    from types import SimpleNamespace
    from app.core.crypto import SecretCipher
    from app.db.models.settings import ServiceSecret
    from app.schemas.discovery import DiscoveryRequest
    from app.workers import discovery_tasks
    from app.integrations import (
        x_discovery,
    )  # Load annotations before replacing transport.

    cipher = SecretCipher(bytes(range(32)))
    encrypted = cipher.encrypt("fixture-token")
    session.add(
        ServiceSecret(
            service="x",
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            last_test_succeeded=False,
        )
    )
    session.commit()

    @contextmanager
    def credentials():
        yield session
        session.commit()

    monkeypatch.setattr(discovery_tasks, "session_scope", credentials)
    monkeypatch.setattr(
        discovery_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            master_key_file="fixture-unused", x_api_base_url="https://fixture.invalid/2"
        ),
    )
    monkeypatch.setattr(SecretCipher, "from_file", lambda path: cipher)
    requests = []

    def respond(request):
        assert not session.in_transaction()
        requests.append(request)
        return httpx.Response(200, json={"meta": {"result_count": 0}})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    with discovery_tasks.production_gateway("x") as gateway:
        result = gateway.discover(
            DiscoveryRequest(platform="x", query="game", page_size=10)
        )
    assert result.status == "complete"
    assert [str(request.url).split("?")[0] for request in requests] == [
        "https://fixture.invalid/2/tweets/search/recent"
    ]
    assert requests[0].headers["Authorization"] == "Bearer fixture-token"
