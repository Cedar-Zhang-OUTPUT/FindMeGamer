from uuid import uuid4
from contextlib import contextmanager

import httpx
import pytest


@pytest.fixture
def dispatches(monkeypatch):
    from app.api.routes.activity import CeleryDiscoveryDispatcher

    values = []
    monkeypatch.setattr(
        CeleryDiscoveryDispatcher,
        "dispatch",
        lambda self, identity: values.append(identity),
    )
    return values


def activity(client):
    game = create_game(client)
    response = client.post(
        "/api/v2/activities",
        headers={"Idempotency-Key": str(uuid4())},
        json={"game_id": game["id"], "name": "Launch"},
    )
    assert response.status_code == 201
    return response.json()


def query(client, activity_id, **extra):
    response = client.post(
        f"/api/v2/activities/{activity_id}/queries",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "providers": [{"platform": "x", "query": "indie", "page_size": 10}],
            "batch_target": 1,
            **extra,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def execute(session, batch_id, handler):
    from app.integrations.x_discovery import XDiscoveryGateway
    from app.workers.discovery_tasks import run_discovery_batch

    @contextmanager
    def sessions():
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise

    @contextmanager
    def gateways(platform):
        assert platform == "x"
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with XDiscoveryGateway(
                bearer_token="fixture-only", http_client=client
            ) as gateway:
                yield gateway

    run_discovery_batch(batch_id, session_factory=sessions, gateway_factory=gateways)


def provider_page(ids, token=None):
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": str(1000 + i),
                    "author_id": str(i),
                    "text": "Indie news",
                    "lang": "en",
                }
                for i in ids
            ],
            "includes": {
                "users": [
                    {
                        "id": str(i),
                        "name": f"Creator {i}",
                        "username": f"creator{i}",
                        "public_metrics": {"followers_count": 200},
                    }
                    for i in ids
                ]
            },
            "meta": {
                "result_count": len(ids),
                **({"next_token": token} if token else {}),
            },
        },
    )


def create_game(client):
    response = client.post(
        "/api/v2/library/games",
        headers={"Idempotency-Key": str(uuid4())},
        json={"name": "Frozen Game", "reference_works": [{"name": "Reference"}]},
    )
    assert response.status_code == 201
    return response.json()


def test_activity_http_requires_auth(client):
    assert client.get("/api/v2/activities").status_code == 401


def test_activity_create_freezes_selected_references_and_replays(auth_client):
    game = create_game(auth_client)
    payload = {
        "name": "Launch",
        "game_id": game["id"],
        "reference_work_ids": [game["reference_works"][0]["id"]],
    }
    headers = {"Idempotency-Key": str(uuid4())}
    first = auth_client.post("/api/v2/activities", headers=headers, json=payload)
    assert first.status_code == 201
    again = auth_client.post("/api/v2/activities", headers=headers, json=payload)
    assert again.json() == first.json()
    auth_client.patch(
        f'/api/v2/library/games/{game["id"]}',
        json={"expected_revision": game["revision"], "name": "Changed"},
    )
    read = auth_client.get(f'/api/v2/activities/{first.json()["id"]}')
    assert read.json()["source_snapshot"]["game"]["name"] == "Frozen Game"
    assert len(read.json()["source_snapshot"]["references"]) == 1
    assert auth_client.get("/api/v2/activities").json()["total"] == 1


def test_activity_rejects_reference_not_in_game(auth_client):
    game = create_game(auth_client)
    response = auth_client.post(
        "/api/v2/activities",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "name": "Launch",
            "game_id": game["id"],
            "reference_work_ids": [str(uuid4())],
        },
    )
    assert response.status_code == 422


