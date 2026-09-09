from datetime import timedelta
from uuid import UUID, uuid4
import pytest

from sqlalchemy import select, func

from app.core.idempotency import utc_now
from app.db.models.discovery import Activity
from app.db.models.activity_outreach import ActivitySelection
from app.db.models.activity_sending import ActivityDelivery
from tests.integration.test_activity_preparation import setup_selection, choose, post
from tests.integration.test_activity_qualification import ready_composition, preview
from tests.integration.test_activity_final_send import final_send


def invitations(client, activity_id, **params):
    response = client.get(
        f"/api/v2/activities/{activity_id}/invitations", params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_same_list_keeps_excluded_and_cancelled_frozen_members(
    auth_client, session, monkeypatch
):
    activity, composition = ready_composition(auth_client, session, monkeypatch)
    excluded = [{"draft_id": composition["drafts"][2]["id"], "reason": "Need evidence"}]
    qualified = preview(auth_client, composition, excluded).json()
    sent = final_send(auth_client, composition, qualified, excluded=excluded)
    assert sent.status_code == 201, sent.text
    page = invitations(auth_client, activity)
    assert page["total"] == 3
    assert sorted(r["sending_state"] for r in page["items"]) == [
        "not_sent",
        "queued",
        "queued",
    ]
    third = next(r for r in page["items"] if r["sending_state"] == "not_sent")
    assert third["send_history"][0]["exclusion_reason"] == "Need evidence"
    assert third["send_history"][0]["delivery"] is None
    assert all(r["invitation_state"] == "not_invited" for r in page["items"])
    row = session.get(ActivitySelection, UUID(third["selection_id"]))
    row.active = False
    session.commit()
    assert invitations(auth_client, activity)["total"] == 3
    queued = invitations(
        auth_client, activity, sending_state="queued", limit=1, offset=1
    )
    assert queued["total"] == 2 and len(queued["items"]) == 1
    assert (
        queued["items"][0]["selection_id"]
        == [r for r in page["items"] if r["sending_state"] == "queued"][1][
            "selection_id"
        ]
    )


def test_creator_history_lists_default_selection_without_read_mutation(
    auth_client, session, monkeypatch
):
    activity, candidates = setup_selection(auth_client, session, monkeypatch, count=1)
    creator = str(candidates[0].creator_id)
    path = f"/api/v2/library/creators/{creator}/invitations"
    before = session.scalar(select(func.count()).select_from(Activity))
    response = auth_client.get(path)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["send_history"] == []
    selected = choose(auth_client, activity, candidates[0].id)
    result = auth_client.get(path).json()
    assert result["total"] == 1
    item = result["items"][0]
    assert item["selection_id"] == selected["id"]
    assert item["activity_name"] == session.get(Activity, UUID(activity)).name
    assert item["revision"] == 0 and item["notes"] == ""
    assert item["sending_state"] == "not_sent" and item["invited_at"] is None
    assert item["follow_up_state"] == "not_followed_up"
    assert item["cooperation_state"] == "not_started"
    assert item["responses"] == []
    assert (
        auth_client.get(path, params={"activity_id": str(uuid4())}).json()["total"] == 0
    )
    assert session.scalar(select(func.count()).select_from(Activity)) == before


def test_sending_unknown_is_visible_and_only_sent_implies_awaiting_response(
    auth_client, session, monkeypatch
):
    activity, composition = ready_composition(
        auth_client, session, monkeypatch, count=2
    )
    result = final_send(
        auth_client, composition, preview(auth_client, composition).json()
    ).json()
    first = session.get(ActivityDelivery, UUID(result["deliveries"][0]["id"]))
    first.state = "sent"
    first.sent_at = utc_now()
    second = session.get(ActivityDelivery, UUID(result["deliveries"][1]["id"]))
    second.state = "sending"
    second.lease_expires_at = utc_now() - timedelta(seconds=1)
    session.commit()
    page = invitations(auth_client, activity)
    rows = sorted(page["items"], key=lambda r: r["identity"]["account_id"])
    assert [r["sending_state"] for r in rows] == ["sent", "unknown"]
    assert [r["invitation_state"] for r in rows] == ["awaiting_response", "not_invited"]
    assert rows[0]["invited_at"] is not None
    assert rows[1]["invited_at"] is None
    assert invitations(auth_client, activity, sending_state="unknown")["total"] == 1


def detail(client, item):
    response = client.get(
        f"/api/v2/activities/{item['activity_id']}/invitations/{item['selection_id']}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def change(client, item, **fields):
    return post(
        client,
        f"/api/v2/activities/{item['activity_id']}/invitations/{item['selection_id']}/update",
        {"expected_revision": item["revision"], **fields},
    )


def respond(client, item, *, key=None, **fields):
    return post(
        client,
        f"/api/v2/activities/{item['activity_id']}/invitations/{item['selection_id']}/responses",
        {
            "expected_revision": item["revision"],
            "outcome": "accepted",
            "source_note": "Creator's reply forwarded by the producer.",
            "responded_at": "2026-09-08T03:00:00Z",
            **fields,
        },
        key=key,
    )


def test_manual_response_is_sourced_versioned_and_independent_across_activities(
    auth_client, session, monkeypatch
):
    from tests.integration.test_activity_api import (
        activity as new_activity,
        query,
        execute,
        provider_page,
    )
    from app.db.models.discovery import DiscoveryCandidate

    activity, candidates = setup_selection(auth_client, session, monkeypatch, count=1)
    choose(auth_client, activity, candidates[0].id)
    other = new_activity(auth_client)["id"]
    created_query = query(auth_client, other)
    execute(session, created_query["batch_id"], lambda request: provider_page([1]))
    candidate = session.scalar(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.query_id == UUID(created_query["query_id"])
        )
    )
    choose(auth_client, other, candidate.id)
    first = invitations(auth_client, activity)["items"][0]
    second = invitations(auth_client, other)["items"][0]
    assert first["creator_id"] == second["creator_id"]
    key = str(uuid4())
    response = respond(auth_client, first, key=key)
    assert response.status_code == 200, response.text
    accepted = response.json()
    assert accepted["invitation_state"] == "accepted"
    assert accepted["sending_state"] == "not_sent" and accepted["invited_at"] is None
    assert accepted["cooperation_state"] == "not_started"
    assert (
        accepted["responses"][0]["source_note"]
        == "Creator's reply forwarded by the producer."
    )
    assert accepted["responses"][0]["responded_at"].startswith("2026-09-08T03:00:00")
    assert accepted["responses"][0]["recorded_at"]
    assert respond(auth_client, first, key=key).json() == accepted
    assert respond(auth_client, first).status_code == 409
    assert detail(auth_client, second)["invitation_state"] == "not_invited"
    corrected = respond(
        auth_client,
        accepted,
        outcome="declined",
        source_note="Follow-up correction from the same Creator.",
    ).json()
    assert corrected["invitation_state"] == "declined"
    assert [r["outcome"] for r in corrected["responses"]] == ["declined", "accepted"]
    edited = change(
        auth_client,
        corrected,
        notes="Check again next quarter",
        follow_up_state="follow_up_needed",
    ).json()
    assert (
        edited["invitation_state"] == "declined"
        and edited["notes"] == "Check again next quarter"
    )
    assert len(edited["responses"]) == 2
    rows = auth_client.get(
        f"/api/v2/library/creators/{first['creator_id']}/invitations"
    ).json()
    assert rows["total"] == 2
    assert (
        invitations(
            auth_client,
            activity,
            invitation_state="declined",
            follow_up_state="follow_up_needed",
        )["total"]
        == 1
    )
    assert change(auth_client, accepted, notes="stale").status_code == 409


def test_four_follow_up_and_eight_cooperation_states_round_trip_without_implied_reply(
    auth_client, session, monkeypatch
):
    activity, candidates = setup_selection(auth_client, session, monkeypatch, count=1)
    choose(auth_client, activity, candidates[0].id)
    current = invitations(auth_client, activity)["items"][0]
    for state in (
        "not_followed_up",
        "follow_up_needed",
        "followed_up",
        "no_follow_up_needed",
    ):
        response = change(auth_client, current, follow_up_state=state)
        assert response.status_code == 200, response.text
        current = response.json()
        assert detail(auth_client, current)["follow_up_state"] == state
    for state in (
        "not_started",
        "in_discussion",
        "collaboration_confirmed",
        "in_production",
        "awaiting_publication",
        "published",
        "settled",
        "closed",
    ):
        response = change(auth_client, current, cooperation_state=state)
        assert response.status_code == 200, response.text
        current = response.json()
        assert current["cooperation_state"] == state
        assert (
            current["invitation_state"] == "not_invited" and current["responses"] == []
        )
    assert change(auth_client, current, cooperation_state="All").status_code == 422
    assert change(auth_client, current, follow_up_state=None).status_code == 422
    assert change(auth_client, current, invitation_state="accepted").status_code == 422
    assert change(auth_client, current).status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        {"source_note": " "},
        {"responded_at": None},
        {"responded_at": "2026-09-08T03:00:00"},
        {"outcome": "opened"},
    ],
)
def test_response_rejects_unsourced_or_inferred_claims(
    auth_client, session, monkeypatch, fields
):
    activity, candidates = setup_selection(auth_client, session, monkeypatch, count=1)
    choose(auth_client, activity, candidates[0].id)
    current = invitations(auth_client, activity)["items"][0]
    assert respond(auth_client, current, **fields).status_code == 422
    assert detail(auth_client, current)["revision"] == 0


