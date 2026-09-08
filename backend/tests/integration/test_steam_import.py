from contextlib import contextmanager
from copy import deepcopy
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, func

from app.core.idempotency import utc_now
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import GameProfile
from app.integrations.steam import SteamGateway
from tests.unit.integrations.test_steam import _steam_payload
from tests.integration.test_activity_preparation import post

URL = "https://store.steampowered.com/app/1245620/Elden_Ring/"
PATH = "/api/v2/library/games/steam-import"


def steam_fixture(client, *, handler=None):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "store.steampowered.com"
        assert dict(request.url.params) == {
            "appids": "1245620",
            "l": "english",
            "cc": "US",
        }
        return (
            handler(request) if handler else httpx.Response(200, json=_steam_payload())
        )

    @contextmanager
    def factory():
        with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
            with SteamGateway(http_client=transport) as gateway:
                yield gateway

    client.app.state.steam_gateway_factory = factory
    return calls


def import_source(client, *, key=None, **fields):
    return post(client, PATH, {"url": URL, **fields}, key=key)


def create_game(client, **fields):
    response = post(client, "/api/v2/library/games", {"name": "Human title", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_steam_source_import_is_editable_source_only_and_replayed_once(
    auth_client, session
):
    calls = steam_fixture(auth_client)
    key = str(uuid4())
    response = import_source(auth_client, key=key)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source_fields"]["name"] == "Elden Ring"
    assert result["source_fields"]["developer"] == "FromSoftware"
    assert result["description"] == "An action RPG."
    assert result["tags"] == ["Action"]
    assert result["languages"] == ["English", "Japanese"]
    assert result["cover_url"] == "https://cdn.example/cover.jpg"
    assert result["manual_overrides"] == {} and result["revision"] == 1
    assert result["last_analyzed_at"] is None
    assert result["source_identity"]["steam_app_id"] == "1245620"
    assert import_source(auth_client, key=key).json() == result
    assert len(calls) == 1
    assert import_source(auth_client).json()["id"] == result["id"]
    assert session.scalar(select(func.count()).select_from(GameProfile)) == 1
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 0
    assert session.get(GameProfile, UUID(result["id"])).analysis == {}
    conflict = import_source(
        auth_client, key=key, url="https://store.steampowered.com/app/10"
    )
    assert conflict.status_code == 409
    assert len(calls) == 2


def test_explicit_first_binding_reuses_manual_uuid_and_preserves_human_layers(
    auth_client, session
):
    calls = steam_fixture(auth_client)
    game = create_game(
        auth_client,
        description="Human description",
        favorite=True,
        reference_works=[{"name": "Reference", "reason": "Shared story"}],
    )
    result = import_source(
        auth_client, game_id=game["id"], expected_revision=game["revision"]
    )
    assert result.status_code == 200, result.text
    bound = result.json()
    assert bound["id"] == game["id"] and bound["revision"] == game["revision"] + 1
    assert bound["manual_overrides"] == game["manual_overrides"]
    assert bound["reference_works"] == game["reference_works"] and bound["favorite"]
    assert (
        bound["name"] == "Human title"
        and bound["source_fields"]["name"] == "Elden Ring"
    )
    assert (
        import_source(
            auth_client, game_id=game["id"], expected_revision=game["revision"]
        ).status_code
        == 409
    )
    assert len(calls) == 1
    assert (
        import_source(
            auth_client,
            game_id=game["id"],
            expected_revision=bound["revision"],
            url="https://store.steampowered.com/app/10",
        ).status_code
        == 409
    )
    assert len(calls) == 1


def test_source_refresh_does_not_overwrite_completed_analysis_or_manual_data(
    auth_client, session
):
    steam_fixture(auth_client)
    game = create_game(auth_client, steam_app_id="1245620", tags=["Human genre"])
    profile = session.get(GameProfile, UUID(game["id"]))
    profile.analysis = {"summary": "Existing analysis"}
    profile.brief = {"text": "Existing brief"}
    profile.model_metadata = {"model": "existing"}
    profile.prompt_metadata = {"version": "existing"}
    profile.last_analyzed_at = profile.next_analysis_at = utc_now()
    session.commit()
    previous = {
        name: deepcopy(getattr(profile, name))
        for name in (
            "analysis",
            "brief",
            "model_metadata",
            "prompt_metadata",
            "last_analyzed_at",
            "next_analysis_at",
            "manual_overrides",
        )
    }
    result = import_source(auth_client)
    assert result.status_code == 200, result.text
    assert result.json()["id"] == game["id"] and result.json()["tags"] == [
        "Human genre"
    ]
    assert profile.current_facts["name"] == "Elden Ring"
    assert {name: getattr(profile, name) for name in previous} == previous


def test_source_failure_preserves_saved_fields_and_same_key_retry_recovers(
    auth_client, session
):
    game = create_game(auth_client, steam_app_id="1245620", description="Keep this")
    profile = session.get(GameProfile, UUID(game["id"]))
    profile.current_facts = {"name": "Old source"}
    session.commit()

    def timeout(request):
        raise httpx.ReadTimeout("fixture", request=request)

    calls = steam_fixture(auth_client, handler=timeout)
    key = str(uuid4())
    before = deepcopy(profile.current_facts)
    result = import_source(auth_client, key=key)
    assert result.status_code == 503, result.text
    assert result.json()["error"]["retryable"]
    assert profile.current_facts == before
    assert profile.manual_overrides["description"] == "Keep this"
    steam_fixture(auth_client)
    retried = import_source(auth_client, key=key)
    assert retried.status_code == 200 and retried.json()["id"] == game["id"]
    assert len(calls) == 1
    assert session.scalar(select(func.count()).select_from(GameProfile)) == 1


def test_not_found_and_missing_optional_fields_are_honest(auth_client, session):
    steam_fixture(
        auth_client,
        handler=lambda _: httpx.Response(200, json={"1245620": {"success": False}}),
    )
    response = import_source(auth_client)
    assert response.status_code == 404 and not response.json()["error"]["retryable"]
    assert session.scalar(select(func.count()).select_from(GameProfile)) == 0
    steam_fixture(
        auth_client,
        handler=lambda _: httpx.Response(
            200,
            json={
                "1245620": {
                    "success": True,
                    "data": {"steam_appid": 1245620, "name": "Minimal"},
                }
            },
        ),
    )
    result = import_source(auth_client)
    assert result.status_code == 200, result.text
    assert result.json()["developer"] is None and result.json()["cover_url"] is None
    assert result.json()["languages"] == []


@pytest.mark.parametrize(
    "url",
    [
        "http://store.steampowered.com/app/1245620",
        "https://127.0.0.1/app/1245620",
        "https://secret@store.steampowered.com/app/1245620",
        "https://store.steampowered.com.evil.test/app/1245620",
    ],
)
def test_noncanonical_steam_target_never_reaches_transport(auth_client, url):
    calls = steam_fixture(auth_client)
    assert import_source(auth_client, url=url).status_code == 422
    assert calls == []


def test_import_rejects_wrong_identity_stale_pair_and_unauthorized_request(
    auth_client, client
):
    calls = steam_fixture(auth_client)
    existing = create_game(auth_client, steam_app_id="1245620")
    other = create_game(auth_client)
    assert (
        import_source(
            auth_client, game_id=other["id"], expected_revision=other["revision"]
        ).status_code
        == 409
    )
    assert import_source(auth_client, game_id=existing["id"]).status_code == 422
    assert import_source(auth_client, expected_revision=0).status_code == 422
    assert calls == []
    client.headers.pop("Authorization", None)
    assert import_source(client).status_code == 401


def test_source_import_then_edit_then_analysis_publishes_same_uuid(
    auth_client, session
):
    from app.analysis.game_pipeline import GameAnalysisPipeline
    from app.analysis.service import GameAnalysisService
    from tests.integration.test_game_analysis_commit import Steam, AI, Artifacts

    steam_fixture(auth_client)
    manual = create_game(auth_client, reference_works=[{"name": "Reference game"}])
    result = import_source(
        auth_client, game_id=manual["id"], expected_revision=manual["revision"]
    )
    assert result.status_code == 200, result.text
    imported = result.json()
    edited = auth_client.patch(
        f"/api/v2/library/games/{imported['id']}",
        json={"expected_revision": imported["revision"], "description": "Human edit"},
    )
    assert edited.status_code == 200
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
    assert created.json()["outcome"] == "job"
    job_id = UUID(created.json()["id"])

    @contextmanager
    def sessions():
        yield session

    session.commit()
    pipeline = GameAnalysisPipeline(
        service=GameAnalysisService(session_factory=sessions),
        steam=Steam(),
        deepseek=AI(),
        artifacts=Artifacts(),
    )
    assert str(pipeline.run(job_id)) == manual["id"]
    final = auth_client.get(f"/api/v2/library/games/{manual['id']}").json()
    assert final["description"] == "Human edit"
    assert final["reference_works"] == manual["reference_works"]
    assert final["last_analyzed_at"] is not None
    assert (
        auth_client.get(f"/api/v1/jobs/{job_id}").json()["profile_id"] == manual["id"]
    )
    assert session.scalar(select(func.count()).select_from(GameProfile)) == 1


def test_import_rechecks_selected_revision_after_unlocked_fetch(auth_client, session):
    game = create_game(auth_client)

    def racing_edit(request):
        assert (
            not session.in_transaction()
        ), "Steam I/O must not hold the API's DB transaction"
        profile = session.get(GameProfile, UUID(game["id"]))
        profile.manual_revision += 1
        profile.manual_overrides = {
            **profile.manual_overrides,
            "description": "Concurrent human edit",
        }
        session.commit()
        return httpx.Response(200, json=_steam_payload())

    steam_fixture(auth_client, handler=racing_edit)
    response = import_source(
        auth_client, game_id=game["id"], expected_revision=game["revision"]
    )
    assert response.status_code == 409, response.text
    current = auth_client.get(f"/api/v2/library/games/{game['id']}").json()
    assert current["description"] == "Concurrent human edit"
    assert current["source_identity"]["steam_app_id"] is None


def test_manual_business_steam_id_requires_selected_explicit_binding(auth_client):
    calls = steam_fixture(auth_client)
    game = create_game(auth_client)
    edited = auth_client.patch(
        f"/api/v2/library/games/{game['id']}",
        json={"expected_revision": game["revision"], "steam_app_id": "1245620"},
    ).json()
    assert edited["source_identity"]["steam_app_id"] is None
    assert import_source(auth_client).status_code == 409
    assert calls == []
    bound = import_source(
        auth_client, game_id=game["id"], expected_revision=edited["revision"]
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["id"] == game["id"]


def test_new_import_seed_allows_first_create_analysis_instead_of_existing_profile(
    auth_client,
):
    steam_fixture(auth_client)
    result = import_source(auth_client).json()
    created = post(
        auth_client,
        "/api/v1/jobs/analysis",
        {
            "target_type": "game",
            "url": result["source_identity"]["canonical_url"],
            "mode": "create",
        },
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["outcome"] == "job"
