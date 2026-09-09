from uuid import uuid4
from contextlib import contextmanager
import json

import httpx
import pytest


def sessions_for(session):
    @contextmanager
    def sessions():
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise

    return sessions


def prepare(client, monkeypatch, *, mode="discover", activity=None, **extra):
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: None)
    activity = activity or make_activity(client)
    response = client.post(
        f"/api/v2/activities/{activity['id']}/discovery-plans",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "mode": mode,
            "platforms": ["x"],
            "batch_target": 1,
            "total_request_budget": 1,
            "total_scan_budget": 10,
            **extra,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["plan_id"]


def model_generator(session, *, response=None, calls=None):
    from app.discovery.planning import generate_plan
    from app.integrations.deepseek import DeepSeekGateway

    def generate(snapshot, conditions, model):
        def handle(request):
            assert (
                not session.in_transaction()
            ), "Model I/O must not hold database transaction"
            if calls is not None:
                calls.append(json.loads(request.content))
            return response or httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "Minecraft is the supplied game name. Other facts are unknown.",
                                        "rationale": "Search the supplied game name.",
                                        "queries": [
                                            {"platform": "x", "terms": ["Minecraft"]}
                                        ],
                                    }
                                )
                            },
                        }
                    ]
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            with DeepSeekGateway(api_key="synthetic", http_client=client) as gateway:
                return generate_plan(snapshot, conditions, gateway=gateway, model=model)

    return generate


def get_plan(client, identity):
    response = client.get(f"/api/v2/discovery/plans/{identity}")
    assert response.status_code == 200, response.text
    return response.json()


def test_game_plan_model_query_provider_library_e2e_and_duplicates(
    auth_client, session, monkeypatch
):
    from app.workers.planning_tasks import run_discovery_plan
    from tests.integration.test_activity_api import execute, provider_page

    plan_id = prepare(auth_client, monkeypatch)
    batches, calls = [], []
    generate = model_generator(session, calls=calls)
    for _ in range(2):
        run_discovery_plan(
            plan_id,
            session_factory=sessions_for(session),
            plan_generator=generate,
            dispatch_discovery=batches.append,
        )
    plan = get_plan(auth_client, plan_id)
    assert plan["status"] == "ready"
    assert plan["query_id"] is not None
    assert plan["attempt"] == 1
    assert len(calls) == 1
    assert len(set(batches)) == 1
    query = auth_client.get(f"/api/v2/discovery/queries/{plan['query_id']}").json()
    assert query["conditions"]["providers"][0]["query"] == '"Minecraft" -is:retweet'
    assert query["conditions"]["total_request_budget"] == 1
    assert query["source_snapshot"]["discovery_plan_id"] == plan_id
    provider_calls = []

    def handle(request):
        provider_calls.append(request.url.path)
        return provider_page([12], "do-not-follow")

    for batch in batches:
        execute(session, batch, handle)
    results = auth_client.get(
        f"/api/v2/discovery/queries/{plan['query_id']}/results"
    ).json()
    assert results["total"] == 1
    assert results["items"][0]["creator"]["name"] == "Creator 12"
    assert provider_calls == ["/2/tweets/search/recent"]


def test_preview_never_creates_or_dispatches_discovery(
    auth_client, session, monkeypatch
):
    from app.workers.planning_tasks import run_discovery_plan
    from app.db.models.discovery import DiscoveryQuery
    from sqlalchemy import select, func

    identity = prepare(auth_client, monkeypatch, mode="preview")
    batches = []
    run_discovery_plan(
        identity,
        session_factory=sessions_for(session),
        plan_generator=model_generator(session),
        dispatch_discovery=batches.append,
    )
    plan = get_plan(auth_client, identity)
    assert plan["status"] == "ready"
    assert plan["query_id"] is None
    assert batches == []
    assert session.scalar(select(func.count()).select_from(DiscoveryQuery)) == 0