@pytest.mark.parametrize("state", ["queued", "sending"])
def test_creator_rebind_blocks_new_pending_activity_delivery(
    auth_client, session, monkeypatch, state
):
    activity, composition = ready_composition(
        auth_client, session, monkeypatch, count=1
    )
    result = final_send(
        auth_client, composition, preview(auth_client, composition).json()
    ).json()
    delivery = session.get(ActivityDelivery, UUID(result["deliveries"][0]["id"]))
    delivery.state = state
    session.commit()
    creator = session.scalar(
        select(ActivitySelection).where(ActivitySelection.activity_id == UUID(activity))
    ).creator_id
    path = f"/api/v2/library/creators/{creator}"
    revision = auth_client.get(path).json()["revision"]
    payload = {
        "expected_revision": revision,
        "platform": "x",
        "account_id": "987654",
        "confirmed": True,
    }
    response = auth_client.put(path + "/identity", json=payload)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "creator_delivery_in_progress"
    delivery.state = "sent"
    delivery.sent_at = utc_now()
    session.commit()
    assert auth_client.put(path + "/identity", json=payload).status_code == 200
    row = auth_client.get(path + "/invitations").json()["items"][0]
    assert row["identity"]["account_id"] != "987654"
    assert (
        row["send_history"][0]["delivery"]["snapshot"]["recipient_email"]
        == "account-1@example.com"
    )


