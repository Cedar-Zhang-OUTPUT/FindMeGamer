from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from sqlalchemy import select, func

from app.db.models.discovery import Activity
from app.db.models.outreach import Delivery
from app.db.models.profiles import CreatorProfile, GameProfile
from app.db.models.activity_outreach import RecipientSnapshot
from app.db.models.settings import SharedSettings
from tests.integration.test_activity_recipient_batches import prepared, freeze
from tests.integration.test_activity_preparation import read, update, post


def draft_setup(client, session, monkeypatch, count=3):
    activity_id, choices = prepared(client, session, monkeypatch, count=count)
    updated = []
    for index, old in enumerate(choices):
        person = session.get(CreatorProfile, UUID(old["creator_id"]))
        person.manual_overrides = person.manual_overrides | {
            "public_name": f"Creator {index + 1}"
        }
        work = person.works[0]
        work.manual_overrides = {
            "content_title": f"Video {index + 1}",
            "source_url": f"https://example.com/videos/{index + 1}",
        }
        if index != 2:
            work.manual_overrides |= {
                "evidence_excerpt": "The presenter contrasts a quiet station with a sudden reveal.",
                "verification_notes": "Editor reviewed the video scene and retained this note.",
                "timestamp_seconds": 42,
            }
        session.commit()
        response = update(
            client,
            read(client, old),
            contact_id=None if index == 1 else old["selected_contact"]["id"],
            work_ids=[str(work.id)],
            confirm_public_name=True,
        )
        assert response.status_code == 200, response.text
        updated.append(response.json())
    batch = freeze(client, activity_id, updated)
    activity = session.get(Activity, UUID(activity_id))
    template = post(
        client,
        "/api/v2/outreach/template-versions/canonical",
        {"game_id": str(activity.game_id)},
    )
    assert template.status_code == 201, template.text
    return activity_id, updated, batch, template.json()


def compose(client, activity_id, batch, template, *, request_id=None, key=None):
    return post(
        client,
        f"/api/v2/activities/{activity_id}/compositions",
        {
            "request_id": str(request_id or uuid4()),
            "recipient_batch_id": batch["id"],
            "template_version_id": template["id"],
        },
        key=key,
    )


def get_compose(client, identity):
    response = client.get(f"/api/v2/outreach/compositions/{identity}")
    assert response.status_code == 200, response.text
    return response.json()


def values_for(draft):
    return {
        "firstName": draft["input"]["public_name"],
        "channelName": draft["input"]["channel_name"],
        "reference": draft["input"]["reference"],
        "observation": "contrasted the quiet station with the sudden reveal.",
    }


def manual(client, draft, values=None):
    return client.patch(
        f"/api/v2/outreach/drafts/{draft['id']}",
        json={
            "expected_revision": draft["revision"],
            "context_token": draft["context_token"],
            "values": values or values_for(draft),
        },
    )


