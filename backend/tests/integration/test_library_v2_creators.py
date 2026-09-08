from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.models.profiles import CreatorProfile, CreatorContact
from tests.integration.test_profiles_api import add_creator

URL = "/api/v2/library/creators"


def post(client, path=URL, payload=None, key=None):
    return client.post(
        path, json=payload or {}, headers={"Idempotency-Key": key or str(uuid4())}
    )


def new_creator(client, **fields):
    response = post(client, payload={"platform": "x", "account_id": "123456", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def edit(client, creator, **fields):
    return client.patch(
        f"{URL}/{creator['id']}",
        json={"expected_revision": creator["revision"], **fields},
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", URL),
        ("POST", URL),
        ("GET", f"{URL}/{uuid4()}"),
        ("PATCH", f"{URL}/{uuid4()}"),
    ],
)
def test_creator_library_auth(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize(
    "platform,account",
    [
        ("youtube", "UCtestcreator123"),
        ("x", "12345"),
        ("twitch", "12345"),
        ("instagram", "studio.gamer"),
    ],
)
def test_each_platform_manual_account_is_persisted_without_fake_analysis(
    auth_client, session, platform, account
):
    creator = new_creator(
        auth_client, platform=platform, account_id=account, name="Same Name"
    )
    assert creator["platform"] == platform
    assert creator["source_identity"]["account_id"] == account
    assert creator["source_fields"]["name"] is None
    assert creator["last_analyzed_at"] is None
    row = session.get(CreatorProfile, UUID(creator["id"]))
    assert row.current_facts == {} and row.brief == {}
    assert row.youtube_channel_id == (account if platform == "youtube" else None)
    assert auth_client.get(f"{URL}/{creator['id']}").json() == creator


def test_platform_accounts_never_merge_by_name_and_duplicate_identity_conflicts(
    auth_client,
):
    one = new_creator(auth_client, name="Same")
    two = new_creator(auth_client, platform="twitch", name="Same")
    assert one["id"] != two["id"]
    duplicate = post(
        auth_client, payload={"platform": "x", "account_id": "123456", "name": "Other"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "creator_identity_conflict"


def test_creator_creation_requires_platform_identity_not_name(auth_client):
    assert post(auth_client, payload={"name": "No identity"}).status_code == 422
    assert (
        post(
            auth_client, payload={"platform": "x", "profile_url": "https://x.com/gamer"}
        ).status_code
        == 201
    )


def test_creator_create_retries_are_idempotent(auth_client):
    key = str(uuid4())
    payload = {"platform": "twitch", "account_id": "555"}
    first = post(auth_client, payload=payload, key=key)
    assert first.status_code == 201
    assert post(auth_client, payload=payload, key=key).json() == first.json()
    assert (
        post(auth_client, payload={**payload, "name": "Changed"}, key=key).status_code
        == 409
    )


def test_repeated_unresolved_profile_url_is_not_a_second_account(auth_client):
    payload = {"platform": "twitch", "profile_url": "https://www.twitch.tv/gamer"}
    assert post(auth_client, payload=payload).status_code == 201
    duplicate = post(auth_client, payload=payload)
    assert duplicate.status_code == 409


def test_manual_youtube_seed_still_needs_real_initial_analysis(auth_client):
    creator = new_creator(auth_client, platform="youtube", account_id="UCnewmanual123")
    response = post(
        auth_client,
        "/api/v1/jobs/analysis",
        {
            "target_type": "creator",
            "url": "https://www.youtube.com/channel/UCnewmanual123",
            "mode": "create",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["outcome"] == "job"
    assert auth_client.get(f"{URL}/{creator['id']}").json()["last_analyzed_at"] is None


def test_full_business_edit_keeps_source_and_identity(auth_client, session):
    row = add_creator(session, channel_id="UCsource123", name="Source")
    row.current_facts = {"title": "Source", "subscriber_count": 1200, "country": "US"}
    row.manual_notes = "Existing note"
    session.flush()
    original = auth_client.get(f"{URL}/{row.id}").json()
    assert original["internal_notes"] == "Existing note"
    result = edit(
        auth_client,
        original,
        name="Human",
        public_name="Alex",
        public_name_confirmed=True,
        handle="new_handle",
        profile_url="https://studio.example/creator",
        follower_count=0,
        follower_count_collected_at="2026-09-08T00:00:00Z",
        languages=["English"],
        country_code="CA",
        country_name="Canada",
        description="About",
        source_notes="Owner supplied",
        internal_notes="Keep",
        interest_notes="Specific interest",
        other_contacts=[{"label": "Discord", "value": "gamer"}],
        favorite=True,
    )
    assert result.status_code == 200, result.text
    creator = result.json()
    assert creator["name"] == "Human" and creator["follower_count"] == 0
    assert creator["source_fields"]["name"] == "Source"
    assert creator["source_identity"] == original["source_identity"]
    assert row.current_facts["title"] == "Source"
    assert edit(auth_client, original, name="Stale").status_code == 409
    reset = edit(
        auth_client, creator, reset_fields=["name", "follower_count"], description=None
    ).json()
    assert reset["name"] == "Source" and reset["follower_count"] == 1200
    assert reset["description"] is None
    assert edit(auth_client, reset, platform="twitch").status_code == 422
    assert edit(auth_client, reset, account_id="456").status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("follower_count", -1),
        ("follower_count", 2.5),
        ("follower_count", True),
        ("profile_url", "javascript:alert(1)"),
        ("country_code", "UNKNOWN"),
    ],
)
def test_creator_invalid_fields_do_not_write(auth_client, field, value):
    creator = new_creator(auth_client)
    assert edit(auth_client, creator, **{field: value}).status_code == 422
    assert auth_client.get(f"{URL}/{creator['id']}").json() == creator


def test_multiple_contacts_edit_source_layers_and_archive(auth_client, session):
    creator = new_creator(auth_client)
    path = f"{URL}/{creator['id']}/contacts"
    first = post(
        auth_client,
        path,
        {
            "expected_revision": creator["revision"],
            "email": "business@example.com",
            "purpose": "Business",
            "source_url": "https://studio.example/contact",
        },
    )
    assert first.status_code == 201, first.text
    creator = first.json()
    second = post(
        auth_client,
        path,
        {
            "expected_revision": creator["revision"],
            "email": "press@example.com",
            "purpose": "Press",
        },
    )
    assert second.status_code == 201, second.text
    creator = second.json()
    assert len([c for c in creator["contacts"] if c["is_active"]]) == 2
    duplicate = post(
        auth_client,
        path,
        {"expected_revision": creator["revision"], "email": "BUSINESS@example.com"},
    )
    assert duplicate.status_code == 409
    sourced = CreatorContact(
        creator_id=UUID(creator["id"]),
        email="old@example.com",
        purpose="Old purpose",
        source_type="youtube",
        is_manual=False,
        source_fields={
            "email": "old@example.com",
            "purpose": "Old purpose",
            "source_url": "https://youtube.com/about",
            "validation_state": "valid",
            "is_active": True,
        },
    )
    session.add(sourced)
    session.flush()
    changed = auth_client.patch(
        f"{path}/{sourced.id}",
        json={
            "expected_revision": creator["revision"],
            "email": "new@example.com",
            "purpose": "Agency",
            "verification_notes": "Confirmed by colleague",
        },
    )
    assert changed.status_code == 200, changed.text
    contact = next(c for c in changed.json()["contacts"] if c["id"] == str(sourced.id))
    assert (
        contact["email"] == "new@example.com"
        and contact["source_fields"]["email"] == "old@example.com"
    )
    assert contact["origin"] == "source" and contact["validation_state"] == "unverified"
    assert sourced.email == "new@example.com"
    hidden = auth_client.patch(
        f"{path}/{sourced.id}",
        json={"expected_revision": changed.json()["revision"], "is_active": False},
    )
    assert hidden.status_code == 200 and sourced.is_active is False


def test_work_manual_evidence_and_search_are_structured_not_inferred(auth_client):
    creator = new_creator(auth_client, name="Creator")
    path = f"{URL}/{creator['id']}/works"
    payload = {
        "expected_identity_revision": 0,
        "work_name": "Liminal",
        "content_title": "A quick look",
        "source_url": "https://x.com/gamer/status/777",
        "content_id": "777",
        "published_at": "2026-09-01T00:00:00Z",
        "collected_at": "2026-09-08T00:00:00Z",
        "metrics": [{"name": "views", "value": 12}],
        "verification_notes": "Metadata only",
    }
    key = str(uuid4())
    response = post(auth_client, path, payload, key)
    assert response.status_code == 201, response.text
    work = response.json()
    assert work["origin"] == "manual" and work["source_fields"] == {}
    assert work["content_type"] == "unverified" and work["game_id"] is None
    assert post(auth_client, path, payload, key).json() == work
    updated = auth_client.patch(
        f"{path}/{work['id']}",
        json={
            "expected_revision": work["revision"],
            "content_type": "review",
            "evidence_excerpt": "At 1:20 the creator explains the controls",
            "timestamp_seconds": 80,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["origin"] == "manual"
    assert (
        auth_client.patch(
            f"{path}/{work['id']}",
            json={"expected_revision": work["revision"], "work_name": "Lost update"},
        ).status_code
        == 409
    )
    assert auth_client.get(path).json()["total"] == 1
    assert (
        auth_client.get(URL, params={"query": "liminal", "platform": "x"}).json()[
            "items"
        ][0]["id"]
        == creator["id"]
    )
    assert auth_client.get(URL, params={"platform": "twitch"}).json()["total"] == 0


def test_x_not_exposed_to_old_api_but_available_to_scheduler(auth_client, session):
    from datetime import UTC, datetime, timedelta
    from app.repositories.profiles import ProfilesRepository

    creator = new_creator(auth_client)
    row = session.get(CreatorProfile, UUID(creator["id"]))
    row.next_analysis_at = datetime.now(UTC) - timedelta(days=1)
    session.flush()
    assert auth_client.get(f"/api/v1/profiles/creators/{row.id}").status_code == 404
    assert all(
        item["id"] != str(row.id)
        for item in auth_client.get("/api/v1/profiles/creators").json()["items"]
    )
    assert any(
        item.profile_id == row.id and item.canonical_target_id == "x:123456"
        for item in ProfilesRepository(session).list_due_profiles(
            now=datetime.now(UTC), limit=100
        )
    )


def test_confirmed_rebind_changes_identity_without_silently_editing(auth_client):
    creator = new_creator(auth_client, name="Human name")
    path = f"{URL}/{creator['id']}/identity"
    payload = {
        "expected_revision": creator["revision"],
        "platform": "twitch",
        "account_id": "456",
        "confirmed": False,
    }
    assert auth_client.put(path, json=payload).status_code == 422
    changed = auth_client.put(path, json={**payload, "confirmed": True})
    assert changed.status_code == 200, changed.text
    assert changed.json()["id"] == creator["id"]
    assert changed.json()["platform"] == "twitch"
    assert changed.json()["source_identity"]["revision"] == 1
    assert changed.json()["name"] == "Human name"


def test_legacy_notes_edit_does_not_remove_other_manual_emails(auth_client):
    creator = new_creator(auth_client, platform="youtube", account_id="UClegacy123")
    path = f"{URL}/{creator['id']}/contacts"
    for email in ("first@example.com", "second@example.com"):
        creator = post(
            auth_client,
            path,
            {"expected_revision": creator["revision"], "email": email},
        ).json()
    response = auth_client.patch(
        f"/api/v1/profiles/creators/{creator['id']}/manual",
        json={"contact_email": "first@example.com", "notes": "A new note"},
    )
    assert response.status_code == 200
    current = auth_client.get(f"{URL}/{creator['id']}").json()
    assert {c["email"] for c in current["contacts"] if c["is_active"]} == {
        "first@example.com",
        "second@example.com",
    }
    assert current["internal_notes"] == "A new note"
    assert current["revision"] > creator["revision"]


def test_manual_work_platform_is_editable_without_claiming_source_evidence(auth_client):
    creator = new_creator(auth_client)
    path = f"{URL}/{creator['id']}/works"
    work = post(
        auth_client,
        path,
        {
            "expected_identity_revision": 0,
            "content_title": "Public appearance",
            "platform": "twitch",
        },
    )
    assert work.status_code == 201, work.text
    value = work.json()
    edited = auth_client.patch(
        f"{path}/{value['id']}",
        json={"expected_revision": value["revision"], "platform": "youtube"},
    )
    assert edited.status_code == 200
    assert edited.json()["platform"] == "youtube"
    assert edited.json()["origin"] == "manual" and edited.json()["source_fields"] == {}


def test_stale_work_page_cannot_attach_evidence_to_rebound_identity(auth_client):
    creator = new_creator(auth_client)
    rebound = auth_client.put(
        f"{URL}/{creator['id']}/identity",
        json={
            "expected_revision": creator["revision"],
            "confirmed": True,
            "platform": "twitch",
            "account_id": "888",
        },
    )
    assert rebound.status_code == 200
    result = post(
        auth_client,
        f"{URL}/{creator['id']}/works",
        {"expected_identity_revision": 0, "content_title": "Old account video"},
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "creator_identity_changed"


def test_legacy_notes_keep_source_link_and_cannot_write_after_rebind(auth_client):
    creator = new_creator(auth_client, platform="youtube", account_id="UCbefore123")
    creator = post(
        auth_client,
        f"{URL}/{creator['id']}/contacts",
        {
            "expected_revision": creator["revision"],
            "email": "business@example.com",
            "source_url": "https://studio.example/contact",
        },
    ).json()
    path = f"/api/v1/profiles/creators/{creator['id']}/manual"
    response = auth_client.patch(
        path, json={"contact_email": "business@example.com", "notes": "Only a note"}
    )
    assert response.status_code == 200
    current = auth_client.get(f"{URL}/{creator['id']}").json()
    assert current["contacts"][0]["source_url"] == "https://studio.example/contact"
    result = auth_client.put(
        f"{URL}/{creator['id']}/identity",
        json={
            "expected_revision": current["revision"],
            "confirmed": True,
            "platform": "youtube",
            "account_id": "UCafter123",
        },
    )
    assert result.status_code == 200
    stale = auth_client.patch(
        path, json={"contact_email": "old@example.com", "notes": "Old account"}
    )
    assert stale.status_code == 409
    assert not any(
        c["is_active"]
        for c in auth_client.get(f"{URL}/{creator['id']}").json()["contacts"]
    )


@pytest.mark.parametrize("new_url", [None, "https://www.twitch.tv/newgamer"])
def test_rebind_never_keeps_previous_account_homepage(auth_client, new_url):
    creator = new_creator(auth_client, profile_url="https://x.com/oldgamer")
    result = auth_client.put(
        f"{URL}/{creator['id']}/identity",
        json={
            "expected_revision": creator["revision"],
            "confirmed": True,
            "platform": "twitch",
            "account_id": "888",
            "profile_url": new_url,
        },
    )
    assert result.status_code == 200
    assert result.json()["profile_url"] == new_url
