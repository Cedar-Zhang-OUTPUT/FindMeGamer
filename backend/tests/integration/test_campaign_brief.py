from uuid import uuid4

from tests.integration.test_activity_api import activity
from tests.integration.test_discovery_planning_api import prepare, get_plan


def test_campaign_brief_is_activity_scoped_and_revision_checked(auth_client):
    first = activity(auth_client)
    second = auth_client.post(
        "/api/v2/activities",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "game_id": first["game_id"],
            "name": "Second campaign",
            "campaign_brief": "Find puzzle reviewers.",
        },
    )
    assert second.status_code == 201
    other = second.json()
    assert first["campaign_brief"] is None and first["revision"] == 0
    game_before = auth_client.get("/api/v2/library/games/" + first["game_id"]).json()
    path = f"/api/v2/activities/{first['id']}/campaign-brief"
    changed = auth_client.patch(
        path,
        json={
            "campaign_brief": "  Focus on story commentary.  ",
            "expected_revision": 0,
        },
    )
    assert changed.status_code == 200
    assert changed.json()["campaign_brief"] == "Focus on story commentary."
    assert changed.json()["revision"] == 1
    conflict = auth_client.patch(
        path, json={"campaign_brief": "Overwrite", "expected_revision": 0}
    )
    assert conflict.status_code == 409
    assert (
        auth_client.get("/api/v2/activities/" + other["id"]).json()["campaign_brief"]
        == "Find puzzle reviewers."
    )
    assert (
        auth_client.get("/api/v2/library/games/" + first["game_id"]).json()
        == game_before
    )
    empty = auth_client.patch(
        path, json={"campaign_brief": "   ", "expected_revision": 1}
    )
    assert empty.status_code == 200 and empty.json()["campaign_brief"] is None
    assert (
        auth_client.patch(
            path, json={"campaign_brief": "x" * 5001, "expected_revision": 2}
        ).status_code
        == 422
    )


def test_plan_freezes_brief_and_later_activity_edit_only_affects_new_plan(
    auth_client, monkeypatch
):
    first = activity(auth_client)
    path = f"/api/v2/activities/{first['id']}/campaign-brief"
    assert (
        auth_client.patch(
            path, json={"campaign_brief": "First intent", "expected_revision": 0}
        ).status_code
        == 200
    )
    plan_id = prepare(auth_client, monkeypatch, activity=first)
    before = get_plan(auth_client, plan_id)
    assert before["source_snapshot"]["campaign_brief"] == "First intent"
    assert (
        auth_client.patch(
            path, json={"campaign_brief": "Second intent", "expected_revision": 1}
        ).status_code
        == 200
    )
    assert (
        get_plan(auth_client, plan_id)["source_snapshot"] == before["source_snapshot"]
    )
    next_id = prepare(auth_client, monkeypatch, activity=first)
    assert (
        get_plan(auth_client, next_id)["source_snapshot"]["campaign_brief"]
        == "Second intent"
    )


def test_brief_edit_invalidates_preparation_but_preserves_frozen_batch(
    auth_client, session, monkeypatch
):
    from tests.integration.test_activity_recipient_batches import (
        prepared,
        payload,
        freeze,
    )
    from tests.integration.test_activity_preparation import read, post

    activity_id, choices = prepared(auth_client, session, monkeypatch, count=1)
    path = f"/api/v2/activities/{activity_id}/campaign-brief"
    assert (
        auth_client.patch(
            path, json={"campaign_brief": "Story creators", "expected_revision": 0}
        ).status_code
        == 200
    )
    batch_path = f"/api/v2/activities/{activity_id}/recipient-batches"
    assert post(auth_client, batch_path, payload(choices)).status_code == 409
    fresh = read(auth_client, choices[0])
    frozen = freeze(auth_client, activity_id, [fresh])
    assert frozen["source_snapshot"]["campaign_brief"] == "Story creators"
    assert (
        auth_client.patch(
            path, json={"campaign_brief": "Puzzle creators", "expected_revision": 1}
        ).status_code
        == 200
    )
    reread = auth_client.get(batch_path + "/" + frozen["id"]).json()
    assert reread["source_snapshot"] == frozen["source_snapshot"]
    assert reread["recipients"][0]["snapshot"] == frozen["recipients"][0]["snapshot"]