def test_http_task_library_append_and_duplicate_delivery(
    auth_client, session, dispatches
):
    launch = activity(auth_client)
    created = query(auth_client, launch["id"])
    calls = []

    def handle(request):
        assert (
            not session.in_transaction()
        ), "Provider I/O must not hold a DB transaction"
        calls.append(str(request.url))
        return provider_page([1], "page2") if len(calls) == 1 else provider_page([1, 2])

    execute(session, dispatches[0], handle)
    execute(session, dispatches[0], handle)
    assert len(calls) == 1
    first = auth_client.get(
        f'/api/v2/discovery/queries/{created["query_id"]}/results'
    ).json()
    assert first["total"] == 1
    assert first["items"][0]["selected"] is False
    creator_id = first["items"][0]["creator_id"]
    assert (
        auth_client.get(f"/api/v2/library/creators/{creator_id}").json()["name"]
        == "Creator 1"
    )
    headers = {"Idempotency-Key": str(uuid4())}
    more = auth_client.post(
        f'/api/v2/discovery/queries/{created["query_id"]}/continue',
        json={},
        headers=headers,
    )
    assert more.status_code == 202, more.text
    replay = auth_client.post(
        f'/api/v2/discovery/queries/{created["query_id"]}/continue',
        json={},
        headers=headers,
    )
    assert replay.json() == more.json()
    execute(session, dispatches[-1], handle)
    execute(session, dispatches[-1], handle)
    assert len(calls) == 2
    assert "next_token=page2" in calls[-1]
    final = auth_client.get(
        f'/api/v2/discovery/queries/{created["query_id"]}/results'
    ).json()
    assert final["total"] == 2
    assert len({item["creator_id"] for item in final["items"]}) == 2
    assert all(not item["selected"] for item in final["items"])


