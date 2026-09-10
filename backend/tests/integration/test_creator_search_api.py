from uuid import UUID
from sqlalchemy import select, func
from app.db.models.creator_search import CreatorSearch
from tests.integration.test_activity_preparation import post
from tests.integration.test_steam_import import create_game


def activity(client):
    game = create_game(client)
    result = post(
        client,
        "/api/v2/activities",
        {"game_id": game["id"], "name": "One click campaign"},
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def test_new_search_is_explicit_durable_idempotent_and_old_activity_not_upgraded(
    auth_client, session
):
    aid = activity(auth_client)
    dispatched = []
    auth_client.app.state.creator_search_dispatch = dispatched.append
    path = f"/api/v2/activities/{aid}/creator-searches"
    body = {"mode": "discover", "platforms": ["youtube", "x"]}
    response = post(auth_client, path, body, key="unified-start-test")
    assert response.status_code == 202, response.text
    receipt = response.json()
    assert post(auth_client, path, body, key="unified-start-test").json() == receipt
    assert session.scalar(select(func.count()).select_from(CreatorSearch)) == 1
    view = auth_client.get("/api/v2/creator-searches/" + receipt["search_id"]).json()
    assert view["stage"] == "planning" and view["status"] == "queued"
    assert view["query_id"] is None and view["evaluation_id"] is None
    assert view["counts"]["discovered"] == 0
    assert auth_client.get(path).json()["items"][0]["id"] == receipt["search_id"]
    other = activity(auth_client)
    assert (
        auth_client.get(f"/api/v2/activities/{other}/creator-searches").json()["items"]
        == []
    )


def test_stop_before_work_and_resume_require_explicit_write(auth_client, session):
    aid = activity(auth_client)
    auth_client.app.state.creator_search_dispatch = lambda value: None
    receipt = post(
        auth_client,
        f"/api/v2/activities/{aid}/creator-searches",
        {"mode": "discover", "platforms": ["youtube"]},
    ).json()
    path = "/api/v2/creator-searches/" + receipt["search_id"]
    stopped = post(auth_client, path + "/stop", {})
    assert stopped.status_code == 202, stopped.text
    assert auth_client.get(path).json()["status"] == "stopped"
    assert post(auth_client, path + "/retry", {}).status_code == 202
    assert auth_client.get(path).json()["status"] == "queued"
    assert post(auth_client, path + "/append", {}).status_code == 409


def test_queue_failure_reuses_saved_receipt_and_expired_execution_requires_ack(
    auth_client, session
):
    from datetime import timedelta
    from uuid import uuid4
    from app.core.idempotency import utc_now

    aid = activity(auth_client)

    def unavailable(identity):
        raise RuntimeError("synthetic broker offline")

    auth_client.app.state.creator_search_dispatch = unavailable
    path = f"/api/v2/activities/{aid}/creator-searches"
    body = {"platforms": ["x"]}
    response = post(auth_client, path, body, key="saved-search")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "search_queue_unavailable"
    auth_client.app.state.creator_search_dispatch = lambda uid: None
    receipt = post(auth_client, path, body, key="saved-search").json()
    assert session.scalar(select(func.count()).select_from(CreatorSearch)) == 1
    task = session.get(CreatorSearch, UUID(receipt["search_id"]))
    task.status = "running"
    task.lease_token = uuid4()
    task.lease_expires_at = utc_now() - timedelta(seconds=1)
    session.commit()
    route = "/api/v2/creator-searches/" + receipt["search_id"]
    assert auth_client.get(route).json()["outcome_unknown"] is True
    rejected = post(auth_client, route + "/retry", {})
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "search_outcome_unknown"
    assert (
        post(auth_client, route + "/retry", {"acknowledge_unknown": True}).status_code
        == 202
    )


def test_search_pagination_accepts_100_and_rejects_over_200(auth_client, session):
    aid = activity(auth_client)
    path = f"/api/v2/activities/{aid}/creator-searches"
    assert auth_client.get(path + "?limit=100").json()["limit"] == 100
    assert auth_client.get(path + "?limit=201").status_code == 422