@pytest.mark.parametrize(
    "failure", ["timeout", "truncated", "invalid", "missing_configuration"]
)
def test_failed_plan_safe_and_retry_preserves_existing_ready_plan(
    auth_client, session, monkeypatch, failure, caplog
):
    from app.workers.planning_tasks import run_discovery_plan
    from app.integrations.errors import TransientIntegrationError

    # Alembic's test-session logging setup disables pre-imported loggers.
    import logging

    monkeypatch.setattr(
        logging.getLogger("app.workers.planning_tasks"), "disabled", False
    )

    first = prepare(auth_client, monkeypatch, mode="preview")
    run_discovery_plan(
        first,
        session_factory=sessions_for(session),
        plan_generator=model_generator(session),
    )
    old = get_plan(auth_client, first)
    second = prepare(auth_client, monkeypatch)
    if failure == "missing_configuration":
        generate = None
    elif failure == "timeout":

        def generate(*args):
            raise TransientIntegrationError("secret arbitrary unsafe text")

    else:
        response = httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if failure == "truncated" else "stop",
                        "message": {"content": "invalid synthetic output"},
                    }
                ]
            },
        )
        generate = model_generator(session, response=response)
    run_discovery_plan(
        second, session_factory=sessions_for(session), plan_generator=generate
    )
    failed = get_plan(auth_client, second)
    assert failed["status"] == "failed"
    assert failed["error_code"] in {
        "planning_model_unavailable",
        "planning_model_output_invalid",
        "planning_configuration_missing",
    }
    assert failed["retryable"] is True
    assert failed["query_id"] is None
    diagnostics = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "app.workers.planning_tasks"
    ]
    assert diagnostics[-1]["plan_id"] == str(second)
    assert diagnostics[-1]["attempt"] == 1
    assert "secret arbitrary unsafe text" not in json.dumps(diagnostics)
    assert "unsafe text" not in json.dumps(failed)
    assert get_plan(auth_client, first) == old
    retry = auth_client.post(
        f"/api/v2/discovery/plans/{second}/retry",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert retry.status_code == 202
    run_discovery_plan(
        second,
        session_factory=sessions_for(session),
        plan_generator=model_generator(session),
        dispatch_discovery=lambda identity: None,
    )
    assert get_plan(auth_client, second)["status"] == "ready"


def test_planning_rejects_unknown_duplicate_platforms_and_unauthenticated_requests(
    auth_client, client, monkeypatch
):
    activity = make_activity(auth_client)
    path = f"/api/v2/activities/{activity['id']}/discovery-plans"
    for platforms in (["unknown"], ["x", "x"]):
        assert (
            auth_client.post(
                path,
                headers={"Idempotency-Key": str(uuid4())},
                json={"mode": "discover", "platforms": platforms},
            ).status_code
            == 422
        )
    client.headers.pop("Authorization", None)
    assert client.get(path).status_code == 401


def make_activity(client, **game_fields):
    game = client.post(
        "/api/v2/library/games",
        headers={"Idempotency-Key": str(uuid4())},
        json={"name": "Minecraft", **game_fields},
    )
    assert game.status_code == 201
    activity = client.post(
        "/api/v2/activities",
        headers={"Idempotency-Key": str(uuid4())},
        json={"game_id": game.json()["id"], "name": "Planning launch"},
    )
    assert activity.status_code == 201
    return activity.json()


def test_planning_endpoint_accepts_game_conditions_without_native_query(
    auth_client, monkeypatch
):
    from app.workers.celery_app import celery_app

    dispatched = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda *a, **kw: dispatched.append((a, kw))
    )
    activity = make_activity(auth_client)
    path = f"/api/v2/activities/{activity['id']}/discovery-plans"
    headers = {"Idempotency-Key": str(uuid4())}
    payload = {
        "mode": "preview",
        "platforms": ["youtube", "x"],
        "keywords": ["gameplay"],
    }
    response = auth_client.post(path, headers=headers, json=payload)
    assert response.status_code == 202, response.text
    repeated = auth_client.post(path, headers=headers, json=payload)
    assert repeated.json() == response.json()
    plans = auth_client.get(path).json()
    assert plans["total"] == 1
    assert plans["items"][0]["source_snapshot"]["game"]["name"] == "Minecraft"
    assert plans["items"][0]["status"] == "queued"
    assert plans["items"][0]["query_id"] is None
    assert len(dispatched) == 2  # delivery can replay; worker claim is idempotent


def test_changed_filters_get_new_query_snapshot_and_keep_original(
    auth_client, session, monkeypatch
):
    from app.workers.planning_tasks import run_discovery_plan

    activity = make_activity(auth_client)
    first = prepare(auth_client, monkeypatch, activity=activity)
    second = prepare(
        auth_client,
        monkeypatch,
        activity=activity,
        filters={"languages": ["en"], "countries": ["US"]},
        keywords=["building"],
    )
    for identity in (first, second):
        run_discovery_plan(
            identity,
            session_factory=sessions_for(session),
            plan_generator=model_generator(session),
            dispatch_discovery=lambda _: None,
        )
    old, new = get_plan(auth_client, first), get_plan(auth_client, second)
    assert old["query_id"] != new["query_id"]
    query = auth_client.get(f"/api/v2/discovery/queries/{new['query_id']}").json()
    assert query["conditions"]["filters"]["countries"] == ["US"]
    assert old["conditions"]["filters"]["countries"] == []
    assert new["conditions"]["keywords"] == ["building"]
    assert old["source_snapshot"] == new["source_snapshot"]


