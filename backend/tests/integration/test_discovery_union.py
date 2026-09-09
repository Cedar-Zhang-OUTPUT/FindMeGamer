"""Library and live metadata share candidates without sharing source availability."""

import pytest
from sqlalchemy import select

from app.db.models.discovery import DiscoveryCandidate
from app.db.models.profiles import CreatorProfile
from app.repositories.collection_settings import update_collection
from app.repositories.discovery import start_batch
from tests.integration.test_discovery_runtime import (
    make_query,
    page,
    factories,
    runtime,
)


def creator(session, platform, account_id):
    row = CreatorProfile(
        platform=platform,
        platform_account_id=account_id,
        youtube_channel_id=account_id if platform == "youtube" else None,
        canonical_url=f"https://example.test/{platform}/{account_id}",
        sort_name=account_id or "URL-only Creator",
        current_facts={"title": account_id},
        identity_revision=0,
    )
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize("platform", ["youtube", "x", "twitch", "instagram"])
def test_disabled_or_unsupported_platform_still_searches_library(session, platform):
    saved = creator(
        session, platform, "UCsaved12" if platform == "youtube" else "123456789"
    )
    update_collection(session, platform, False)
    query = make_query(
        session, providers=[{"platform": platform, "query": "game", "page_size": 10}]
    )
    batch = start_batch(session, query)
    session.commit()
    runtime()(
        batch.id,
        **factories(session, lambda req: pytest.fail("No live collection allowed")),
    )
    candidates = session.scalars(
        select(DiscoveryCandidate).where(DiscoveryCandidate.query_id == query.id)
    ).all()
    assert [c.creator_id for c in candidates] == [saved.id]
    assert candidates[0].filter_notes["discovery_sources"] == ["library"]
    assert query.provider_states[platform]["library"]["status"] == "complete"
    assert query.requests_reserved == 0


def test_library_and_live_merge_same_account_and_keep_other_results(session):
    saved = creator(session, "youtube", "UCaaaaaaa")
    query = make_query(session)
    batch = start_batch(session, query)
    session.commit()
    runtime()(
        batch.id,
        **factories(session, lambda req: page(req, ["UCaaaaaaa", "UCbbbbbbb"])),
    )
    rows = session.scalars(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.query_id == query.id)
        .order_by(DiscoveryCandidate.ordinal)
    ).all()
    assert len(rows) == query.result_count == 2
    assert rows[0].creator_id == saved.id
    assert rows[0].filter_notes["discovery_sources"] == ["library", "realtime"]
    assert rows[1].filter_notes["discovery_sources"] == ["realtime"]


def test_library_append_is_bounded_and_never_readds_prior_candidates(session):
    for key in ("1234567", "2345678", "3456789"):
        creator(session, "instagram", key)
    query = make_query(
        session, providers=[{"platform": "instagram", "query": "game"}], batch_target=1
    )
    for expected in (1, 2, 3):
        batch = start_batch(session, query)
        session.commit()
        runtime()(
            batch.id,
            **factories(session, lambda req: pytest.fail("Unavailable live API")),
        )
        assert query.result_count == expected
    rows = session.scalars(
        select(DiscoveryCandidate).where(DiscoveryCandidate.query_id == query.id)
    ).all()
    assert len({row.account_id for row in rows}) == 3


def test_library_first_batch_does_not_starve_available_live_source(session):
    creator(session, "youtube", "UCaaaaaaa")
    query = make_query(session, batch_target=1)
    batch = start_batch(session, query)
    session.commit()
    calls = []

    def live(req):
        calls.append(req)
        return page(req, ["UCbbbbbbb"])

    runtime()(batch.id, **factories(session, live))
    assert len(calls) == 1
    assert query.result_count == 2


def test_four_selected_platforms_are_accepted_by_planning_contract():
    from app.schemas.discovery_planning import PlanCreate
    from app.schemas.discovery_plan_output import SearchPlanOutput

    platforms = ["youtube", "x", "twitch", "instagram"]
    assert PlanCreate(mode="discover", platforms=platforms).platforms == platforms
    output = SearchPlanOutput(
        summary="Supplied game.",
        rationale="Selected platforms.",
        queries=[{"platform": p, "terms": ["game"]} for p in platforms],
    )
    assert len(output.queries) == 4


def test_library_can_append_after_live_request_budget_is_exhausted(session):
    for key in ("1234567", "2345678"):
        creator(session, "instagram", key)
    query = make_query(
        session, providers=[{"platform": "instagram", "query": "game"}], batch_target=1
    )
    batch = start_batch(session, query)
    session.commit()
    runtime()(batch.id, **factories(session, lambda req: pytest.fail("No live API")))
    query.requests_reserved = query.conditions["total_request_budget"]
    session.commit()
    second = start_batch(session, query)
    session.commit()
    runtime()(second.id, **factories(session, lambda req: pytest.fail("No live API")))
    assert query.result_count == 2


