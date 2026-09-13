from sqlalchemy import select
from tests.integration.test_discovery_runtime import (
    make_query,
    factories,
    page,
    runtime,
)
import pytest


def test_busy_youtube_direction_does_not_starve_x_in_same_batch(session):
    from app.repositories.discovery import start_batch

    query = make_query(
        session,
        batch_request_budget=5,
        providers=[
            {
                "platform": "youtube",
                "query": "horror",
                "page_size": 2,
                "max_requests": 2,
            },
            {
                "platform": "x",
                "query": "games -is:retweet",
                "page_size": 10,
                "max_requests": 1,
            },
        ],
        query_directions={"youtube": ["horror", "mystery"], "x": ["games -is:retweet"]},
    )
    batch = start_batch(session, query)
    session.commit()
    calls = []

    def respond(req):
        calls.append((req.platform, req.query))
        return page(req, [], req.platform == "youtube")

    runtime()(batch.id, **factories(session, respond))
    assert calls == [
        ("youtube", "horror"),
        ("x", "games -is:retweet"),
        ("youtube", "mystery"),
    ]
    assert query.requests_reserved == 5


def test_empty_direction_falls_through_and_each_cursor_resumes_without_duplicates(
    session,
):
    from app.repositories.discovery import start_batch
    from app.db.models.discovery import DiscoveryAttempt

    query = make_query(
        session,
        batch_request_budget=4,
        query_directions={"youtube": ["empty", "horror gameplay", "mystery games"]},
    )
    batch = start_batch(session, query)
    session.commit()
    calls = []

    def respond(req):
        calls.append((req.query, req.cursor.token if req.cursor else None))
        return page(
            req,
            [] if req.query == "empty" else ["UCaaaaaaa"],
            req.query == "horror gameplay" and req.cursor is None,
        )

    runtime()(batch.id, **factories(session, respond))
    assert calls == [("empty", None), ("horror gameplay", None)]
    assert query.result_count == 1
    assert batch.reason == "budget_exhausted"
    batch2 = start_batch(session, query)
    session.commit()
    runtime()(batch2.id, **factories(session, respond))
    assert calls == [
        ("empty", None),
        ("horror gameplay", None),
        ("mystery games", None),
        ("horror gameplay", "next"),
    ]
    assert query.result_count == 1
    assert query.requests_reserved == 8
    assert len(session.scalars(select(DiscoveryAttempt)).all()) == 4
    batch3 = start_batch(session, query)
    session.commit()
    runtime()(
        batch3.id,
        **factories(
            session,
            lambda r: (_ for _ in ()).throw(AssertionError("replayed paid request")),
        ),
    )
    assert batch3.requests_reserved == 0


def test_existing_exhausted_plan_upgrades_only_on_explicit_continue(session):
    from app.db.models.discovery_plan import DiscoveryPlan
    from app.repositories.discovery import start_batch

    query = make_query(session)
    plan = DiscoveryPlan(
        activity_id=query.activity_id,
        query_id=query.id,
        status="ready",
        model="deepseek-flash",
        source_snapshot={"game": {"name": "New Game"}},
        conditions={},
        output={
            "summary": "Find creators",
            "rationale": "Find related games",
            "queries": [
                {
                    "platform": "youtube",
                    "terms": ["New Game", "horror gameplay", "mystery games"],
                }
            ],
        },
    )
    session.add(plan)
    query.provider_states = {
        "youtube": {
            "status": "exhausted",
            "cursor": None,
            "library": {"status": "complete"},
        }
    }
    session.commit()
    batch = start_batch(session, query)
    session.commit()
    calls = []
    runtime()(
        batch.id, **factories(session, lambda r: calls.append(r.query) or page(r, []))
    )
    assert calls == ["horror gameplay", "mystery games", "New Game"]
    assert query.conditions["filters"] == {}
    assert query.conditions["providers"][0]["max_requests"] == 3
    batch2 = start_batch(session, query)
    session.commit()
    runtime()(
        batch2.id,
        **factories(
            session, lambda r: (_ for _ in ()).throw(AssertionError("replayed"))
        ),
    )
    assert batch2.requests_reserved == 0


@pytest.mark.parametrize("limit", ["batch_request_budget", "total_request_budget"])
def test_three_request_page_never_exceeds_remaining_two(session, limit):
    from app.repositories.discovery import start_batch

    query = make_query(
        session,
        **{limit: 2},
        providers=[
            {
                "platform": "youtube",
                "query": "horror",
                "page_size": 2,
                "max_requests": 3,
            }
        ],
        query_directions={"youtube": ["horror", "mystery"]},
    )
    batch = start_batch(session, query)
    session.commit()
    runtime()(batch.id, **factories(session, lambda r: pytest.fail("budget exceeded")))
    assert query.requests_reserved == 0
    assert batch.reason in {"budget_exhausted", "total_budget_exhausted"}


