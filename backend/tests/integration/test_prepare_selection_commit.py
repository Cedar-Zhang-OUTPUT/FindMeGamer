"""Existing bulk/freeze contract used by one client-side Prepare action."""

from uuid import UUID, uuid4

from app.db.models.profiles import CreatorProfile
from tests.integration.test_activity_preparation import setup_selection, post
from tests.integration.test_activity_recipient_batches import payload


def selections(client, activity_id):
    response = client.get(
        f"/api/v2/activities/{activity_id}/selections", params={"limit": 200}
    )
    assert response.status_code == 200
    return response.json()["items"]


def test_prepare_commits_final_delta_once_then_recovers_unknown_freeze(
    auth_client, session, monkeypatch
):
    activity_id, candidates = setup_selection(auth_client, session, monkeypatch, count=3)
    base = f"/api/v2/activities/{activity_id}"
    original = selections(auth_client, activity_id)
    by_candidate = {row["candidate_id"]: row for row in original}
    third = by_candidate[str(candidates[2].id)]
    assert post(auth_client, base + f"/selections/{third['id']}/cancel", {
        "expected_revision": third["revision"],
    }).status_code == 200

    # Checkbox edits are a local intent only; reading does not mutate selections.
    before = selections(auth_client, activity_id)
    desired = [str(candidates[2].id), str(candidates[1].id)]
    assert selections(auth_client, activity_id) == before
    current = {row["candidate_id"]: row for row in before}
    delta = {
        "add_candidate_ids": [item for item in desired if item not in current],
        "cancel_selections": [
            {"selection_id": row["id"], "expected_revision": row["revision"]}
            for item, row in current.items() if item not in desired
        ],
    }
    bulk_key = str(uuid4())
    committed = post(auth_client, base + "/selections/bulk", delta, key=bulk_key)
    assert committed.status_code == 200
    after = selections(auth_client, activity_id)
    # Lost acknowledgement: replay original key/body, never reconstruct the delta.
    replay = post(auth_client, base + "/selections/bulk", delta, key=bulk_key)
    assert replay.json() == committed.json()
    assert selections(auth_client, activity_id) == after
    assert {row["candidate_id"] for row in after} == set(desired)

    rows = {row["candidate_id"]: row for row in after}
    freeze_body = payload([rows[item] for item in desired])
    freeze_key = str(uuid4())
    batch_path = base + "/recipient-batches"
    frozen = post(auth_client, batch_path, freeze_body, key=freeze_key)
    assert frozen.status_code == 201
    assert post(auth_client, batch_path, freeze_body, key=freeze_key).json() == frozen.json()
    # Persistent request_id also protects recovery beyond the HTTP key lifetime.
    assert post(auth_client, batch_path, freeze_body).json() == frozen.json()
    listed = auth_client.get(batch_path).json()
    assert listed["total"] == 1
    assert listed["items"][0]["request_id"] == freeze_body["request_id"]
    assert [row["snapshot"]["candidate_id"] for row in frozen.json()["recipients"]] == desired
    assert not frozen.json()["send_ready"]


def test_prepare_freeze_conflict_keeps_committed_selections_for_explicit_resume(
    auth_client, session, monkeypatch
):
    activity_id, _ = setup_selection(auth_client, session, monkeypatch, count=2)
    base = f"/api/v2/activities/{activity_id}"
    before = selections(auth_client, activity_id)
    stale_payload = payload(before)
    creator = session.get(CreatorProfile, UUID(before[0]["creator_id"]))
    creator.manual_overrides = {"name": "Updated channel title"}
    session.commit()
    rejected = post(auth_client, base + "/recipient-batches", stale_payload)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "preparation_context_changed"
    assert auth_client.get(base + "/recipient-batches").json()["total"] == 0
    current = selections(auth_client, activity_id)
    assert [row["id"] for row in current] == [row["id"] for row in before]
    assert [row["revision"] for row in current] == [row["revision"] for row in before]
    # Explicit refresh uses fresh context and a new request, not a silent replay
    # of modified payload under an uncertain request's key.
    resumed = post(auth_client, base + "/recipient-batches", payload(current))
    assert resumed.status_code == 201
    assert resumed.json()["recipient_count"] == 2


def test_prepare_cancel_revision_conflict_rolls_back_whole_delta(
    auth_client, session, monkeypatch
):
    activity_id, _ = setup_selection(auth_client, session, monkeypatch, count=2)
    base = f"/api/v2/activities/{activity_id}"
    before = selections(auth_client, activity_id)
    rejected = post(auth_client, base + "/selections/bulk", {
        "cancel_selections": [
            {"selection_id": before[0]["id"], "expected_revision": before[0]["revision"]},
            {"selection_id": before[1]["id"], "expected_revision": before[1]["revision"] + 1},
        ],
    })
    assert rejected.status_code == 409
    assert selections(auth_client, activity_id) == before


def test_prepare_unchanged_selection_skips_empty_bulk_and_freezes_directly(
    auth_client, session, monkeypatch
):
    activity_id, _ = setup_selection(auth_client, session, monkeypatch, count=2)
    base = f"/api/v2/activities/{activity_id}"
    current = selections(auth_client, activity_id)
    # The explicit-delta endpoint intentionally does not accept a no-op.
    assert post(auth_client, base + "/selections/bulk", {
        "add_candidate_ids": [], "cancel_selections": [],
    }).status_code == 422
    assert selections(auth_client, activity_id) == current
    # Real Prepare skips that POST altogether when D == A.
    frozen = post(auth_client, base + "/recipient-batches", payload(current))
    assert frozen.status_code == 201
    assert frozen.json()["recipient_count"] == 2
    assert selections(auth_client, activity_id) == current
