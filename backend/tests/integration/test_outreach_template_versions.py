from uuid import UUID, uuid4

import pytest

from app.db.models.profiles import GameProfile
from tests.integration.test_library_v2_games import create as create_game

URL = "/api/v2/outreach/template-versions"


def post(client, path, value, key=None):
    return client.post(
        path, json=value, headers={"Idempotency-Key": str(key or uuid4())}
    )


@pytest.mark.parametrize("steam_id", [None, "4952700"])
def test_canonical_registration_is_explicit_bound_and_does_not_change_game(
    auth_client, session, steam_id
):
    game = create_game(
        auth_client,
        {"name": "Chosen Game", **({"steam_app_id": steam_id} if steam_id else {})},
    ).json()
    before = auth_client.get(f"/api/v2/library/games/{game['id']}").json()
    listing = auth_client.get(URL, params={"game_id": game["id"]})
    assert listing.status_code == 200, listing.text
    assert listing.json()["items"] == []
    assert listing.json()["builtin"]["requires_explicit_registration"] is True
    response = post(auth_client, URL + "/canonical", {"game_id": game["id"]})
    assert response.status_code == 201, response.text
    version = response.json()
    assert version["game_id"] == game["id"]
    assert version["source_metadata"]["revision"] == 69
    assert version["source_metadata"]["steam_app_id"] == "4952700"
    assert (
        version["fixed_hash"]
        == "0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93"
    )
    assert (
        post(auth_client, URL + "/canonical", {"game_id": game["id"]}).json() == version
    )
    assert auth_client.get(URL + f"/{version['id']}").json() == version
    assert (
        len(auth_client.get(URL, params={"game_id": game["id"]}).json()["items"]) == 1
    )
    assert auth_client.get(f"/api/v2/library/games/{game['id']}").json() == before
    assert session.get(GameProfile, UUID(game["id"])).steam_app_id == steam_id


def test_conflicting_known_steam_game_cannot_register_canonical(auth_client):
    game = create_game(
        auth_client, {"name": "LIMINAL: Within", "steam_app_id": "123"}
    ).json()
    response = post(auth_client, URL + "/canonical", {"game_id": game["id"]})
    assert response.status_code == 422, response.text
    assert auth_client.get(URL, params={"game_id": game["id"]}).json()["items"] == []


def test_explicit_new_versions_do_not_mutate_original_or_each_other(auth_client):
    game = create_game(auth_client, {"name": "Manual game"}).json()
    canonical = post(auth_client, URL + "/canonical", {"game_id": game["id"]}).json()
    value = {
        "request_id": str(uuid4()),
        "game_id": game["id"],
        "name": "Our new original",
        "subject": "Try our new game",
        "fixed_fragments": [
            "<p>Hi ",
            ", ",
            " reference ",
            ": ",
            "</p><p>New studio</p>",
        ],
    }
    created = post(auth_client, URL, value)
    assert created.status_code == 201, created.text
    assert created.json()["fixed_hash"] != canonical["fixed_hash"]
    assert post(auth_client, URL, value).json() == created.json()
    assert post(auth_client, URL, value | {"subject": "Changed"}).status_code == 409
    newer = post(
        auth_client, URL, value | {"request_id": str(uuid4()), "subject": "Version two"}
    )
    assert newer.status_code == 201 and newer.json()["id"] != created.json()["id"]
    assert auth_client.get(URL + f"/{canonical['id']}").json() == canonical
    assert auth_client.get(URL + f"/{created.json()['id']}").json() == created.json()
    assert (
        len(auth_client.get(URL, params={"game_id": game["id"]}).json()["items"]) == 3
    )


def test_new_template_bad_fixed_markup_is_rejected(auth_client):
    game = create_game(auth_client, {"name": "Manual game"}).json()
    value = {
        "request_id": str(uuid4()),
        "game_id": game["id"],
        "name": "Bad",
        "subject": "Hello",
        "fixed_fragments": ["<p onclick='run()'>", "", "", "", "</p>"],
    }
    response = post(auth_client, URL, value)
    assert response.status_code == 422, response.text
    assert auth_client.get(URL, params={"game_id": game["id"]}).json()["items"] == []


def test_template_routes_require_auth(client):
    assert client.get(URL).status_code == 401
    assert client.get(URL + f"/{uuid4()}").status_code == 401
    assert (
        post(client, URL + "/canonical", {"game_id": str(uuid4())}).status_code == 401
    )
