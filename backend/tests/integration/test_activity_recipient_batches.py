from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from app.db.models.profiles import CreatorProfile, GameProfile
from app.db.models.discovery import Activity
from tests.integration.test_activity_preparation import (
    setup_selection,
    choose,
    read,
    update,
    post,
    contacts,
)


def prepared(client, session, monkeypatch, count=2):
    activity_id, candidates = setup_selection(client, session, monkeypatch, count=count)
    choices = []
    for candidate in candidates:
        selection = choose(client, activity_id, candidate.id)
        path = f"/api/v2/library/creators/{candidate.creator_id}"
        profile = client.get(path).json()
        response = post(
            client,
            path + "/contacts",
            {
                "expected_revision": profile["revision"],
                "email": f"account-{candidate.account_id}@example.com",
                "purpose": "Sponsorship",
                "source_url": "https://example.com/contact",
            },
        )
        assert response.status_code == 201, response.text
        contact = response.json()["contacts"][0]
        response = update(client, read(client, selection), contact_id=contact["id"])
        assert response.status_code == 200, response.text
        choices.append(response.json())
    return activity_id, choices


def payload(choices, request_id=None):
    return {
        "request_id": request_id or str(uuid4()),
        "recipients": [
            {
                "selection_id": s["id"],
                "expected_revision": s["revision"],
                "context_token": s["context_token"],
            }
            for s in choices
        ],
    }


def freeze(client, activity_id, choices):
    response = post(
        client, f"/api/v2/activities/{activity_id}/recipient-batches", payload(choices)
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_freeze_explicit_subset_and_recover_same_persistent_request(
    auth_client, session, monkeypatch
):
    activity_id, choices = prepared(auth_client, session, monkeypatch)
    path = f"/api/v2/activities/{activity_id}/recipient-batches"
    value = payload(choices[:1])
    key = str(uuid4())
    response = post(auth_client, path, value, key=key)
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["status"] == "frozen" and not batch["send_ready"]
    assert len(batch["recipients"]) == 1
    snapshot = batch["recipients"][0]["snapshot"]
    assert snapshot["selected_contact"]["email"] == "account-1@example.com"
    assert snapshot["identity"] == choices[0]["identity"]
    assert "evaluation_missing" in snapshot["missing_fields"]
    assert not batch["recipients"][0]["source_changed"]
    assert post(auth_client, path, value, key=key).json() == batch
    assert (
        post(auth_client, path, value).json() == batch
    )  # persistent request ID, not just 24h key
    assert auth_client.get(path).json()["total"] == 1
    assert auth_client.get(path + f"/{batch['id']}").json() == batch
    changed = payload(choices, request_id=value["request_id"])
    assert post(auth_client, path, changed).status_code == 409


def test_missing_email_stays_in_frozen_total_as_repairable_member(
    auth_client, session, monkeypatch
):
    activity_id, choices = prepared(auth_client, session, monkeypatch)
    cleared = update(auth_client, choices[1], contact_id=None)
    assert cleared.status_code == 200
    path = f"/api/v2/activities/{activity_id}/recipient-batches"
    response = post(auth_client, path, payload([choices[0], cleared.json()]))
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["recipient_count"] == 2 and batch["send_ready_count"] == 0
    assert batch["needs_repair_count"] == 2
    pending = next(
        r for r in batch["recipients"] if r["selection_id"] == choices[1]["id"]
    )
    assert pending["snapshot"]["selected_contact"] is None
    assert "email_not_selected" in pending["current_missing_fields"]
    repaired = update(
        auth_client, cleared.json(), contact_id=choices[1]["selected_contact"]["id"]
    )
    assert repaired.status_code == 200
    reread = auth_client.get(path + f"/{batch['id']}").json()
    member = next(
        r for r in reread["recipients"] if r["selection_id"] == choices[1]["id"]
    )
    assert member["snapshot"]["selected_contact"] is None
    assert member["preparation"]["selected_contact"]["email"] == "account-2@example.com"
    assert "email_not_selected" not in member["current_missing_fields"]
    assert reread["recipient_count"] == 2 and reread["send_ready_count"] == 0


@pytest.mark.parametrize("change", ["email", "game", "identity", "cancel", "work"])
def test_source_changes_do_not_rewrite_frozen_history(
    auth_client, session, monkeypatch, change
):
    activity_id, choices = prepared(auth_client, session, monkeypatch, count=1)
    selection = choices[0]
    batch = freeze(auth_client, activity_id, choices)
    original = batch["recipients"][0]["snapshot"]
    creator = session.get(CreatorProfile, UUID(selection["creator_id"]))
    if change == "email":
        creator.contacts[0].email = "new-address@example.com"
    elif change == "game":
        activity = session.get(Activity, UUID(activity_id))
        session.get(GameProfile, activity.game_id).manual_overrides = {
            "description": "Changed game premise."
        }
    elif change == "identity":
        creator.identity_revision += 1
        creator.platform_account_id = "987654321"
    elif change == "work":
        creator.works[0].manual_overrides = {
            "evidence_excerpt": "Newly recorded content."
        }
    else:
        response = post(
            auth_client,
            f"/api/v2/activities/{activity_id}/selections/{selection['id']}/cancel",
            {"expected_revision": selection["revision"]},
        )
        assert response.status_code == 200
    session.commit()
    response = auth_client.get(
        f"/api/v2/activities/{activity_id}/recipient-batches/{batch['id']}"
    )
    assert response.status_code == 200, response.text
    recipient = response.json()["recipients"][0]
    assert recipient["snapshot"] == original
    assert recipient["source_changed"] and not response.json()["send_ready"]
    stale = post(
        auth_client,
        f"/api/v2/activities/{activity_id}/recipient-batches",
        payload(choices),
    )
    assert stale.status_code == 409, stale.text


def test_duplicate_address_is_repair_item_and_foreign_selection_rejected(
    auth_client, session, monkeypatch
):
    activity_id, choices = prepared(auth_client, session, monkeypatch)
    creator = session.get(CreatorProfile, UUID(choices[1]["creator_id"]))
    creator.contacts[0].email = choices[0]["selected_contact"]["email"]
    session.commit()
    changed = read(auth_client, choices[1])
    choices[1] = update(
        auth_client, changed, contact_id=changed["selected_contact"]["id"]
    ).json()
    response = post(
        auth_client,
        f"/api/v2/activities/{activity_id}/recipient-batches",
        payload(choices),
    )
    assert response.status_code == 201, response.text
    assert response.json()["recipient_count"] == 2
    assert all(
        "duplicate_email" in r["current_missing_fields"]
        for r in response.json()["recipients"]
    )
    other_id, _ = setup_selection(auth_client, session, monkeypatch)
    response = post(
        auth_client,
        f"/api/v2/activities/{other_id}/recipient-batches",
        payload(choices[:1]),
    )
    assert response.status_code == 404, response.text


def test_frozen_recipients_keep_explicit_user_order(auth_client, session, monkeypatch):
    import app.repositories.recipient_batches as repository

    activity_id, choices = prepared(auth_client, session, monkeypatch)
    ids = iter([UUID(int=9999), UUID(int=9998), UUID(int=9997)])
    monkeypatch.setattr(repository, "uuid4", lambda: next(ids))
    batch = freeze(auth_client, activity_id, choices)
    assert [r["selection_id"] for r in batch["recipients"]] == [
        s["id"] for s in choices
    ]