def test_new_discovery_and_batch_preserve_old_mail_response_and_list_order(
    auth_client, session, monkeypatch
):
    from tests.integration.test_activity_api import query, execute, provider_page
    from tests.integration.test_activity_recipient_batches import freeze
    from app.db.models.discovery import DiscoveryCandidate

    activity, composition = ready_composition(
        auth_client, session, monkeypatch, count=1
    )
    sent = final_send(
        auth_client, composition, preview(auth_client, composition).json()
    ).json()
    delivery = session.get(ActivityDelivery, UUID(sent["deliveries"][0]["id"]))
    delivery.state = "sent"
    delivery.sent_at = utc_now()
    session.commit()
    current = invitations(auth_client, activity)["items"][0]
    accepted = respond(auth_client, current).json()
    frozen_mail = accepted["send_history"]
    created = query(auth_client, activity)
    execute(session, created["batch_id"], lambda request: provider_page([2]))
    candidate = session.scalar(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.query_id == UUID(created["query_id"]),
            DiscoveryCandidate.creator_id != UUID(current["creator_id"]),
        )
    )
    added = choose(auth_client, activity, candidate.id)
    original = auth_client.get(
        f"/api/v2/activities/{activity}/selections/{current['selection_id']}"
    ).json()
    batch = freeze(auth_client, activity, [original, added])
    page = invitations(auth_client, activity)
    assert page["total"] == 2
    old = next(r for r in page["items"] if r["selection_id"] == current["selection_id"])
    assert (
        old["invitation_state"] == "accepted"
        and old["responses"] == accepted["responses"]
    )
    assert old["send_history"] == frozen_mail
    assert len(old["memberships"]) == 2
    membership = next(
        m for m in old["memberships"] if m["recipient_batch_id"] == batch["id"]
    )
    assert membership["input_order"] == 0
    assert invitations(auth_client, activity)["items"] == page["items"]
    canceled = post(
        auth_client,
        f"/api/v2/activities/{activity}/selections/{original['id']}/cancel",
        {"expected_revision": original["revision"]},
    )
    assert canceled.status_code == 200
    assert detail(auth_client, old)["send_history"] == frozen_mail


