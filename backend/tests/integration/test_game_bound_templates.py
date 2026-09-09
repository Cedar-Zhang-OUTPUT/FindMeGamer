from uuid import UUID
from app.db.models.profiles import GameProfile
from app.db.models.outreach_drafts import OutreachTemplateVersion
from tests.integration.test_outreach_template_versions import post, URL
from tests.integration.test_library_v2_games import create
from tests.integration.test_outreach_drafts import draft_setup, compose


def test_historical_original_template_is_readable_and_not_rewritten(auth_client, session):
    from app.outreach.locked_templates import canonical_template
    game = create(auth_client, {"name": "Historical Game"}).json()
    old = canonical_template()
    row = OutreachTemplateVersion(game_id=UUID(game["id"]), builtin_key="liminal-revision-69", name=old["name"], subject=old["subject"], fixed_fragments=old["fixed_fragments"], fixed_hash=old["fixed_hash"], source_metadata={"kind": "canonical", "revision": 69})
    session.add(row)
    session.commit()
    original = auth_client.get(URL + f"/{row.id}").json()
    new = post(auth_client, URL + "/canonical", {"game_id": game["id"]})
    assert new.status_code == 201 and new.json()["id"] != str(row.id)
    assert auth_client.get(URL + f"/{row.id}").json() == original


def test_two_games_render_independently_and_changed_facts_keep_old_version(
    auth_client, session
):
    one = create(
        auth_client,
        {"name": "Forest", "steam_app_id": "123", "description": "A forest puzzle."},
    ).json()
    two = create(
        auth_client, {"name": "Ocean", "description": "An ocean adventure."}
    ).json()
    first = post(auth_client, URL + "/canonical", {"game_id": one["id"]}).json()
    second = post(auth_client, URL + "/canonical", {"game_id": two["id"]}).json()
    assert first["source_metadata"]["kind"] == "game_bound"
    assert "Forest" in first["subject"] and "Ocean" not in first["subject"]
    assert "Ocean" in second["subject"] and "LIMINAL" not in str(second)
    profile = session.get(GameProfile, UUID(one["id"]))
    profile.manual_overrides = profile.manual_overrides | {
        "description": "A revised forest puzzle."
    }
    profile.manual_revision += 1
    session.commit()
    newer = post(auth_client, URL + "/canonical", {"game_id": one["id"]}).json()
    assert newer["id"] != first["id"]
    assert auth_client.get(URL + "/" + first["id"]).json() == first
    assert post(auth_client, URL + "/canonical", {"game_id": one["id"]}).json() == newer
    assert (
        auth_client.get(URL, params={"game_id": one["id"]}).json()["builtin"][
            "fixed_hash"
        ]
        == newer["fixed_hash"]
    )


def test_new_composition_rejects_stale_fixed_game_text(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    game = session.get(GameProfile, UUID(template["game_id"]))
    game.manual_overrides = game.manual_overrides | {"name": "Changed Game"}
    game.manual_revision += 1
    session.commit()
    response = compose(auth_client, activity, batch, template)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "template_context_changed"


def test_refresh_cannot_make_stale_game_template_sendable(
    auth_client, session, monkeypatch
):
    from tests.integration.test_outreach_drafts import get_compose

    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    original = compose(auth_client, activity, batch, template).json()
    game = session.get(GameProfile, UUID(template["game_id"]))
    game.manual_overrides = game.manual_overrides | {"description": "Changed facts"}
    session.commit()
    draft = get_compose(auth_client, original["id"])["drafts"][0]
    refreshed = post(
        auth_client,
        f"/api/v2/outreach/drafts/{draft['id']}/refresh",
        {
            "expected_revision": draft["revision"],
            "context_token": draft["context_token"],
        },
    )
    assert refreshed.status_code == 200
    assert "template_context_changed" in refreshed.json()["missing_fields"]
    assert refreshed.json()["status"] == "needs_repair"