def test_dispatch_failure_replay_uses_same_query_without_model_repeat(
    auth_client, session, monkeypatch
):
    from app.workers.planning_tasks import run_discovery_plan

    identity = prepare(auth_client, monkeypatch)
    calls = []

    def unavailable(_):
        raise RuntimeError("broker fixture unavailable")

    run_discovery_plan(
        identity,
        session_factory=sessions_for(session),
        plan_generator=model_generator(session, calls=calls),
        dispatch_discovery=unavailable,
    )
    original = get_plan(auth_client, identity)
    assert original["status"] == "ready"
    assert original["error_code"] == "planning_discovery_queue_unavailable"
    assert original["retryable"] is True
    retries = []
    run_discovery_plan(
        identity,
        session_factory=sessions_for(session),
        plan_generator=model_generator(session, calls=calls),
        dispatch_discovery=retries.append,
    )
    assert len(calls) == 1
    assert len(retries) == 1
    assert get_plan(auth_client, identity)["query_id"] == original["query_id"]
    assert get_plan(auth_client, identity)["error_code"] is None


def test_running_claim_duplicate_and_expired_retry_reject_stale_completion(
    auth_client, session, monkeypatch
):
    from app.workers.planning_tasks import run_discovery_plan
    from app.db.models.discovery_plan import DiscoveryPlan
    from app.core.idempotency import utc_now
    from datetime import timedelta
    from uuid import UUID

    identity = prepare(auth_client, monkeypatch)
    fixture_generate = model_generator(session)
    batches = []

    def original(snapshot, conditions, model):
        # Duplicate delivery while first call is active is a no-op.
        run_discovery_plan(
            identity,
            session_factory=sessions_for(session),
            plan_generator=lambda *a: pytest.fail("duplicate model call"),
        )
        response = auth_client.post(
            f"/api/v2/discovery/plans/{identity}/retry",
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 409
        with sessions_for(session)() as db:
            plan = db.get(DiscoveryPlan, UUID(identity))
            plan.lease_expires_at = utc_now() - timedelta(seconds=1)
        assert (
            get_plan(auth_client, identity)["error_code"] == "planning_outcome_unknown"
        )
        retry = auth_client.post(
            f"/api/v2/discovery/plans/{identity}/retry",
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert retry.status_code == 202
        run_discovery_plan(
            identity,
            session_factory=sessions_for(session),
            plan_generator=fixture_generate,
            dispatch_discovery=batches.append,
        )
        # End any read transaction before the late model result arrives.
        session.commit()
        return fixture_generate(snapshot, conditions, model)

    run_discovery_plan(
        identity,
        session_factory=sessions_for(session),
        plan_generator=original,
        dispatch_discovery=batches.append,
    )
    plan = get_plan(auth_client, identity)
    assert plan["status"] == "ready"
    assert plan["attempt"] == 2
    assert len(batches) == 1


def test_url_only_game_fails_actionably_without_network_or_profile_change(
    auth_client, session, monkeypatch
):
    from app.workers.planning_tasks import run_discovery_plan

    activity = make_activity(
        auth_client, name=None, website_url="https://example.test/game"
    )
    identity = prepare(auth_client, monkeypatch, activity=activity)
    calls = []
    run_discovery_plan(
        identity,
        session_factory=sessions_for(session),
        plan_generator=model_generator(session, calls=calls),
    )
    plan = get_plan(auth_client, identity)
    assert plan["status"] == "failed"
    assert plan["error_code"] == "game_context_required"
    assert plan["retryable"] is False
    assert calls == []
    game = auth_client.get(f"/api/v2/library/games/{activity['game_id']}").json()
    assert game["name"] is None
    assert game["website_url"] == "https://example.test/game"


def test_plan_dispatch_error_replay_does_not_duplicate_saved_plan(
    auth_client, monkeypatch
):
    from app.workers.celery_app import celery_app

    activity = make_activity(auth_client)

    def broken(*a, **kw):
        raise RuntimeError("synthetic broker outage")

    monkeypatch.setattr(celery_app, "send_task", broken)
    path = f"/api/v2/activities/{activity['id']}/discovery-plans"
    headers = {"Idempotency-Key": str(uuid4())}
    payload = {"mode": "discover", "platforms": ["youtube"]}
    assert auth_client.post(path, headers=headers, json=payload).status_code == 503
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: None)
    assert auth_client.post(path, headers=headers, json=payload).status_code == 202
    assert auth_client.get(path).json()["total"] == 1
    assert (
        auth_client.post(
            path, headers=headers, json={**payload, "mode": "preview"}
        ).status_code
        == 409
    )
