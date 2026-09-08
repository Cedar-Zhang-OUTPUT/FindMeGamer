from uuid import UUID, uuid4
import pytest
from app.core.idempotency import utc_now
from app.db.models.activity_sending import ActivityDelivery
from app.db.models.profiles import CreatorProfile
from app.db.models.discovery import Activity
from app.db.models.profiles import GameProfile
from tests.integration.test_activity_qualification import ready_composition, preview
from tests.integration.test_activity_preparation import post
from tests.integration.test_activity_preparation import read, update
from tests.integration.test_outreach_drafts import compose, manual, confirm_facts


def final_send(
    client, composition, qualification, *, request_id=None, key=None, excluded=None
):
    return post(
        client,
        f"/api/v2/outreach/compositions/{composition['id']}/send-batches",
        {
            "request_id": str(request_id or uuid4()),
            "qualification_token": qualification["qualification_token"],
            "excluded": excluded or [],
        },
        key=key,
    )


def get_batch(client, identity):
    result = client.get(f"/api/v2/outreach/send-batches/{identity}")
    assert result.status_code == 200, result.text
    return result.json()


def test_final_confirmation_freezes_eligible_subset_and_durable_request_replay(
    auth_client, session, monkeypatch
):
    activity, composition = ready_composition(auth_client, session, monkeypatch)
    excluded = [{"draft_id": composition["drafts"][2]["id"], "reason": "Need evidence"}]
    qualified = preview(auth_client, composition, excluded).json()
    request_id, key = uuid4(), str(uuid4())
    response = final_send(
        auth_client,
        composition,
        qualified,
        request_id=request_id,
        key=key,
        excluded=excluded,
    )
    assert response.status_code == 201, response.text
    batch = response.json()
    assert (
        batch["activity_id"] == activity
        and batch["composition_id"] == composition["id"]
    )
    assert len(batch["deliveries"]) == 2 and batch["qualification"]["total_count"] == 3
    assert batch["qualification"]["excluded_count"] == 1
    assert [d["snapshot"]["recipient_email"] for d in batch["deliveries"]] == [
        "account-1@example.com",
        "account-2@example.com",
    ]
    assert all(d["state"] == "queued" for d in batch["deliveries"])
    assert batch["deliveries"][0]["snapshot"]["sender"] == {
        "address": "producer@example.com",
        "name": "Toki",
        "reply_to": "reply@example.com",
    }
    for replay_key in (key, str(uuid4())):
        assert (
            final_send(
                auth_client,
                composition,
                qualified,
                request_id=request_id,
                key=replay_key,
                excluded=excluded,
            ).json()
            == batch
        )
    assert get_batch(auth_client, batch["id"]) == batch
    assert (
        auth_client.get(f"/api/v2/activities/{activity}/send-batches").json()["total"]
        == 1
    )
    assert (
        final_send(
            auth_client, composition, qualified, request_id=request_id, excluded=[]
        ).status_code
        == 409
    )


def test_stale_qualification_and_unexcluded_repairs_create_no_deliveries(
    auth_client, session, monkeypatch
):
    activity_id, composition = ready_composition(auth_client, session, monkeypatch)
    incomplete = preview(auth_client, composition).json()
    assert final_send(auth_client, composition, incomplete).status_code == 422
    excluded = [{"draft_id": composition["drafts"][2]["id"], "reason": "Need evidence"}]
    qualified = preview(auth_client, composition, excluded).json()
    game = session.get(GameProfile, session.get(Activity, UUID(activity_id)).game_id)
    game.manual_overrides = game.manual_overrides | {
        "description": "Updated before final confirmation"
    }
    session.commit()
    assert (
        final_send(auth_client, composition, qualified, excluded=excluded).status_code
        == 409
    )
    assert (
        auth_client.get(f"/api/v2/activities/{activity_id}/send-batches").json()[
            "total"
        ]
        == 0
    )


