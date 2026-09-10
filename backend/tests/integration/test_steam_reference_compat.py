from tests.integration.test_steam_import import steam_fixture, import_source
from tests.integration.test_activity_qualification import ready_composition
from tests.integration.test_outreach_drafts import get_compose
import json
import os
from pathlib import Path

HEADER = "X-FMG-Steam-References"


def test_old_new_import_cache_replay_and_library_get_shape(auth_client):
    steam_fixture(auth_client)
    old = import_source(auth_client, key="steam-compat-import").json()
    assert "steam_recommendations" not in old
    auth_client.headers[HEADER] = "1"
    new = import_source(auth_client, key="steam-compat-import").json()
    assert new["id"] == old["id"]
    assert new["steam_recommendations"]["status"] == "available"
    path = f"/api/v2/library/games/{new['id']}"
    patched = auth_client.patch(
        path,
        json={
            "expected_revision": new["revision"],
            "reference_works": [{"name": "Manual"}],
        },
    ).json()
    assert patched["reference_works"][0]["source"] == "manual"
    del auth_client.headers[HEADER]
    legacy = auth_client.get(path).json()
    assert "source" not in legacy["reference_works"][0]
    assert "source_url" not in legacy["reference_works"][0]
    assert "steam_recommendations" not in legacy
    legacy_page = auth_client.get("/api/v2/library/games").json()
    assert "steam_recommendations" not in legacy_page["items"][0]


def test_nested_draft_game_uses_same_opt_in(auth_client, session, monkeypatch):
    auth_client.headers[HEADER] = "1"
    _, composition = ready_composition(auth_client, session, monkeypatch, count=1)
    new = get_compose(auth_client, composition["id"])
    game = new["drafts"][0]["input"]["game"]
    assert game["steam_recommendations"]["status"] == "not_fetched"
    del auth_client.headers[HEADER]
    legacy = get_compose(auth_client, composition["id"])
    assert "steam_recommendations" not in legacy["drafts"][0]["input"]["game"]
    if directory := os.environ.get("FMG_STEAM_DTO_EXPORT_DIR"):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        for name, body in {
            "draft-new": new["drafts"][0],
            "draft-legacy": legacy["drafts"][0],
        }.items():
            (path / (name + ".json")).write_text(json.dumps(body, indent=2) + "\n")
