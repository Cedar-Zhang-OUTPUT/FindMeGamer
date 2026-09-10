from uuid import UUID, uuid4

from sqlalchemy import select

from app.db.models.creator_search import CreatorSearch, CreatorSearchUnit
from app.db.models.discovery import DiscoveryQuery, DiscoveryBatch
from app.db.models.discovery_plan import DiscoveryPlan
from tests.integration.test_discovery_evaluation import (
    seed_query,
    sessions_for,
    fixture_executor,
)


def seeded_search(client, session, monkeypatch, count=3):
    query_id = UUID(seed_query(client, session, monkeypatch, count=count))
    query = session.get(DiscoveryQuery, query_id)
    plan = DiscoveryPlan(
        id=uuid4(),
        activity_id=query.activity_id,
        source_snapshot=query.source_snapshot,
        conditions=query.conditions,
        status="ready",
        query_id=query_id,
        model="fixture-only",
    )
    session.add(plan)
    session.flush()
    batch = session.scalar(
        select(DiscoveryBatch).where(DiscoveryBatch.query_id == query_id)
    )
    task = CreatorSearch(
        id=uuid4(),
        activity_id=query.activity_id,
        plan_id=plan.id,
        query_id=query_id,
        batch_id=batch.id,
        stage="discovery",
    )
    session.add(task)
    session.commit()
    return task.id


def test_complete_scope_email_missing_does_not_remove_match_and_delivery_is_idempotent(
    auth_client,
    session,
    monkeypatch,
):
    from app.workers.creator_search_tasks import run_creator_search

    identity = seeded_search(auth_client, session, monkeypatch)
    calls, profiles, emails = [], [], []

    def profile(unit_id):
        profiles.append(unit_id)
        return "ready"

    def email(unit_id):
        emails.append(unit_id)
        return "missing"

    kwargs = dict(
        session_factory=sessions_for(session),
        profile_runner=profile,
        email_runner=email,
        execute_model=fixture_executor(calls),
        heartbeat=False,
        concurrency=1,
    )
    run_creator_search(identity, **kwargs)
    run_creator_search(identity, **kwargs)
    view = auth_client.get(f"/api/v2/creator-searches/{identity}").json()
    assert view["status"] == "completed", view
    assert view["counts"]["matched"] == view["counts"]["email_missing"] == 3
    assert len(profiles) == len(emails) == 3
    assert view["evaluation_id"] is not None
    assert len([c for c in calls if c[0] == "deep_match"]) == 3


def test_partial_retry_only_failed_creator_preserves_successful_match_outputs(
    auth_client,
    session,
    monkeypatch,
):
    from app.workers.creator_search_tasks import run_creator_search

    identity = seeded_search(auth_client, session, monkeypatch)
    profiles, calls = [], []
    failed = []

    def profile(unit_id):
        profiles.append(unit_id)
        if len(profiles) == 2:
            failed.append(unit_id)
            raise RuntimeError("fixture secret must not appear in public errors")
        return "ready"

    kwargs = dict(
        session_factory=sessions_for(session),
        profile_runner=profile,
        email_runner=lambda uid: "missing",
        execute_model=fixture_executor(calls),
        heartbeat=False,
        concurrency=1,
    )
    run_creator_search(identity, **kwargs)
    task = session.get(CreatorSearch, identity)
    assert task.status == "partial"
    evaluation_id = task.evaluation_id
    task.status = "queued"
    session.commit()
    run_creator_search(identity, **kwargs)
    session.refresh(task)
    assert task.status == "completed"
    assert task.evaluation_id == evaluation_id
    assert len(profiles) == 4 and profiles[-1] == failed[0]
    assert len([c for c in calls if c[0] == "deep_match"]) == 3