def test_composition_preserves_all_members_and_original_snapshots(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(auth_client, session, monkeypatch)
    snapshots = {
        r.id: deepcopy(r.snapshot) for r in session.scalars(select(RecipientSnapshot))
    }
    request_id, key = uuid4(), str(uuid4())
    response = compose(
        auth_client, activity, batch, template, request_id=request_id, key=key
    )
    assert response.status_code == 201, response.text
    composition = response.json()
    assert composition["recipient_count"] == 3 and not composition["send_ready"]
    assert [d["recipient_snapshot_id"] for d in composition["drafts"]] == [
        r["id"] for r in batch["recipients"]
    ]
    assert [d["status"] for d in composition["drafts"]] == [
        "pending",
        "pending",
        "needs_repair",
    ]
    assert "email_not_selected" in composition["drafts"][1]["missing_fields"]
    assert "observation_evidence_missing" in composition["drafts"][2]["missing_fields"]
    assert not any(d["sender_facts_valid"] for d in composition["drafts"])
    for replay_key in (key, str(uuid4())):
        assert (
            compose(
                auth_client,
                activity,
                batch,
                template,
                request_id=request_id,
                key=replay_key,
            ).json()
            == composition
        )
    assert get_compose(auth_client, composition["id"]) == composition
    assert (
        auth_client.get(f"/api/v2/activities/{activity}/compositions").json()["total"]
        == 1
    )
    assert {
        r.id: r.snapshot for r in session.scalars(select(RecipientSnapshot))
    } == snapshots
    assert session.scalar(select(func.count()).select_from(Delivery)) == 0


def test_manual_four_slots_render_bound_sources_without_sender_confirmation(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    response = compose(auth_client, activity, batch, template)
    assert response.status_code == 201, response.text
    draft = response.json()["drafts"][0]
    edited = manual(auth_client, draft)
    assert edited.status_code == 200, edited.text
    item = edited.json()
    assert (
        item["status"] == "succeeded"
        and not item["send_ready"]
        and not item["sender_facts_valid"]
    )
    assert item["rendered"]["fixed_hash"] == template["fixed_hash"]
    assert set(item["slot_sources"]) == {
        "firstName",
        "channelName",
        "reference",
        "observation",
    }
    assert (
        item["slot_sources"]["observation"]["source_url"]
        == "https://example.com/videos/1"
    )
    assert (
        "Choice=" not in item["rendered"]["html"]
        and "Yes, I'm in" not in item["rendered"]["html"]
    )
    assert manual(auth_client, draft).status_code == 409
    override = values_for(item) | {
        "reference": "Another recorded work",
        "firstName": "Channel team",
    }
    changed = manual(auth_client, item, override)
    assert changed.status_code == 200, changed.text
    assert changed.json()["values"] == override
    assert changed.json()["input"]["reference"] != override["reference"]


def test_game_edit_refresh_keeps_frozen_discovery_and_members(
    auth_client, session, monkeypatch
):
    activity_id, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    response = compose(auth_client, activity_id, batch, template)
    assert response.status_code == 201, response.text
    composition = response.json()
    draft = manual(auth_client, composition["drafts"][0]).json()
    activity = session.get(Activity, UUID(activity_id))
    original_source = deepcopy(activity.source_snapshot)
    game = session.get(GameProfile, activity.game_id)
    game.manual_overrides = game.manual_overrides | {
        "description": "Corrected current game details"
    }
    session.commit()
    changed = get_compose(auth_client, composition["id"])["drafts"][0]
    assert changed["source_changed"] and not changed["sender_facts_valid"]
    assert manual(auth_client, draft).status_code == 409
    refreshed = post(
        auth_client,
        f"/api/v2/outreach/drafts/{changed['id']}/refresh",
        {
            "expected_revision": changed["revision"],
            "context_token": changed["context_token"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    assert not refreshed.json()["source_changed"]
    assert (
        refreshed.json()["input"]["game"]["description"]
        == "Corrected current game details"
    )
    assert refreshed.json()["values"] == draft["values"]
    assert activity.source_snapshot == original_source
    assert get_compose(auth_client, composition["id"])["recipient_count"] == 1
    assert (
        auth_client.get(
            f"/api/v2/activities/{activity_id}/recipient-batches/{batch['id']}"
        ).json()["recipients"][0]["snapshot"]
        == batch["recipients"][0]["snapshot"]
    )


def test_template_game_mismatch_does_not_repurpose_recipient_batch(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    other = GameProfile(
        canonical_url="https://example.com/another-game", sort_name="Another"
    )
    session.add(other)
    session.commit()
    foreign = post(
        auth_client,
        "/api/v2/outreach/template-versions/canonical",
        {"game_id": str(other.id)},
    ).json()
    response = compose(auth_client, activity, batch, foreign)
    assert response.status_code == 422, response.text
    assert (
        auth_client.get(f"/api/v2/activities/{activity}/compositions").json()["total"]
        == 0
    )


def confirm_facts(client, composition_id, drafts, **changes):
    return post(
        client,
        f"/api/v2/outreach/compositions/{composition_id}/sender-facts",
        {
            "members": [
                {
                    "draft_id": d["id"],
                    "expected_revision": d["revision"],
                    "context_token": d["context_token"],
                }
                for d in drafts
            ],
            "following": True,
            "enjoyed": True,
            "liked": True,
            **changes,
        },
    )


def test_sender_facts_require_explicit_members_and_invalidate_on_edit(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=2
    )
    settings = session.scalar(select(SharedSettings))
    settings.service_connection_state = {
        "smtp": {
            "username": "producer@example.com",
            "from_name": "Toki",
            "reply_to": "producer@example.com",
        }
    }
    session.commit()
    template = post(
        auth_client,
        "/api/v2/outreach/template-versions/canonical",
        {"game_id": template["game_id"]},
    ).json()
    composition = compose(auth_client, activity, batch, template).json()
    draft = manual(auth_client, composition["drafts"][0]).json()
    assert not draft["sender_facts_valid"]
    response = confirm_facts(auth_client, composition["id"], [draft])
    assert response.status_code == 200, response.text
    first, second = response.json()["drafts"]
    assert first["sender_facts_valid"] and not first["send_ready"]
    assert (
        first["sender_facts"]["following"]
        and first["sender_facts"]["enjoyed"]
        and first["sender_facts"]["liked"]
    )
    assert not second["sender_facts_valid"] and not second["sender_facts"]
    changed = manual(
        auth_client,
        first,
        values_for(first) | {"observation": "contrasted silence with a sudden reveal."},
    ).json()
    assert not changed["sender_facts_valid"]
    assert confirm_facts(auth_client, composition["id"], [first]).status_code == 409


def test_sender_facts_without_smtp_are_recorded_but_not_valid_for_sending(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    composition = compose(auth_client, activity, batch, template).json()
    draft = manual(auth_client, composition["drafts"][0]).json()
    response = confirm_facts(auth_client, composition["id"], [draft])
    assert response.status_code == 200, response.text
    assert response.json()["drafts"][0]["sender_facts"]["enjoyed"]
    assert not response.json()["drafts"][0]["sender_facts_valid"]


def test_sender_change_invalidates_confirmation_and_wrong_member_is_atomic(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    settings = session.scalar(select(SharedSettings))
    settings.service_connection_state = {"smtp": {"username": "producer@example.com"}}
    session.commit()
    composition = compose(auth_client, activity, batch, template).json()
    draft = manual(auth_client, composition["drafts"][0]).json()
    foreign = compose(auth_client, activity, batch, template).json()
    other = manual(auth_client, foreign["drafts"][0]).json()
    assert (
        confirm_facts(auth_client, composition["id"], [draft, other]).status_code == 422
    )
    assert not get_compose(auth_client, composition["id"])["drafts"][0]["sender_facts"]
    response = confirm_facts(auth_client, composition["id"], [draft])
    assert (
        response.status_code == 200
        and response.json()["drafts"][0]["sender_facts_valid"]
    )
    settings.service_connection_state = {"smtp": {"username": "another@example.com"}}
    session.commit()
    changed = get_compose(auth_client, composition["id"])["drafts"][0]
    assert changed["source_changed"] and not changed["sender_facts_valid"]


def test_draft_routes_require_workspace_auth(client):
    identity = uuid4()
    for path in (
        f"/api/v2/activities/{identity}/compositions",
        f"/api/v2/outreach/compositions/{identity}",
    ):
        assert client.get(path).status_code == 401
    for method, path in (
        ("post", f"/api/v2/activities/{identity}/compositions"),
        ("patch", f"/api/v2/outreach/drafts/{identity}"),
        ("post", f"/api/v2/outreach/drafts/{identity}/refresh"),
        ("post", f"/api/v2/outreach/drafts/{identity}/retry"),
        ("post", f"/api/v2/outreach/compositions/{identity}/sender-facts"),
    ):
        assert getattr(client, method)(path, json={}).status_code == 401


def test_real_bracketed_title_remains_exact_through_manual_draft(
    auth_client, session, monkeypatch
):
    activity, choices, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    creator = session.get(CreatorProfile, UUID(choices[0]["creator_id"]))
    work = creator.works[0]
    work.manual_overrides = work.manual_overrides | {
        "content_title": "LIMINAL: Within [Full Playthrough]"
    }
    session.commit()
    composition = compose(auth_client, activity, batch, template).json()
    response = manual(auth_client, composition["drafts"][0])
    assert response.status_code == 200, response.text
    assert (
        response.json()["values"]["reference"] == "LIMINAL: Within [Full Playthrough]"
    )
    assert "LIMINAL: Within [Full Playthrough]" in response.json()["rendered"]["text"]


def test_incomplete_unconfirmed_draft_saves_reopens_previews_and_stays_unsendable(
    auth_client, session, monkeypatch
):
    activity, choices, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=3
    )
    creator = session.get(CreatorProfile, UUID(choices[2]["creator_id"]))
    creator.manual_overrides = creator.manual_overrides | {"public_name": None}
    session.commit()
    original = deepcopy(creator.manual_overrides)
    composition = compose(auth_client, activity, batch, template).json()
    draft = composition["drafts"][2]
    values = {
        "firstName": "",
        "channelName": "Channel team",
        "reference": "",
        "observation": "a draft fragment",
    }
    response = manual(auth_client, draft, values)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "needs_repair"
    assert (
        result["values"] == values
        and result["rendered"]["fixed_hash"] == template["fixed_hash"]
    )
    assert not result["sender_facts_valid"] and result["sender_facts"] == {}
    assert get_compose(auth_client, composition["id"])["drafts"][2] == result
    from app.outreach.activity_qualification import qualify

    qualified = qualify(session, UUID(composition["id"]), [])
    member = qualified["members"][2]
    assert member["values"] == values and member["status"] == "needs_repair"
    assert "draft_not_complete" in member["missing_fields"]
    assert not qualified["send_ready"]
    session.refresh(creator)
    assert creator.manual_overrides == original
    assert (
        get_compose(auth_client, composition["id"])["drafts"][0]
        == composition["drafts"][0]
    )


@pytest.mark.parametrize(
    "field,replacement,invalidated",
    [
        ("firstName", "Team", set()),
        ("firstName", "", set()),
        ("channelName", "Another channel", {"following"}),
        ("reference", "Another work", {"enjoyed", "liked"}),
        ("observation", "another observation.", {"liked"}),
    ],
)
def test_manual_edit_invalidates_only_related_sender_facts(
    auth_client, session, monkeypatch, field, replacement, invalidated
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    settings = session.scalar(select(SharedSettings))
    settings.service_connection_state = {"smtp": {"username": "producer@example.com"}}
    session.commit()
    composition = compose(auth_client, activity, batch, template).json()
    draft = manual(auth_client, composition["drafts"][0]).json()
    confirmed = confirm_facts(auth_client, composition["id"], [draft]).json()["drafts"][
        0
    ]
    result = manual(auth_client, confirmed, confirmed["values"] | {field: replacement})
    assert result.status_code == 200, result.text
    item = result.json()
    assert {
        key
        for key in ("following", "enjoyed", "liked")
        if not item["sender_facts"][key]
    } == invalidated
    assert item["sender_facts"]["at"] == confirmed["sender_facts"]["at"]
    assert (
        item["sender_facts"]["fingerprint"] != confirmed["sender_facts"]["fingerprint"]
    )
    assert item["sender_facts_valid"] == (not invalidated and replacement != "")


def test_automatic_work_prefill_uses_library_without_changing_selection(
    auth_client, session, monkeypatch
):
    activity, choices, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    from app.db.models.activity_outreach import ActivitySelection

    selection = session.get(ActivitySelection, UUID(choices[0]["id"]))
    selection.work_ids = []
    creator = session.get(CreatorProfile, selection.creator_id)
    creator.manual_overrides = creator.manual_overrides | {"public_name": None}
    session.commit()
    composition = compose(auth_client, activity, batch, template).json()
    draft = composition["drafts"][0]
    assert (
        draft["input"]["prefill_values"]["firstName"] == draft["input"]["channel_name"]
    )
    assert draft["input"]["prefill_values"]["reference"] == "Video 1"
    assert draft["input"]["work"]["evidence_kind"] == "manual_note"
    assert not draft["sender_facts_valid"]
    session.refresh(selection)
    assert selection.work_ids == []
