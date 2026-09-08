"""Named subsets remain durable and read-only when discovery keeps growing."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.models.discovery import DiscoveryCandidate, DiscoveryQuery
from app.db.models.profiles import CreatorProfile
from tests.integration.test_candidate_query_options import setup_query


def post(client, query, members, *, name="Shortlist", request_id=None, key=None):
    return client.post(
        f"/api/v2/discovery/queries/{query.id}/saved-sets",
        json={
            "name": name,
            "candidate_ids": [str(c.id) for c in members],
            "request_id": str(request_id or uuid4()),
        },
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def fixtures(session):
    query, candidates = setup_query(session)
    creators = [session.get(CreatorProfile, c.creator_id) for c in candidates]
    session.commit()
    return query, creators, candidates


def test_save_replay_preserves_name_members_and_persistent_request(
    auth_client, session
):
    query, _, candidates = fixtures(session)
    request_id, key = uuid4(), uuid4()
    saved = post(
        auth_client,
        query,
        [candidates[1], candidates[0], candidates[1]],
        name="  First pass  ",
        request_id=request_id,
        key=key,
    )
    assert saved.status_code == 201, saved.text
    value = saved.json()
    assert value["name"] == "First pass"
    assert value["candidate_ids"] == [str(candidates[1].id), str(candidates[0].id)]
    assert value["count"] == 2
    for retry_key in [key, uuid4()]:
        replay = post(
            auth_client,
            query,
            [candidates[1], candidates[0], candidates[1]],
            name="  First pass  ",
            request_id=request_id,
            key=retry_key,
        )
        assert replay.status_code == 201, replay.text
        assert replay.json() == value
    assert (
        post(auth_client, query, candidates[:1], request_id=request_id).status_code
        == 409
    )
    read = auth_client.get(f"/api/v2/discovery/saved-sets/{value['id']}")
    assert read.json() == value
    listing = auth_client.get(f"/api/v2/activities/{query.activity_id}/saved-sets")
    assert listing.json()["total"] == 1


def test_subset_restore_keeps_cursor_progress_and_does_not_select_arrivals(
    auth_client, session
):
    query, _, candidates = fixtures(session)
    query.provider_states = {"youtube": {"status": "more", "cursor": {"token": "keep"}}}
    query.status = "paused"
    session.commit()
    saved = post(auth_client, query, candidates[:2])
    assert saved.status_code == 201, saved.text
    set_id = saved.json()["id"]
    extra_creator = CreatorProfile(
        platform="x",
        platform_account_id="late-arrival",
        sort_name="Late",
        canonical_url="https://x.com/late-arrival",
    )
    session.add(extra_creator)
    session.flush()
    session.add(
        DiscoveryCandidate(
            query_id=query.id,
            creator_id=extra_creator.id,
            platform="x",
            account_id="late-arrival",
            identity_revision=0,
            ordinal=5,
        )
    )
    query.result_count = 5
    session.commit()
    original_conditions = query.conditions.copy()
    restored = auth_client.get(
        f"/api/v2/discovery/saved-sets/{set_id}/results?sort=followers&limit=1"
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["total"] == 2
    assert restored.json()["items"][0]["id"] == str(candidates[1].id)
    assert not restored.json()["items"][0]["selected"]
    session.expire_all()
    assert session.get(DiscoveryQuery, query.id).provider_states["youtube"][
        "cursor"
    ] == {"token": "keep"}
    assert (
        query.status == "paused"
        and query.result_count == 5
        and query.conditions == original_conditions
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(DiscoveryCandidate)
            .where(DiscoveryCandidate.selected)
        )
        == 0
    )


def test_foreign_query_members_are_rejected_and_sets_stay_separate(
    auth_client, session
):
    query, _, candidates = fixtures(session)
    # Same Activity, different query; saved membership may never bleed across it.
    other = DiscoveryQuery(
        activity_id=query.activity_id,
        conditions=query.conditions,
        source_snapshot=query.source_snapshot,
    )
    session.add(other)
    session.flush()
    foreign = DiscoveryCandidate(
        query_id=other.id,
        creator_id=candidates[0].creator_id,
        platform=candidates[0].platform,
        account_id=candidates[0].account_id,
        identity_revision=0,
        ordinal=1,
    )
    session.add(foreign)
    session.commit()
    bad = post(auth_client, query, [candidates[0], foreign])
    assert bad.status_code == 422, bad.text
    assert (
        auth_client.get(f"/api/v2/activities/{query.activity_id}/saved-sets").json()[
            "total"
        ]
        == 0
    )
    first = post(auth_client, query, candidates[:1]).json()
    second = post(auth_client, other, [foreign]).json()
    assert first["query_id"] != second["query_id"]
    # The fixture shares one outer transaction, so database now() is identical.
    from app.db.models.saved_candidate_set import SavedCandidateSet

    first_row = session.get(SavedCandidateSet, UUID(first["id"]))
    second_row = session.get(SavedCandidateSet, UUID(second["id"]))
    second_row.created_at = first_row.created_at + timedelta(seconds=1)
    session.commit()
    listing = auth_client.get(
        f"/api/v2/activities/{query.activity_id}/saved-sets?limit=1"
    )
    assert listing.json()["total"] == 2
    assert listing.json()["items"][0]["id"] == second["id"]
    old = auth_client.get(f"/api/v2/discovery/saved-sets/{first['id']}/results").json()
    assert [c["id"] for c in old["items"]] == [str(candidates[0].id)]


def test_saved_results_filter_full_membership_and_flag_rebound_identity(
    auth_client, session
):
    query, creators, candidates = fixtures(session)
    saved = post(auth_client, query, candidates[:2])
    assert saved.status_code == 201, saved.text
    path = f"/api/v2/discovery/saved-sets/{saved.json()['id']}/results"
    filtered = auth_client.get(path + "?evidence=reference_game&limit=1").json()
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == str(
        candidates[1].id
    )
    creators[0].identity_revision += 1
    session.commit()
    restored = auth_client.get(path).json()
    assert restored["total"] == 2 and restored["items"][0]["identity_changed"]
    assert auth_client.get(path + "?evidence=current_game").json()["total"] == 0
    assert auth_client.get(path + "?sort=unsupported").status_code == 422


@pytest.mark.parametrize("name,members", [(" ", True), ("Empty", False)])
def test_invalid_save_has_no_partial_set(auth_client, session, name, members):
    query, _, candidates = fixtures(session)
    response = post(auth_client, query, candidates if members else [], name=name)
    assert response.status_code == 422, response.text
    assert (
        auth_client.get(f"/api/v2/activities/{query.activity_id}/saved-sets").json()[
            "total"
        ]
        == 0
    )


def test_saved_set_routes_require_auth_and_unknown_reads_are_404(
    client, workspace_access_key
):
    identity = uuid4()
    paths = [
        f"/api/v2/activities/{identity}/saved-sets",
        f"/api/v2/discovery/saved-sets/{identity}",
        f"/api/v2/discovery/saved-sets/{identity}/results",
    ]
    for path in paths:
        assert client.get(path).status_code == 401
        assert (
            client.get(
                path, headers={"Authorization": f"Bearer {workspace_access_key}"}
            ).status_code
            == 404
        )
    assert (
        client.post(
            f"/api/v2/discovery/queries/{identity}/saved-sets",
            json={
                "name": "N",
                "request_id": str(uuid4()),
                "candidate_ids": [str(uuid4())],
            },
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 401
    )