def test_url_only_library_identity_can_be_evaluated_and_selected(session):
    from app.db.models.discovery import Activity
    from app.repositories.activity_preparation import add_selection
    from app.discovery.evaluation_snapshot import creator_snapshot

    saved = creator(session, "instagram", None)
    query = make_query(session, providers=[{"platform": "instagram", "query": "game"}])
    session.get(Activity, query.activity_id).source_snapshot = {"game": {}}
    batch = start_batch(session, query)
    session.commit()
    runtime()(batch.id, **factories(session, lambda req: pytest.fail("No live API")))
    candidate = session.scalar(
        select(DiscoveryCandidate).where(DiscoveryCandidate.query_id == query.id)
    )
    snapshot, _ = creator_snapshot(saved, candidate.id)
    assert snapshot["identity"]["account_id"] == candidate.account_id
    prepared = add_selection(session, query.activity_id, candidate.id)
    assert prepared["identity_changed"] is False


@pytest.mark.parametrize("failure", ["missing", "failed"])
def test_live_failure_preserves_library_and_other_platform_results(session, failure):
    from app.workers.discovery_tasks import MissingConnection
    from app.schemas.discovery import DiscoveryPage, DiscoveryIssue

    creator(session, "youtube", "UCsaved12")
    creator(session, "x", "123456789")
    query = make_query(
        session,
        providers=[
            {"platform": p, "query": "game", "page_size": 10} for p in ["youtube", "x"]
        ],
    )
    batch = start_batch(session, query)
    session.commit()

    def live(req):
        if req.platform == "youtube":
            if failure == "missing":
                raise MissingConnection()
            return DiscoveryPage(
                platform="youtube",
                status="failed",
                coverage="search_index",
                issues=[DiscoveryIssue(code="timeout")],
            )
        return page(req, ["234567890"])

    runtime()(batch.id, **factories(session, live))
    assert query.result_count == 3
    assert query.status == "paused"
    assert query.provider_states["youtube"]["status"] == (
        "missing_connection" if failure == "missing" else "failed"
    )
    assert query.provider_states["youtube"]["library"]["added_count"] == 1
    assert query.provider_states["x"]["status"] == "exhausted"


def test_library_filters_manual_values_and_does_not_mutate_profile(session):
    import copy
    from app.api.routes.activity import _query

    saved = creator(session, "instagram", "alpha")
    saved.manual_overrides = {
        "country_code": "US",
        "languages": ["English"],
        "follower_count": 50,
    }
    original = copy.deepcopy(saved.current_facts)
    other = creator(session, "instagram", "beta")
    other.manual_overrides = {"country_code": "JP"}
    query = make_query(
        session,
        providers=[{"platform": "instagram", "query": "game"}],
        filters={
            "countries": ["US"],
            "languages": ["en"],
            "follower_ranges": [{"minimum": 40, "maximum": 60}],
        },
    )
    batch = start_batch(session, query)
    session.commit()
    runtime()(batch.id, **factories(session, lambda req: pytest.fail("No live API")))
    assert query.result_count == 1
    assert saved.current_facts == original
    public = _query(session, query)["sources"]["instagram"]["library"]
    assert set(public) == {"status", "scanned_count", "added_count"}
    assert public["scanned_count"] == 2


def test_four_platform_plan_publishes_and_runs_library_only_sources(
    auth_client, session, monkeypatch
):
    from app.workers.planning_tasks import run_discovery_plan
    from app.schemas.discovery_plan_output import SearchPlanOutput
    from tests.integration.test_discovery_planning_api import (
        prepare,
        sessions_for,
        get_plan,
    )
    from uuid import UUID
    from app.db.models.discovery import DiscoveryQuery

    platforms = ["youtube", "x", "twitch", "instagram"]
    for platform in platforms:
        creator(
            session, platform, "UCsaved12" if platform == "youtube" else "123456789"
        )
        update_collection(session, platform, False)
    session.commit()
    identity = prepare(
        auth_client,
        monkeypatch,
        platforms=platforms,
        total_request_budget=10,
        total_scan_budget=100,
    )
    batches = []
    run_discovery_plan(
        identity,
        session_factory=sessions_for(session),
        plan_generator=lambda *args: SearchPlanOutput(
            summary="Supplied game.",
            rationale="Requested platforms.",
            queries=[{"platform": p, "terms": ["game"]} for p in platforms],
        ),
        dispatch_discovery=batches.append,
    )
    plan = get_plan(auth_client, identity)
    assert set(plan["output"]["provider_queries"]) == set(platforms)
    runtime()(
        batches[0],
        **factories(
            session, lambda req: pytest.fail("Disabled/unavailable collection")
        ),
    )
    query = session.get(DiscoveryQuery, UUID(plan["query_id"]))
    assert query.result_count == 4
    response = auth_client.get(f"/api/v2/discovery/queries/{query.id}/results")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 4
