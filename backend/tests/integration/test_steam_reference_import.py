from contextlib import contextmanager
from uuid import UUID
import json
import os
from pathlib import Path
import httpx
from app.integrations.steam import SteamGateway
from app.analysis.game_pipeline import GameAnalysisPipeline
from app.analysis.service import GameAnalysisService
from tests.integration.test_steam_import import import_source, create_game
from tests.integration.test_activity_preparation import post
from tests.integration.test_game_analysis_commit import Steam, AI, Artifacts
from tests.unit.integrations.test_steam import _steam_payload
from tests.unit.integrations.test_steam_reference_merge import source


def test_real_gateway_import_edit_remove_refresh_and_analysis_publication(
    auth_client, session
):
    auth_client.headers["X-FMG-Steam-References"] = "1"
    state = {"status": 200}

    def handler(request):
        if "/recommended/" in request.url.path:
            return httpx.Response(
                state["status"],
                text='<div id="released">'
                + "".join(
                    f'<a class="similar_grid_capsule" data-ds-appid="{i}" href="https://store.steampowered.com/app/{i}/"></a>'
                    for i in (20, 21)
                )
                + "</div>",
            )
        app = request.url.params["appids"]
        payload = _steam_payload(app)
        payload[app]["data"]["name"] = (
            "Synthetic Source" if app == "1245620" else f"Game {app}"
        )
        return httpx.Response(200, json=payload)

    @contextmanager
    def gateway():
        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            yield SteamGateway(http_client=transport)

    auth_client.app.state.steam_gateway_factory = gateway
    imported_response = import_source(auth_client)
    assert imported_response.status_code == 200, imported_response.text
    imported = imported_response.json()
    assert [r["name"] for r in imported["reference_works"]] == ["Game 20", "Game 21"]
    assert all(
        r["source"] == "steam_more_like_this"
        and not r["similarities"]
        and r["reason"] is None
        for r in imported["reference_works"]
    )
    assert imported["steam_recommendations"]["status"] == "available"
    if directory := os.environ.get("FMG_STEAM_DTO_EXPORT_DIR"):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        (path / "game-detail.json").write_text(json.dumps(imported, indent=2) + "\n")
        legacy = auth_client.get(
            f"/api/v2/library/games/{imported['id']}",
            headers={"X-FMG-Steam-References": ""},
        ).json()
        (path / "game-detail-legacy.json").write_text(
            json.dumps(legacy, indent=2) + "\n"
        )
    edited_work = {
        k: v
        for k, v in imported["reference_works"][0].items()
        if k not in {"source", "source_url"}
    }
    edited_work.update(name="Human edited title", reason="Human authored note")
    edited_response = auth_client.patch(
        f"/api/v2/library/games/{imported['id']}",
        json={
            "expected_revision": imported["revision"],
            "reference_works": [edited_work],
        },
    )
    assert edited_response.status_code == 200, edited_response.text
    edited = edited_response.json()
    assert edited["reference_works"][0]["source"] == "steam_more_like_this"
    refreshed = import_source(auth_client).json()
    assert refreshed["reference_works"] == edited["reference_works"]
    state["status"] = 503
    failed_optional = import_source(auth_client).json()
    assert failed_optional["reference_works"] == edited["reference_works"]
    assert failed_optional["steam_recommendations"]["status"] == "unavailable"
    if directory:
        (path / "game-detail-unavailable.json").write_text(
            json.dumps(failed_optional, indent=2) + "\n"
        )
    created = post(
        auth_client,
        "/api/v1/jobs/analysis",
        {
            "target_type": "game",
            "url": imported["source_identity"]["canonical_url"],
            "mode": "reanalyze",
        },
    )
    assert created.status_code in (200, 201), created.text

    class RecommendedSteam(Steam):
        def fetch_game(self, app_id):
            return (
                super()
                .fetch_game(app_id)
                .model_copy(update={"steam_recommendations": source(20, 21, 22)})
            )

    @contextmanager
    def sessions():
        yield session

    session.commit()
    pipeline = GameAnalysisPipeline(
        service=GameAnalysisService(session_factory=sessions),
        steam=RecommendedSteam(),
        deepseek=AI(),
        artifacts=Artifacts(),
    )
    assert str(pipeline.run(UUID(created.json()["id"]))) == imported["id"]
    final = auth_client.get(f"/api/v2/library/games/{imported['id']}").json()
    assert [r["name"] for r in final["reference_works"]] == [
        "Human edited title",
        "Game 22",
    ]
    assert final["reference_works"][0]["reason"] == "Human authored note"
    assert final["revision"] > failed_optional["revision"]
    assert final["steam_recommendations"]["status"] == "available"


def test_manual_reference_dedup_then_user_delete_stays_deleted(auth_client):
    auth_client.headers["X-FMG-Steam-References"] = "1"

    class RecommendedSteam(Steam):
        def fetch_game(self, app_id):
            return (
                super()
                .fetch_game(app_id)
                .model_copy(update={"steam_recommendations": source(20)})
            )

    @contextmanager
    def gateway():
        yield RecommendedSteam()

    auth_client.app.state.steam_gateway_factory = gateway
    manual = create_game(
        auth_client,
        reference_works=[
            {"name": "Human reference", "url": "https://store.steampowered.com/app/20/"}
        ],
    )
    imported = import_source(
        auth_client, game_id=manual["id"], expected_revision=manual["revision"]
    ).json()
    assert (
        len(imported["reference_works"]) == 1
        and imported["reference_works"][0]["source"] == "manual"
    )
    edited = auth_client.patch(
        f"/api/v2/library/games/{manual['id']}",
        json={"expected_revision": imported["revision"], "reference_works": []},
    )
    assert edited.status_code == 200, edited.text
    refreshed = import_source(auth_client).json()
    assert refreshed["reference_works"] == []