def test_stop_after_inflight_profile_preserves_it_and_starts_no_next_unit(
    auth_client,
    session,
    monkeypatch,
):
    from app.workers.creator_search_tasks import run_creator_search

    identity = seeded_search(auth_client, session, monkeypatch)
    calls = []

    def profile(unit_id):
        calls.append(unit_id)
        task = session.get(CreatorSearch, identity)
        task.stop_requested = True
        session.commit()
        return "ready"

    run_creator_search(
        identity,
        session_factory=sessions_for(session),
        profile_runner=profile,
        email_runner=lambda uid: "missing",
        heartbeat=False,
        concurrency=1,
    )
    task = session.get(CreatorSearch, identity)
    assert task.status == "stopped" and task.evaluation_id is None
    units = list(
        session.scalars(
            select(CreatorSearchUnit).where(CreatorSearchUnit.search_id == identity)
        )
    )
    assert sum(u.profile_status == "ready" for u in units) == 1
    assert len(calls) == 1


def test_one_explicit_request_runs_planning_discovery_enrichment_and_matching(
    auth_client,
    session,
    monkeypatch,
):
    from contextlib import contextmanager
    import httpx
    from app.integrations.x_discovery import XDiscoveryGateway
    from app.workers.creator_search_tasks import run_creator_search
    from tests.integration.test_creator_search_api import activity
    from tests.integration.test_activity_preparation import post
    from tests.integration.test_activity_api import provider_page
    from tests.integration.test_discovery_planning_api import model_generator

    aid = activity(auth_client)
    auth_client.app.state.creator_search_dispatch = lambda uid: None
    receipt = post(
        auth_client,
        f"/api/v2/activities/{aid}/creator-searches",
        {"mode": "discover", "platforms": ["x"]},
    ).json()
    planning, providers, models = [], [], []

    def handler(request):
        providers.append(request.url.path)
        return provider_page([1, 2, 3])

    @contextmanager
    def gateways(platform):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with XDiscoveryGateway(
                bearer_token="fixture-only", http_client=client
            ) as gateway:
                yield gateway

    kwargs = dict(
        session_factory=sessions_for(session),
        plan_generator=model_generator(session, calls=planning),
        gateway_factory=gateways,
        profile_runner=lambda uid: "ready",
        email_runner=lambda uid: "missing",
        execute_model=fixture_executor(models),
        heartbeat=False,
        concurrency=1,
    )
    run_creator_search(receipt["search_id"], **kwargs)
    run_creator_search(receipt["search_id"], **kwargs)
    view = auth_client.get("/api/v2/creator-searches/" + receipt["search_id"]).json()
    assert view["status"] == "completed", view
    assert view["counts"]["matched"] == 3
    assert len(planning) == len(providers) == 1


