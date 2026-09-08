from uuid import UUID, uuid4
import httpx
import pytest
from sqlalchemy import select, func

from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile
from app.db.models.settings import SharedSettings
from app.integrations.youtube import YouTubeGateway
from tests.integration.test_library_v2_creators import new_creator
from tests.integration.test_activity_preparation import post

URL = "https://www.youtube.com/@fixturecreator"
CHANNEL = "UCresolved123"


def resolver_fixture(client, session, *, handler=None):
    calls = []

    class Resolver:
        def resolve_channel(self, target):
            assert (
                not session.in_transaction()
            ), "Resolution holds the API read transaction"

            def response(request):
                calls.append(request)
                assert request.url.host == "www.googleapis.com"
                assert request.url.params["forHandle"] == "@fixturecreator"
                return (
                    handler(request)
                    if handler
                    else httpx.Response(200, json={"items": [{"id": CHANNEL}]})
                )

            with httpx.Client(transport=httpx.MockTransport(response)) as transport:
                with YouTubeGateway(
                    api_key="fixture", http_client=transport
                ) as gateway:
                    return gateway.resolve_channel(target)

    client.app.state.youtube_binding_resolver = Resolver()
    return calls


def seed(client):
    return new_creator(
        client,
        platform="youtube",
        account_id=None,
        profile_url=URL,
        name="Human channel",
        internal_notes="Keep notes",
    )


def bind(client, creator, *, key=None, **fields):
    return post(
        client,
        f"/api/v2/library/creators/{creator['id']}/youtube-binding",
        {"url": URL, "expected_revision": creator["revision"], **fields},
        key=key,
    )


def test_url_only_first_binding_retains_uuid_manual_fields_and_replays(
    auth_client, session
):
    creator = seed(auth_client)
    calls = resolver_fixture(auth_client, session)
    key = str(uuid4())
    response = bind(auth_client, creator, key=key)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["id"] == creator["id"]
    assert result["source_identity"]["account_id"] == CHANNEL
    assert (
        result["source_identity"]["canonical_url"]
        == f"https://www.youtube.com/channel/{CHANNEL}"
    )
    assert (
        result["name"] == "Human channel" and result["internal_notes"] == "Keep notes"
    )
    assert result["last_analyzed_at"] is None and result["analysis_available"]
    assert bind(auth_client, creator, key=key).json() == result
    assert len(calls) == 1
    assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 1
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 0
    assert bind(auth_client, creator).status_code == 409
    assert len(calls) == 1


def test_binding_duplicate_or_different_bound_account_never_creates_new_creator(
    auth_client, session
):
    existing = new_creator(auth_client, platform="youtube", account_id=CHANNEL)
    target = seed(auth_client)
    resolver_fixture(auth_client, session)
    response = bind(auth_client, target)
    assert response.status_code == 409, response.text
    assert (
        auth_client.get(f"/api/v2/library/creators/{target['id']}").json()[
            "source_identity"
        ]["account_id"]
        is None
    )
    response = bind(
        auth_client, existing, url="https://www.youtube.com/channel/UCdifferent123"
    )
    assert response.status_code == 409
    assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 2


def test_pause_blocks_handle_network_but_direct_channel_binding_is_local(
    auth_client, session
):
    creator = seed(auth_client)
    calls = resolver_fixture(auth_client, session)
    settings = session.scalar(select(SharedSettings))
    settings.collection_enabled = {**settings.collection_enabled, "youtube": False}
    session.commit()
    response = bind(auth_client, creator)
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "collection_disabled"
    )
    assert calls == []
    direct = bind(
        auth_client, creator, url=f"https://www.youtube.com/channel/{CHANNEL}"
    )
    assert direct.status_code == 200, direct.text
    assert calls == []


@pytest.mark.parametrize("failure, expected", [("missing", 404), ("timeout", 503)])
def test_resolution_failure_preserves_manual_seed_and_can_retry(
    auth_client, session, failure, expected
):
    creator = seed(auth_client)

    def failing(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("fixture", request=request)
        return httpx.Response(200, json={"items": []})

    resolver_fixture(auth_client, session, handler=failing)
    key = str(uuid4())
    response = bind(auth_client, creator, key=key)
    assert response.status_code == expected, response.text
    assert (
        auth_client.get(f"/api/v2/library/creators/{creator['id']}").json() == creator
    )
    resolver_fixture(auth_client, session)
    assert bind(auth_client, creator, key=key).status_code == 200


def test_resolution_rechecks_revision_before_binding(auth_client, session):
    creator = seed(auth_client)

    def changing(request):
        row = session.get(CreatorProfile, UUID(creator["id"]))
        row.manual_revision += 1
        row.manual_overrides = {
            **row.manual_overrides,
            "internal_notes": "Concurrent note",
        }
        session.commit()
        return httpx.Response(200, json={"items": [{"id": CHANNEL}]})

    resolver_fixture(auth_client, session, handler=changing)
    response = bind(auth_client, creator)
    assert response.status_code == 409
    current = auth_client.get(f"/api/v2/library/creators/{creator['id']}").json()
    assert (
        current["internal_notes"] == "Concurrent note"
        and current["source_identity"]["account_id"] is None
    )


def test_binding_scope_auth_and_url_allowlist(auth_client, client, session):
    creator = seed(auth_client)
    calls = resolver_fixture(auth_client, session)
    assert (
        bind(
            auth_client, creator, url="https://127.0.0.1/channel/UCresolved123"
        ).status_code
        == 422
    )
    other = new_creator(auth_client)
    assert bind(auth_client, other).status_code == 422
    assert calls == []
    client.headers.pop("Authorization", None)
    assert bind(client, creator).status_code == 401


def test_first_binding_does_not_race_an_already_queued_analysis(auth_client, session):
    creator = seed(auth_client)
    canonical = f"https://www.youtube.com/channel/{CHANNEL}"
    queued = post(
        auth_client,
        "/api/v1/jobs/analysis",
        {"target_type": "creator", "url": canonical, "mode": "reanalyze"},
    )
    assert queued.status_code == 201, queued.text
    response = bind(auth_client, creator, url=canonical)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "creator_analysis_in_progress"
    assert (
        auth_client.get(f"/api/v2/library/creators/{creator['id']}").json() == creator
    )
