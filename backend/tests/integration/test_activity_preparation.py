from uuid import UUID, uuid4

from sqlalchemy import select

from app.db.models.discovery import DiscoveryCandidate, DiscoveryQuery
from tests.integration.test_discovery_evaluation import seed_query
import pytest


def setup_selection(client, session, monkeypatch, count=2):
    query_id = seed_query(client, session, monkeypatch, count=count)
    query = session.get(DiscoveryQuery, UUID(query_id))
    candidates = list(
        session.scalars(
            select(DiscoveryCandidate)
            .where(DiscoveryCandidate.query_id == query.id)
            .order_by(DiscoveryCandidate.ordinal)
        )
    )
    return str(query.activity_id), candidates


def post(client, path, value, key=None):
    return client.post(
        path, json=value, headers={"Idempotency-Key": key or str(uuid4())}
    )


def choose(client, activity_id, candidate_id):
    response = post(
        client,
        f"/api/v2/activities/{activity_id}/selections",
        {"candidate_id": str(candidate_id)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_human_selection_persists_without_implying_send_readiness(
    auth_client, session, monkeypatch
):
    activity_id, candidates = setup_selection(auth_client, session, monkeypatch)
    path = f"/api/v2/activities/{activity_id}/selections"
    assert auth_client.get(path).json()["total"] == len(candidates)
    selected = choose(auth_client, activity_id, candidates[0].id)
    assert selected["active"]
    assert selected["identity"]["account_id"] == candidates[0].account_id
    assert selected["selected_contact"] is None
    assert selected["freeze_ready"] and not selected["send_ready"]
    assert not selected["sender_watched"]
    assert {
        "email_not_selected",
        "evaluation_missing",
        "evidence_missing",
        "public_name_unconfirmed",
    }.issubset(selected["missing_fields"])
    assert choose(auth_client, activity_id, candidates[0].id)["id"] == selected["id"]
    assert auth_client.get(path).json()["total"] == len(candidates)
    assert auth_client.get(f"{path}/{selected['id']}").json() == selected


def read(client, selected):
    response = client.get(
        f"/api/v2/activities/{selected['activity_id']}/selections/{selected['id']}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def update(client, selected, **changes):
    return post(
        client,
        f"/api/v2/activities/{selected['activity_id']}/selections/{selected['id']}/update",
        {
            "expected_revision": selected["revision"],
            "context_token": selected["context_token"],
            **changes,
        },
    )


def contacts(client, creator_id):
    path = f"/api/v2/library/creators/{creator_id}"
    for email, purpose in [
        ("press@example.com", "Press"),
        ("business@example.com", "Sponsorships"),
    ]:
        creator = client.get(path).json()
        result = post(
            client,
            path + "/contacts",
            {
                "expected_revision": creator["revision"],
                "email": email,
                "purpose": purpose,
                "source_url": "https://example.com/contact",
            },
        )
        assert result.status_code == 201, result.text
    return client.get(path).json()["contacts"]


def test_explicit_second_email_and_source_version_no_implicit_first(
    auth_client, session, monkeypatch
):
    activity_id, candidates = setup_selection(auth_client, session, monkeypatch)
    selected = choose(auth_client, activity_id, candidates[0].id)
    options = contacts(auth_client, selected["creator_id"])
    selected = read(auth_client, selected)
    assert (
        selected["selected_contact"] is None and len(selected["contact_options"]) == 2
    )
    second = next(c for c in options if c["email"] == "business@example.com")
    response = update(auth_client, selected, contact_id=second["id"])
    assert response.status_code == 200, response.text
    selected = response.json()
    assert selected["selected_contact"]["email"] == "business@example.com"
    assert selected["selected_contact"]["purpose"] == "Sponsorships"
    assert selected["selected_contact"]["source_url"] == "https://example.com/contact"
    assert selected["freeze_ready"] and not selected["send_ready"]
    assert "evaluation_missing" in selected["missing_fields"]
    # Source change invalidates a previous choice instead of silently switching it.
    path = f"/api/v2/library/creators/{selected['creator_id']}"
    revision = auth_client.get(path).json()["revision"]
    patched = auth_client.patch(
        path + f"/contacts/{second['id']}",
        json={"expected_revision": revision, "email": "changed@example.com"},
    )
    assert patched.status_code == 200, patched.text
    changed = read(auth_client, selected)
    assert (
        changed["contact_status"] == "changed"
        and "email_changed" in changed["missing_fields"]
    )
    assert changed["selected_contact"]["email"] == "business@example.com"
    assert update(auth_client, selected, contact_id=second["id"]).status_code == 409
    restored = update(auth_client, changed, contact_id=second["id"])
    assert restored.status_code == 200
    assert restored.json()["selected_contact"]["email"] == "changed@example.com"
    cleared = update(auth_client, restored.json(), contact_id=None)
    assert cleared.status_code == 200 and cleared.json()["selected_contact"] is None


def test_cancel_readd_and_cross_query_identity_dedup(auth_client, session, monkeypatch):
    from tests.integration.test_activity_api import query, execute, provider_page

    activity_id, candidates = setup_selection(auth_client, session, monkeypatch)
    selected = choose(auth_client, activity_id, candidates[0].id)
    another = query(auth_client, activity_id)
    execute(session, another["batch_id"], lambda request: provider_page([1]))
    candidate = session.scalar(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.query_id == UUID(another["query_id"]),
            DiscoveryCandidate.account_id == candidates[0].account_id,
        )
    )
    assert choose(auth_client, activity_id, candidate.id)["id"] == selected["id"]
    cancel = f"/api/v2/activities/{activity_id}/selections/{selected['id']}/cancel"
    response = post(auth_client, cancel, {"expected_revision": selected["revision"]})
    assert response.status_code == 200 and not response.json()["active"]
    assert (
        auth_client.get(f"/api/v2/activities/{activity_id}/selections").json()["total"]
        == len(candidates) - 1
    )
    assert choose(auth_client, activity_id, candidate.id)["id"] == selected["id"]
    assert (
        post(
            auth_client, cancel, {"expected_revision": selected["revision"]}
        ).status_code
        == 409
    )


def test_name_confirmation_binds_exact_name_and_identity(
    auth_client, session, monkeypatch
):
    activity_id, candidates = setup_selection(auth_client, session, monkeypatch)
    selected = choose(auth_client, activity_id, candidates[0].id)
    path = f"/api/v2/library/creators/{selected['creator_id']}"
    creator = auth_client.get(path).json()
    assert (
        auth_client.patch(
            path,
            json={
                "expected_revision": creator["revision"],
                "public_name": "Alex",
                "public_name_confirmed": True,
            },
        ).status_code
        == 200
    )
    selected = read(auth_client, selected)
    assert not selected["public_name_confirmed"]
    response = update(auth_client, selected, confirm_public_name=True)
    assert response.status_code == 200, response.text
    assert (
        response.json()["public_name_confirmed"]
        and response.json()["name_confirmed_at"]
    )
    creator = auth_client.get(path).json()
    assert (
        auth_client.patch(
            path,
            json={"expected_revision": creator["revision"], "public_name": "Avery"},
        ).status_code
        == 200
    )
    changed = read(auth_client, selected)
    assert not changed["public_name_confirmed"]
    assert (
        update(auth_client, response.json(), confirm_public_name=True).status_code
        == 409
    )
    confirmed = update(auth_client, changed, confirm_public_name=True).json()
    creator = auth_client.get(path).json()
    rebound = auth_client.put(
        path + "/identity",
        json={
            "expected_revision": creator["revision"],
            "platform": "x",
            "account_id": "123456789",
            "confirmed": True,
        },
    )
    assert rebound.status_code == 200, rebound.text
    changed = read(auth_client, confirmed)
    assert changed["identity_changed"] and not changed["public_name_confirmed"]
    assert (
        not changed["sender_watched"]
        and "identity_changed" in changed["missing_fields"]
    )
    assert update(auth_client, changed, confirm_public_name=True).status_code == 409


def test_attach_evaluation_and_known_works_without_fabricating_sender_facts(
    auth_client, session, monkeypatch
):
    from tests.integration.test_discovery_evaluation import (
        start,
        sessions_for,
        fixture_executor,
    )
    from app.workers.evaluation_tasks import run_evaluation
    from app.db.models.profiles import CreatorProfile

    activity_id, candidates = setup_selection(auth_client, session, monkeypatch)
    selected = choose(auth_client, activity_id, candidates[0].id)
    creator = session.get(CreatorProfile, candidates[0].creator_id)
    work = creator.works[0]
    work.manual_overrides = {
        "evidence_excerpt": "Recorded puzzle mechanics discussion.",
        "verification_notes": "Editor notes with source context.",
    }
    session.commit()
    run_id = start(auth_client, str(candidates[0].query_id))
    run_evaluation(
        run_id,
        session_factory=sessions_for(session),
        execute_model=fixture_executor([]),
    )
    selected = read(auth_client, selected)
    response = update(
        auth_client, selected, evaluation_run_id=run_id, work_ids=[str(work.id)]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evaluation"]["match_brief"]
    assert (
        body["works"][0]["evidence_excerpt"] == "Recorded puzzle mechanics discussion."
    )
    assert not body["sender_watched"] and not body["send_ready"]
    assert "work_relation_missing" in body["missing_fields"]
    assert "evaluation_missing" not in body["missing_fields"]


def test_foreign_activity_contact_and_work_references_are_rejected(
    auth_client, session, monkeypatch
):
    from app.db.models.profiles import CreatorProfile
    from tests.integration.test_discovery_evaluation import start

    activity_id, candidates = setup_selection(auth_client, session, monkeypatch)
    selected = choose(auth_client, activity_id, candidates[0].id)
    foreign_contacts = contacts(auth_client, str(candidates[1].creator_id))
    selected = read(auth_client, selected)
    assert (
        update(auth_client, selected, contact_id=foreign_contacts[0]["id"]).status_code
        == 422
    )
    creator = session.get(CreatorProfile, candidates[1].creator_id)
    assert (
        update(auth_client, selected, work_ids=[str(creator.works[0].id)]).status_code
        == 422
    )
    other_activity, other_candidates = setup_selection(
        auth_client, session, monkeypatch
    )
    assert (
        post(
            auth_client,
            f"/api/v2/activities/{other_activity}/selections",
            {"candidate_id": str(candidates[0].id)},
        ).status_code
        == 422
    )
    foreign_run = start(auth_client, str(other_candidates[0].query_id))
    assert (
        update(
            auth_client, read(auth_client, selected), evaluation_run_id=foreign_run
        ).status_code
        == 422
    )
    independent = choose(auth_client, other_activity, other_candidates[0].id)
    assert independent["id"] != selected["id"]


def test_explicit_bulk_selection_covers_loaded_pages_without_auto_additions(
    auth_client, session, monkeypatch
):
    activity_id, candidates = setup_selection(
        auth_client, session, monkeypatch, count=100
    )
    path = f"/api/v2/activities/{activity_id}/selections/bulk"
    initial = auth_client.get(
        f"/api/v2/activities/{activity_id}/selections", params={"limit": 100}
    ).json()
    assert initial["total"] == 100
    assert post(auth_client, path, {"cancel_selections": [
        {"selection_id": item["id"], "expected_revision": item["revision"]}
        for item in initial["items"]
    ]}).status_code == 200
    response = post(
        auth_client, path, {"add_candidate_ids": [str(c.id) for c in candidates[:75]]}
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["added_selection_ids"]) == 75
    listed = auth_client.get(
        f"/api/v2/activities/{activity_id}/selections", params={"limit": 100}
    ).json()
    assert listed["total"] == 75
    assert {r["candidate_id"] for r in listed["items"]} == {
        str(c.id) for c in candidates[:75]
    }
    cancel = [
        {"selection_id": s["id"], "expected_revision": s["revision"]}
        for s in listed["items"][:2]
    ]
    response = post(auth_client, path, {"cancel_selections": cancel})
    assert response.status_code == 200, response.text
    assert (
        auth_client.get(f"/api/v2/activities/{activity_id}/selections").json()["total"]
        == 73
    )
    # One foreign ID must roll back the whole explicit bulk request.
    response = post(
        auth_client, path, {"add_candidate_ids": [str(candidates[-1].id), str(uuid4())]}
    )
    assert response.status_code == 404
    assert (
        auth_client.get(f"/api/v2/activities/{activity_id}/selections").json()["total"]
        == 73
    )


@pytest.mark.parametrize("state", ["inactive", "invalid", "historical"])
def test_ineligible_email_remains_visible_but_cannot_be_chosen(
    auth_client, session, monkeypatch, state
):
    from app.db.models.profiles import CreatorProfile

    activity_id, candidates = setup_selection(auth_client, session, monkeypatch)
    selection = choose(auth_client, activity_id, candidates[0].id)
    options = contacts(auth_client, selection["creator_id"])
    creator = session.get(CreatorProfile, UUID(selection["creator_id"]))
    contact = next(c for c in creator.contacts if str(c.id) == options[0]["id"])
    if state == "inactive":
        contact.is_active = False
    elif state == "invalid":
        contact.email = "not-an-email"
    else:
        contact.identity_revision += 1
    session.commit()
    current = read(auth_client, selection)
    assert (
        next(c for c in current["contact_options"] if c["id"] == str(contact.id))[
            "status"
        ]
        == state
    )
    assert update(auth_client, current, contact_id=str(contact.id)).status_code == 422


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("GET", "selections"),
        ("POST", "selections"),
        ("POST", "selections/bulk"),
        ("GET", "selections/{id}"),
        ("POST", "selections/{id}/update"),
        ("POST", "selections/{id}/cancel"),
        ("GET", "recipient-batches"),
        ("POST", "recipient-batches"),
        ("GET", "recipient-batches/{id}"),
    ],
)
def test_preparation_routes_require_auth(client, method, suffix):
    path = f"/api/v2/activities/{uuid4()}/" + suffix.format(id=uuid4())
    assert client.request(method, path, json={}).status_code == 401


def test_update_retry_is_exact_and_cannot_assert_sender_watched(
    auth_client, session, monkeypatch
):
    activity_id, candidates = setup_selection(auth_client, session, monkeypatch)
    selected = choose(auth_client, activity_id, candidates[0].id)
    path = f"/api/v2/activities/{activity_id}/selections/{selected['id']}/update"
    value = {
        "expected_revision": selected["revision"],
        "context_token": selected["context_token"],
        "contact_id": None,
    }
    key = str(uuid4())
    response = post(auth_client, path, value, key=key)
    assert response.status_code == 200
    assert post(auth_client, path, value, key=key).json() == response.json()
    assert (
        post(
            auth_client, path, {**value, "confirm_public_name": False}, key=key
        ).status_code
        == 409
    )
    assert post(auth_client, path, {**value, "sender_watched": True}).status_code == 422


def test_old_identity_selection_can_be_cancelled_without_moving_preparation(
    auth_client, session, monkeypatch
):
    from app.db.models.profiles import CreatorProfile

    activity_id, candidates = setup_selection(auth_client, session, monkeypatch)
    selected = choose(auth_client, activity_id, candidates[0].id)
    creator = session.get(CreatorProfile, candidates[0].creator_id)
    creator.identity_revision += 1
    creator.platform_account_id = "987654321"
    session.commit()
    assert (
        post(
            auth_client,
            f"/api/v2/activities/{activity_id}/selections",
            {"candidate_id": str(candidates[0].id)},
        ).status_code
        == 409
    )
    response = post(
        auth_client,
        f"/api/v2/activities/{activity_id}/selections/{selected['id']}/cancel",
        {"expected_revision": selected["revision"]},
    )
    assert response.status_code == 200 and not response.json()["active"]
