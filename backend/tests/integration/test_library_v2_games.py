from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.models.profiles import GameProfile
from app.repositories.profiles import ProfilesRepository
from tests.integration.test_profiles_api import add_game


URL = "/api/v2/library/games"


def create(client, payload, *, key=None):
    return client.post(
        URL, json=payload, headers={"Idempotency-Key": key or str(uuid4())}
    )


def patch(client, game, **fields):
    return client.patch(
        f"{URL}/{game['id']}",
        json={"expected_revision": game["revision"], **fields},
    )


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH"])
def test_library_requires_workspace_auth(client, method):
    path = URL if method != "PATCH" else f"{URL}/{uuid4()}"
    response = client.request(method, path, json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "workspace_key_invalid"


def test_name_only_game_is_real_persisted_and_has_no_fake_source(auth_client, session):
    response = create(auth_client, {"name": "  Our New Game  "})
    assert response.status_code == 201
    game = response.json()
    assert game["name"] == "Our New Game"
    assert game["steam_app_id"] is None
    assert game["website_url"] is None
    assert game["source_identity"] == {"steam_app_id": None, "canonical_url": None}
    assert game["source_fields"]["name"] is None
    assert game["manual_overrides"] == {"name": "Our New Game"}
    assert game["revision"] == 1
    assert game["last_analyzed_at"] is None
    stored = session.get(GameProfile, UUID(game["id"]))
    assert stored is not None and stored.current_facts == {}
    assert auth_client.get(f"{URL}/{game['id']}").json() == game


def test_url_only_creation_and_explicit_clearing(auth_client):
    game = create(auth_client, {"website_url": "https://studio.example/game"}).json()
    assert game["name"] is None
    updated = patch(auth_client, game, name="New Title", website_url=None)
    assert updated.status_code == 200
    assert updated.json()["website_url"] is None
    invalid = patch(auth_client, updated.json(), name=None)
    assert invalid.status_code == 422
    assert auth_client.get(f"{URL}/{game['id']}").json()["name"] == "New Title"


def test_url_only_game_can_be_found_by_its_website(auth_client):
    game = create(auth_client, {"website_url": "https://studio.example/game"}).json()
    response = auth_client.get(URL, params={"query": "STUDIO.example"})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [game["id"]]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "  "},
        {"steam_app_id": "123"},
        {"name": "Game", "website_url": "javascript:alert(1)"},
        {"name": "Game", "cover_url": "file:///etc/passwd"},
        {"name": "Game", "website_url": "https://user:password@example.com/"},
        {"name": "Game", "steam_app_id": "not-a-steam-id"},
        {"name": "Game", "favorite": "yes"},
        {"name": "Game", "reference_works": [{}]},
        {"name": "Game", "unknown_field": "no"},
    ],
)
def test_bad_input_is_rejected_without_creating(auth_client, session, payload):
    before = session.scalar(select(func.count()).select_from(GameProfile))
    response = create(auth_client, payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"
    assert session.scalar(select(func.count()).select_from(GameProfile)) == before


def test_create_retry_replays_and_changed_request_conflicts(auth_client, session):
    key = str(uuid4())
    first = create(auth_client, {"name": "Retry safe"}, key=key)
    assert first.status_code == 201
    assert create(auth_client, {"name": "Retry safe"}, key=key).json() == first.json()
    changed = create(auth_client, {"name": "Different"}, key=key)
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_key_conflict"
    assert session.scalar(select(func.count()).select_from(GameProfile)) == 1


def test_create_requires_valid_idempotency_key(auth_client):
    response = auth_client.post(URL, json={"name": "Missing key"})
    assert response.status_code == 422


def test_full_edit_keeps_source_and_resets_selected_overrides(auth_client, session):
    old = add_game(
        session,
        app_id="1001",
        name="Source Name",
        current_facts={
            "name": "Source Name",
            "developers": ["Source Studio"],
            "short_description": "Original",
            "genres": ["Adventure"],
            "supported_languages": "English, French",
            "release_date": "Coming soon",
            "header_image_url": "https://cdn.example/header.jpg",
        },
    )
    original_url = old.canonical_url
    initial = auth_client.get(f"{URL}/{old.id}").json()
    assert initial["revision"] == 0
    edited = patch(
        auth_client,
        initial,
        name="Human Name",
        website_url="https://our.example/",
        developer="Human Studio",
        description=None,
        tags=["Puzzle"],
        languages=["English"],
        release_date="2027",
        cover_url=None,
        steam_app_id="2002",
        favorite=True,
    )
    assert edited.status_code == 200
    game = edited.json()
    assert game["name"] == "Human Name" and game["description"] is None
    assert game["steam_app_id"] == "2002"
    assert game["source_fields"]["name"] == "Source Name"
    assert game["source_identity"]["steam_app_id"] == "1001"
    session.refresh(old)
    assert old.current_facts["name"] == "Source Name"
    assert old.canonical_url == original_url and old.steam_app_id == "1001"
    reset = patch(
        auth_client, game, reset_fields=["name", "description", "steam_app_id"]
    )
    assert reset.status_code == 200
    assert reset.json()["name"] == "Source Name"
    assert reset.json()["description"] == "Original"
    assert reset.json()["steam_app_id"] == "1001"
    assert reset.json()["developer"] == "Human Studio"


def test_concurrent_editor_does_not_overwrite_newer_changes(auth_client):
    initial = create(auth_client, {"name": "Original"}).json()
    assert patch(auth_client, initial, name="First editor").status_code == 200
    stale = patch(auth_client, initial, name="Second editor")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "game_revision_conflict"
    assert auth_client.get(f"{URL}/{initial['id']}").json()["name"] == "First editor"


def test_reference_works_normalize_and_deduplicate_without_deleting_library(
    auth_client, session
):
    existing = add_game(session, app_id="123", name="Existing Reference")
    response = create(
        auth_client,
        {
            "name": "Game",
            "reference_works": [
                {
                    "name": "Reference",
                    "url": "https://store.steampowered.com/app/123/Some_Title/",
                    "similarities": ["art"],
                    "reason": "Shared mood",
                },
                {"url": "https://store.steampowered.com/app/123/?l=english"},
                {"name": "Other"},
                {"name": " other "},
            ],
        },
    )
    assert response.status_code == 201
    refs = response.json()["reference_works"]
    assert len(refs) == 2 and UUID(refs[0]["id"])
    assert refs[0]["reason"] == "Shared mood"
    edited = patch(auth_client, response.json(), reference_works=[refs[0]])
    assert edited.json()["reference_works"][0]["id"] == refs[0]["id"]
    assert session.get(GameProfile, existing.id) is not None


def test_steam_identity_conflict_is_explicit(auth_client, session):
    add_game(session, app_id="123", name="Existing")
    conflict = create(auth_client, {"name": "Duplicate", "steam_app_id": "123"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "game_identity_conflict"
    new = create(auth_client, {"name": "New"}).json()
    assert patch(auth_client, new, steam_app_id="123").status_code == 409


def test_list_search_pagination_and_collection_use_effective_values(
    auth_client, session
):
    add_game(session, app_id="10", name="Source")
    for name in ["Beta", "Alpha"]:
        assert (
            create(
                auth_client, {"name": name, "developer": "Our Studio", "favorite": True}
            ).status_code
            == 201
        )
    page = auth_client.get(
        URL, params={"query": "our studio", "only_collection": True, "limit": 1}
    ).json()
    assert page["total"] == 2 and page["items"][0]["name"] == "Alpha"
    page2 = auth_client.get(
        URL,
        params={
            "query": "our studio",
            "only_collection": True,
            "limit": 1,
            "offset": 1,
        },
    ).json()
    assert page2["items"][0]["name"] == "Beta"
    assert auth_client.get(URL).json()["total"] == 3


def test_manual_game_does_not_break_legacy_library_or_schedule(auth_client, session):
    legacy = add_game(session, app_id="10", name="Legacy")
    new = create(auth_client, {"name": "Manual"}).json()
    stored = session.get(GameProfile, UUID(new["id"]))
    stored.next_analysis_at = datetime.now(UTC) - timedelta(days=1)
    session.flush()
    assert [
        item["id"] for item in auth_client.get("/api/v1/profiles/games").json()["items"]
    ] == [str(legacy.id)]
    for suffix in ["", "/favorite"]:
        path = f"/api/v1/profiles/games/{new['id']}{suffix}"
        result = (
            auth_client.patch(path, json={"favorite": True})
            if suffix
            else auth_client.get(path)
        )
        assert result.status_code == 404
    due = ProfilesRepository(session).list_due_profiles(now=datetime.now(UTC), limit=20)
    assert all(item.profile_id != stored.id for item in due)
    session.refresh(stored)
    assert not stored.favorite


def test_steam_seed_can_be_analyzed_in_place_instead_of_reused_as_complete(
    auth_client, session
):
    game = create(auth_client, {"name": "Seed", "steam_app_id": "123"}).json()
    from app.analysis.targets import canonicalize_target
    from app.db.models.enums import JobMode, TargetType
    from app.repositories.jobs import JobsRepository

    target = canonicalize_target(
        TargetType.GAME, "https://store.steampowered.com/app/123"
    )
    result = JobsRepository(session).create_or_reuse_job(
        target, mode=JobMode.CREATE, correlation_id=None
    )
    assert result.existing_profile_id is None and result.created
    assert session.get(GameProfile, UUID(game["id"])).steam_app_id == "123"


def test_missing_game_and_invalid_patch_are_explicit(auth_client):
    assert auth_client.get(f"{URL}/{uuid4()}").status_code == 404
    game = create(auth_client, {"name": "Game"}).json()
    assert (
        auth_client.patch(
            f"{URL}/{game['id']}", json={"name": "No revision"}
        ).status_code
        == 422
    )
    assert (
        patch(auth_client, game, name="Both", reset_fields=["name"]).status_code == 422
    )


def test_migration_allows_unbound_games_and_retains_unique_bound_identity(
    database_inspector,
):
    columns = {
        col["name"]: col for col in database_inspector.get_columns("game_profiles")
    }
    assert columns["steam_app_id"]["nullable"] is True
    assert {"manual_overrides", "reference_works", "manual_revision"} <= columns.keys()