def test_collaboration_auth_scope_and_read_no_tracking_side_effects(
    auth_client, client, session, monkeypatch
):
    from app.db.models.activity_collaboration import (
        ActivityCollaboration,
        ActivityResponse,
    )
    from tests.integration.test_activity_api import activity as new_activity

    activity, candidates = setup_selection(auth_client, session, monkeypatch, count=1)
    choose(auth_client, activity, candidates[0].id)
    current = invitations(auth_client, activity)["items"][0]
    assert session.scalar(select(func.count()).select_from(ActivityCollaboration)) == 0
    assert session.scalar(select(func.count()).select_from(ActivityResponse)) == 0
    other = new_activity(auth_client)["id"]
    wrong = {**current, "activity_id": other}
    assert change(auth_client, wrong, notes="Cross activity").status_code == 404
    assert respond(auth_client, wrong).status_code == 404
    assert session.scalar(select(func.count()).select_from(ActivityResponse)) == 0
    client.headers.pop("Authorization", None)
    assert client.get(f"/api/v2/activities/{activity}/invitations").status_code == 401
    assert change(client, current, notes="Unauthorized").status_code == 401
    assert respond(client, current).status_code == 401


def test_retry_older_failed_delivery_is_not_masked_by_newer_failed_batch(
    auth_client, session, monkeypatch
):
    from app.db.models.activity_sending import ActivitySendBatch
    from tests.integration.test_outreach_drafts import compose, manual, confirm_facts

    activity, composition = ready_composition(
        auth_client, session, monkeypatch, count=1
    )
    first = final_send(
        auth_client, composition, preview(auth_client, composition).json()
    ).json()
    old = session.get(ActivityDelivery, UUID(first["deliveries"][0]["id"]))
    old.state, old.retryable, old.attempt = "failed", True, 1
    session.commit()
    fresh = compose(
        auth_client,
        activity,
        {"id": composition["recipient_batch_id"]},
        {"id": composition["template_version_id"]},
    ).json()
    draft = manual(auth_client, fresh["drafts"][0]).json()
    assert confirm_facts(auth_client, fresh["id"], [draft]).status_code == 200
    second = final_send(auth_client, fresh, preview(auth_client, fresh).json())
    assert second.status_code == 201, second.text
    newer = session.get(ActivityDelivery, UUID(second.json()["deliveries"][0]["id"]))
    newer.state, newer.retryable, newer.attempt = "failed", True, 1
    # Test transaction timestamps coincide; make the supported real request order explicit.
    session.get(ActivitySendBatch, UUID(second.json()["id"])).created_at = (
        utc_now() + timedelta(seconds=1)
    )
    session.commit()
    result = post(
        auth_client,
        f"/api/v2/outreach/deliveries/{old.id}/retry",
        {"expected_attempt": 1},
    )
    assert result.status_code == 200, result.text
    row = invitations(auth_client, activity)["items"][0]
    assert row["sending_state"] == "queued"
    assert len(row["send_history"]) == 2
    for state in ("sending", "unknown", "sent"):
        old.state = state
        old.sent_at = utc_now() if state == "sent" else None
        session.commit()
        row = invitations(auth_client, activity)["items"][0]
        assert row["sending_state"] == state
        assert invitations(auth_client, activity, sending_state=state)["total"] == 1
        assert row["invitation_state"] == (
            "awaiting_response" if state == "sent" else "not_invited"
        )