def test_append_freezes_only_new_candidates_and_preserves_parent_units(
    auth_client, session, monkeypatch
):
    from app.workers import creator_search_tasks

    original = creator_search_tasks._discover
    errors = []

    def checked_discovery(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except Exception as error:
            errors.append(repr(error))
            raise

    monkeypatch.setattr(creator_search_tasks, "_discover", checked_discovery)
    from contextlib import contextmanager
    import httpx
    from app.integrations.x_discovery import XDiscoveryGateway
    from app.workers.creator_search_tasks import run_creator_search
    from tests.integration.test_activity_api import provider_page
    from tests.integration.test_activity_preparation import post

    identity = seeded_search(auth_client, session, monkeypatch, count=2)
    kwargs = dict(
        session_factory=sessions_for(session),
        profile_runner=lambda uid: "ready",
        email_runner=lambda uid: "missing",
        execute_model=fixture_executor([]),
        heartbeat=False,
        concurrency=1,
    )
    run_creator_search(identity, **kwargs)
    auth_client.app.state.creator_search_dispatch = lambda uid: None
    receipt = post(
        auth_client, f"/api/v2/creator-searches/{identity}/append", {}
    ).json()
    task = session.get(CreatorSearch, identity)
    query = session.get(DiscoveryQuery, task.query_id)
    states = dict(query.provider_states)
    states["x"] = {**states["x"], "status": "more", "cursor": None}
    query.provider_states = states
    session.commit()

    @contextmanager
    def gateways(platform):
        with httpx.Client(
            transport=httpx.MockTransport(lambda req: provider_page([2, 3]))
        ) as client:
            with XDiscoveryGateway(
                bearer_token="fixture-only", http_client=client
            ) as gateway:
                yield gateway

    run_creator_search(receipt["search_id"], gateway_factory=gateways, **kwargs)
    assert not errors, errors
    view = auth_client.get("/api/v2/creator-searches/" + receipt["search_id"]).json()
    assert view["status"] == "completed", view
    assert view["counts"]["discovered"] == view["counts"]["matched"] == 1
    assert (
        auth_client.get(f"/api/v2/creator-searches/{identity}").json()["counts"][
            "matched"
        ]
        == 2
    )


def test_screening_extension_keys_do_not_collide_with_non_screening_steps(
    auth_client, session, monkeypatch
):
    from app.repositories.discovery_evaluation import (
        create_run,
        extend_run,
        add_step,
        steps_for,
    )
    from app.db.models.discovery import DiscoveryCandidate

    identity = seeded_search(auth_client, session, monkeypatch, count=22)
    task = session.get(CreatorSearch, identity)
    query = session.get(DiscoveryQuery, task.query_id)
    candidates = list(
        session.scalars(
            select(DiscoveryCandidate)
            .where(DiscoveryCandidate.query_id == query.id)
            .order_by(DiscoveryCandidate.ordinal)
        )
    )
    run = create_run(session, query, candidates[:21])
    for index in range(18):
        add_step(session, run.id, f"deep:test{index}", "deep_match", [])
    session.flush()
    extend_run(session, run, candidates)
    assert len({s.step_key for s in steps_for(session, run.id)}) == 21


def test_actual_api_dto_bundle(auth_client, session, monkeypatch, tmp_path):
    """Export real API serialization from isolated synthetic worker outcomes."""
    import json
    from app.workers.creator_search_tasks import run_creator_search

    identity = seeded_search(auth_client, session, monkeypatch)
    route = f"/api/v2/creator-searches/{identity}"
    bundle = {"queued": auth_client.get(route).json()}
    called = []

    def profile(uid):
        called.append(uid)
        if len(called) == 2:
            raise RuntimeError("synthetic unit failed")
        return "ready"

    kwargs = dict(
        session_factory=sessions_for(session),
        profile_runner=profile,
        email_runner=lambda uid: "missing",
        execute_model=fixture_executor([]),
        heartbeat=False,
        concurrency=1,
    )
    run_creator_search(identity, **kwargs)
    bundle["partial"] = auth_client.get(route).json()
    bundle["partial_creators"] = auth_client.get(route + "/creators?limit=100").json()
    task = session.get(CreatorSearch, identity)
    task.status = "queued"
    session.commit()
    run_creator_search(identity, **kwargs)
    bundle["completed"] = auth_client.get(route).json()
    bundle["creators"] = auth_client.get(route + "/creators?limit=100").json()
    bundle["history"] = auth_client.get(
        f"/api/v2/activities/{task.activity_id}/creator-searches?limit=100"
    ).json()
    bundle["results"] = auth_client.get(
        f"/api/v2/discovery/evaluations/{task.evaluation_id}/results?limit=100"
    ).json()
    bundle["candidates"] = auth_client.get(
        f"/api/v2/discovery/queries/{task.query_id}/results?limit=100"
    ).json()
    assert bundle["completed"]["status"] == "completed"
    assert bundle["partial"]["status"] == "partial"
    assert bundle["results"]["total"] == 3
    assert "error" not in bundle["candidates"]
    (tmp_path / "creator-search-api.json").write_text(
        json.dumps(bundle, indent=2) + "\n"
    )