def test_stop_during_request_keeps_result_without_fetching_next_page(
    auth_client, session, dispatches
):
    created = query(auth_client, activity(auth_client)["id"], batch_target=100)
    calls = []

    def handle(request):
        calls.append(request)
        response = auth_client.post(
            f'/api/v2/discovery/queries/{created["query_id"]}/stop',
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200
        return provider_page([3], "more")

    execute(session, dispatches[0], handle)
    assert len(calls) == 1
    result = auth_client.get(f'/api/v2/discovery/queries/{created["query_id"]}').json()
    assert result["status"] == "stopped"
    assert result["result_count"] == 1
    more = auth_client.post(
        f'/api/v2/discovery/queries/{created["query_id"]}/continue',
        json={},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert more.status_code == 202, more.text
    execute(session, dispatches[-1], lambda request: provider_page([4]))
    assert (
        auth_client.get(
            f'/api/v2/discovery/queries/{created["query_id"]}/results'
        ).json()["total"]
        == 2
    )


def test_failed_append_preserves_results_and_new_conditions_make_new_query(
    auth_client, session, dispatches
):
    launch = activity(auth_client)
    created = query(auth_client, launch["id"])
    execute(session, dispatches[0], lambda request: provider_page([5], "next"))
    more = auth_client.post(
        f'/api/v2/discovery/queries/{created["query_id"]}/continue',
        json={},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert more.status_code == 202
    execute(
        session,
        dispatches[-1],
        lambda request: httpx.Response(403, text="private-canary"),
    )
    result = auth_client.get(f'/api/v2/discovery/queries/{created["query_id"]}')
    assert result.json()["result_count"] == 1
    assert "private-canary" not in result.text
    changed = query(auth_client, launch["id"], filters={"countries": ["US"]})
    assert changed["query_id"] != created["query_id"]
    assert (
        auth_client.get(
            f'/api/v2/discovery/queries/{changed["query_id"]}/results'
        ).json()["total"]
        == 0
    )
    assert (
        auth_client.get(
            f'/api/v2/discovery/queries/{created["query_id"]}/results'
        ).json()["total"]
        == 1
    )


def test_queue_failure_retry_same_key_does_not_create_new_query(
    auth_client, monkeypatch, dispatches
):
    from app.api.routes.activity import CeleryDiscoveryDispatcher

    launch = activity(auth_client)
    headers = {"Idempotency-Key": str(uuid4())}
    payload = {"providers": [{"platform": "x", "query": "indie"}]}
    attempts = []

    def dispatch(self, identity):
        attempts.append(identity)
        if len(attempts) == 1:
            raise RuntimeError("private-queue-error")

    monkeypatch.setattr(CeleryDiscoveryDispatcher, "dispatch", dispatch)
    path = f'/api/v2/activities/{launch["id"]}/queries'
    first = auth_client.post(path, headers=headers, json=payload)
    assert first.status_code == 503
    assert "private-queue-error" not in first.text
    retry = auth_client.post(path, headers=headers, json=payload)
    assert retry.status_code == 202
    assert attempts[0] == attempts[1]
    assert (
        len(auth_client.get(f'/api/v2/activities/{launch["id"]}').json()["queries"])
        == 1
    )
    conflict = auth_client.post(
        path,
        headers=headers,
        json={"providers": [{"platform": "x", "query": "changed"}]},
    )
    assert conflict.status_code == 409


def test_query_read_exposes_actual_usage_and_typed_http_contract(
    auth_client, session, dispatches
):
    created = query(auth_client, activity(auth_client)["id"])
    execute(session, dispatches[0], lambda request: provider_page([6]))
    state = auth_client.get(f'/api/v2/discovery/queries/{created["query_id"]}').json()
    assert state["usage"]["requests_used"] == 1
    assert state["usage"]["provider_items_received"] == 1
    schema = auth_client.get("/openapi.json").json()
    response = schema["paths"]["/api/v2/discovery/queries/{query_id}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert "$ref" in response


def test_http_reports_interrupted_request_and_requires_explicit_acknowledgement(
    auth_client, session, dispatches
):
    from datetime import UTC, datetime, timedelta
    from sqlalchemy import select
    from app.db.models.discovery import DiscoveryAttempt
    from app.workers.discovery_tasks import reserve

    created = query(auth_client, activity(auth_client)["id"])
    reserved = reserve(session, dispatches[0])
    assert reserved is not None
    session.commit()
    attempt = session.scalar(
        select(DiscoveryAttempt).where(DiscoveryAttempt.id == reserved[0])
    )
    attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    status = auth_client.get(f'/api/v2/discovery/queries/{created["query_id"]}').json()
    assert status["status"] == "outcome_unknown"
    assert status["requires_acknowledgement"] is True
    response = auth_client.post(
        f'/api/v2/discovery/queries/{created["query_id"]}/continue',
        headers={"Idempotency-Key": str(uuid4())},
        json={},
    )
    assert response.status_code == 409
    response = auth_client.post(
        f'/api/v2/discovery/queries/{created["query_id"]}/continue',
        headers={"Idempotency-Key": str(uuid4())},
        json={"acknowledge_unknown": True},
    )
    assert response.status_code == 202, response.text
    execute(session, dispatches[-1], lambda request: provider_page([7]))
    state = auth_client.get(f'/api/v2/discovery/queries/{created["query_id"]}').json()
    assert state["result_count"] == 1
    assert state["usage"]["unknown_requests_reserved"] == 1


def test_results_use_shared_library_details_after_manual_edit(
    auth_client, session, dispatches
):
    created = query(auth_client, activity(auth_client)["id"])
    execute(session, dispatches[0], lambda request: provider_page([8]))
    path = f'/api/v2/discovery/queries/{created["query_id"]}/results'
    row = auth_client.get(path).json()["items"][0]
    profile = auth_client.get(f'/api/v2/library/creators/{row["creator_id"]}').json()
    edited = auth_client.patch(
        f'/api/v2/library/creators/{row["creator_id"]}',
        json={"expected_revision": profile["revision"], "name": "Human confirmed name"},
    )
    assert edited.status_code == 200
    current = auth_client.get(path).json()["items"][0]
    assert current["creator"]["name"] == "Human confirmed name"
    assert current["account"]["display_name"] == "Creator 8"