def test_cold_library_respects_country_followers_and_known_content_language(session):
    from app.repositories.discovery import start_batch
    from app.schemas.discovery import DiscoveredContent

    filters = {
        "countries": ["US", "CA", "JP", "KR"],
        "languages": ["en", "ja"],
        "follower_ranges": [{"minimum": 0, "maximum": 99999}],
        "include_unknown_country": False,
        "include_unknown_language": False,
        "include_unknown_followers": False,
    }
    query = make_query(session, filters=filters)
    batch = start_batch(session, query)
    session.commit()

    def respond(req):
        result = page(req, ["UCknownxx", "UCunknown", "UCoutsize"])
        for i, account in enumerate(result.accounts):
            account.country = "US"
            account.follower_count = 200000 if i == 2 else 1000
            result.contents.append(
                DiscoveredContent(
                    platform="youtube",
                    content_id=str(i),
                    account_id=account.account_id,
                    source_url=f"https://www.youtube.com/watch?v=video0000{i}",
                    collected_at=account.collected_at,
                    language="en-US" if i != 1 else None,
                    language_source="defaultAudioLanguage" if i != 1 else None,
                )
            )
        return result

    runtime()(batch.id, **factories(session, respond))
    assert query.result_count == 1
    assert query.conditions["filters"] == filters
    from app.db.models.discovery import DiscoveryAttempt

    outcome = session.scalar(select(DiscoveryAttempt)).outcome
    assert outcome["accounts_received"] == 3
    assert outcome["eligible_count"] == 1
    assert outcome["failed_filters"] == {"language": 1, "followers": 1}


def test_completed_zero_search_append_is_reachable_idempotent_and_upgrades(
    auth_client, session
):
    from uuid import UUID
    from app.db.models.discovery_plan import DiscoveryPlan
    from app.db.models.creator_search import CreatorSearch
    from app.db.models.discovery import DiscoveryAttempt
    from tests.integration.test_activity_preparation import post
    from tests.integration.test_discovery_planning_api import sessions_for
    from app.workers.creator_search_tasks import run_creator_search
    from contextlib import contextmanager

    query = make_query(session)
    query.provider_states = {"youtube": {"status": "exhausted"}}
    plan = DiscoveryPlan(
        activity_id=query.activity_id,
        query_id=query.id,
        status="ready",
        model="fixture",
        source_snapshot={"game": {"name": "New Game"}},
        output={
            "summary": "Game",
            "rationale": "Related games",
            "queries": [
                {"platform": "youtube", "terms": ["New Game", "horror gameplay"]}
            ],
        },
    )
    session.add(plan)
    session.flush()
    parent = CreatorSearch(
        activity_id=query.activity_id,
        plan_id=plan.id,
        query_id=query.id,
        status="completed",
        stage="complete",
        scope_frozen=True,
    )
    session.add(parent)
    session.commit()
    auth_client.app.state.creator_search_dispatch = lambda identity: None
    path = f"/api/v2/creator-searches/{parent.id}/append"
    first = post(auth_client, path, {}, key="append-zero-independent-directions")
    assert first.status_code == 202
    assert (
        post(auth_client, path, {}, key="append-zero-independent-directions").json()
        == first.json()
    )
    calls = []

    class Gateway:
        def discover(self, request):
            calls.append(request.query)
            return page(request, [])

    @contextmanager
    def gateways(platform):
        yield Gateway()

    kwargs = {
        "session_factory": sessions_for(session),
        "gateway_factory": gateways,
        "heartbeat": False,
        "plan_generator": lambda *args: pytest.fail("No model needed"),
        "profile_runner": lambda *args: pytest.fail("No profile candidates"),
        "email_runner": lambda *args: pytest.fail("No email candidates"),
    }
    identity = UUID(first.json()["search_id"])
    run_creator_search(identity, **kwargs)
    run_creator_search(identity, **kwargs)
    assert calls == ["horror gameplay", "New Game"]
    assert len(session.scalars(select(DiscoveryAttempt)).all()) == 2
    assert session.get(CreatorSearch, identity).status == "completed"
    assert parent.status == "completed"
    response = auth_client.get(f"/api/v2/discovery/queries/{query.id}")
    assert response.status_code == 200
    public = response.json()
    assert public["conditions"]["providers"][0]["max_requests"] == 3
    assert "query_directions" not in public["conditions"]
    assert "directions" not in public["sources"]["youtube"]