def test_final_snapshot_survives_library_edits_and_same_request_replay(
    auth_client, session, monkeypatch
):
    activity_id, composition = ready_composition(
        auth_client, session, monkeypatch, count=1
    )
    qualified = preview(auth_client, composition).json()
    request_id = uuid4()
    response = final_send(auth_client, composition, qualified, request_id=request_id)
    assert response.status_code == 201, response.text
    batch = response.json()
    game = session.get(GameProfile, session.get(Activity, UUID(activity_id)).game_id)
    game.manual_overrides = game.manual_overrides | {
        "description": "Later changes cannot replace approved mail"
    }
    session.commit()
    assert get_batch(auth_client, batch["id"])["deliveries"] == batch["deliveries"]
    assert (
        final_send(auth_client, composition, qualified, request_id=request_id).json()
        == batch
    )


def test_all_excluded_cannot_create_empty_send_batch(auth_client, session, monkeypatch):
    activity, composition = ready_composition(
        auth_client, session, monkeypatch, count=1
    )
    excluded = [
        {"draft_id": composition["drafts"][0]["id"], "reason": "Not this campaign"}
    ]
    qualified = preview(auth_client, composition, excluded).json()
    assert (
        final_send(auth_client, composition, qualified, excluded=excluded).status_code
        == 422
    )
    assert (
        auth_client.get(f"/api/v2/activities/{activity}/send-batches").json()["total"]
        == 0
    )


@pytest.mark.parametrize("state", ["queued", "sending", "sent", "unknown"])
def test_cross_batch_normal_invitation_is_blocked_for_same_activity_account(
    auth_client, session, monkeypatch, state
):
    activity, composition = ready_composition(
        auth_client, session, monkeypatch, count=1
    )
    qualified = preview(auth_client, composition).json()
    created = final_send(auth_client, composition, qualified).json()
    prior = session.get(ActivityDelivery, UUID(created["deliveries"][0]["id"]))
    prior.state = state
    session.commit()
    current = preview(auth_client, composition).json()
    assert current["eligible_count"] == 0
    assert current["members"][0]["blocking_delivery_id"] == str(prior.id)
    assert "already_invited" in current["members"][0]["missing_fields"]
    response = final_send(auth_client, composition, current)
    assert response.status_code == 409, response.text
    assert str(prior.id) in response.json()["error"]["message"]
    assert (
        auth_client.get(f"/api/v2/activities/{activity}/send-batches").json()["total"]
        == 1
    )


def test_definitely_failed_delivery_allows_corrected_new_snapshot_but_old_retry_cannot_race(
    auth_client, session, monkeypatch
):
    activity, composition = ready_composition(
        auth_client, session, monkeypatch, count=1
    )
    qualified = preview(auth_client, composition).json()
    created = final_send(auth_client, composition, qualified).json()
    prior = session.get(ActivityDelivery, UUID(created["deliveries"][0]["id"]))
    prior.state, prior.retryable, prior.attempt = "failed", True, 1
    prior.sending_at = prior.failed_at = utc_now()
    session.commit()
    old_draft = composition["drafts"][0]
    selection = auth_client.get(
        f"/api/v2/activities/{activity}/selections/{old_draft['selection_id']}"
    ).json()
    creator = session.get(CreatorProfile, UUID(selection["creator_id"]))
    creator.contacts[0].email = "corrected@example.com"
    session.commit()
    repaired = update(
        auth_client,
        read(auth_client, selection),
        contact_id=str(creator.contacts[0].id),
    )
    assert repaired.status_code == 200
    fresh = compose(
        auth_client,
        activity,
        {"id": composition["recipient_batch_id"]},
        {"id": composition["template_version_id"]},
    ).json()
    draft = manual(auth_client, fresh["drafts"][0]).json()
    assert confirm_facts(auth_client, fresh["id"], [draft]).status_code == 200
    current = preview(auth_client, fresh).json()
    replacement = final_send(auth_client, fresh, current)
    assert replacement.status_code == 201, replacement.text
    assert (
        replacement.json()["deliveries"][0]["snapshot"]["recipient_email"]
        == "corrected@example.com"
    )
    assert (
        get_batch(auth_client, created["id"])["deliveries"][0]["snapshot"][
            "recipient_email"
        ]
        == "account-1@example.com"
    )
    retried = post(
        auth_client,
        f"/api/v2/outreach/deliveries/{prior.id}/retry",
        {"expected_attempt": 1},
    )
    assert retried.status_code == 409, retried.text
