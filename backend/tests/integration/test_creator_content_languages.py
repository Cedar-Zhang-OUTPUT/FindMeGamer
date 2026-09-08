from datetime import datetime, UTC
from uuid import UUID

import httpx
from sqlalchemy import select

from app.integrations.youtube import YouTubeGateway
from app.analysis.creator_map_reduce_pipeline import CreatorSourceCheckpoint
from app.discovery.library import import_discovered_account
from app.schemas.discovery import DiscoveredAccount, DiscoveredContent
from app.db.models.profiles import CreatorProfile
from app.repositories.creator_library import detail
from tests.integration.test_library_v2_creators import edit


def youtube_language_source(*, audio="en-US", metadata="ja"):
    def handler(request):
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UCcreator123",
                            "snippet": {"title": "Source"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "UUcreator123"}
                            },
                            "statistics": {},
                        }
                    ]
                },
            )
        if endpoint == "playlistItems":
            return httpx.Response(
                200, json={"items": [{"contentDetails": {"videoId": "video-001"}}]}
            )
        if endpoint == "videos":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "video-001",
                            "snippet": {
                                "title": "Clip",
                                "channelId": "UCcreator123",
                                "defaultAudioLanguage": audio,
                                "defaultLanguage": metadata,
                            },
                            "contentDetails": {},
                            "statistics": {},
                            "status": {"privacyStatus": "public"},
                        }
                    ]
                },
            )
        raise AssertionError(endpoint)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        with YouTubeGateway(api_key="fixture", http_client=transport) as gateway:
            return gateway.fetch_creator("UCcreator123")


def test_audio_language_survives_normalized_checkpoint_without_using_title_language():
    source = youtube_language_source()
    assert getattr(source.videos[0], "audio_language", None) == "en-US"
    restored = CreatorSourceCheckpoint.from_source(source).to_source()
    assert restored.videos[0].audio_language == "en-US"
    assert restored.videos[0].raw == {}
    assert youtube_language_source(audio=None).videos[0].audio_language is None


def test_discovery_source_languages_are_current_before_transaction_commit(session):
    now = datetime.now(UTC)
    account = DiscoveredAccount(
        platform="x",
        account_id="7654321",
        profile_url="https://x.com/i/user/7654321",
        collected_at=now,
    )

    def item(content_id, language):
        return DiscoveredContent(
            platform="x",
            content_id=content_id,
            account_id=account.account_id,
            source_url=f"https://x.com/i/status/{content_id}",
            language=language,
            collected_at=now,
        )

    creator = import_discovered_account(session, account, [item("1111", "en")])
    assert detail(creator).languages == ["en"]
    assert len(creator.works) == 1
    same = import_discovered_account(session, account, [item("2222", "ja")])
    assert same.id == creator.id
    assert set(detail(same).languages) == {"en", "ja"}
    assert len(same.works) == 2


def x_language_creator(session, *, language="en-US"):
    now = datetime.now(UTC)
    creator = import_discovered_account(
        session,
        DiscoveredAccount(
            platform="x",
            account_id="7654321",
            profile_url="https://x.com/i/user/7654321",
            display_name="Source language",
            collected_at=now,
        ),
        [
            DiscoveredContent(
                platform="x",
                content_id="9876543",
                account_id="7654321",
                source_url="https://x.com/i/status/9876543",
                text="A game discussion",
                language=language,
                collected_at=now,
            )
        ],
    )
    session.commit()
    return str(creator.id)


def test_discovered_content_language_reaches_library_and_preset_filter(
    auth_client, session
):
    creator_id = x_language_creator(session)
    result = auth_client.get(f"/api/v2/library/creators/{creator_id}").json()
    assert result["languages"] == ["en-US"]
    filtered = auth_client.get(
        "/api/v2/library/creators", params={"language": "English"}
    ).json()
    assert [c["id"] for c in filtered["items"]] == [creator_id]
    source = session.get(CreatorProfile, UUID(creator_id)).works[0].source_fields
    assert source["language"] == "en-US"


def test_manual_language_overlay_and_rebind_never_leak_previous_source(
    auth_client, session
):
    creator_id = x_language_creator(session, language="en")
    path = f"/api/v2/library/creators/{creator_id}"
    creator = auth_client.get(path).json()
    assert creator["languages"] == ["en"]
    changed = edit(auth_client, creator, languages=["Japanese"]).json()
    assert changed["languages"] == ["Japanese"] and changed["source_fields"][
        "languages"
    ] == ["en"]
    empty = edit(auth_client, changed, languages=[]).json()
    assert empty["languages"] == []
    rebound = auth_client.put(
        path + "/identity",
        json={
            "expected_revision": empty["revision"],
            "platform": "x",
            "account_id": "7654322",
            "confirmed": True,
        },
    )
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["source_fields"]["languages"] == []


def test_unknown_content_and_audience_inference_never_become_source_language(
    auth_client, session
):
    creator_id = x_language_creator(session, language="und")
    profile = session.get(CreatorProfile, UUID(creator_id))
    profile.analysis = {
        "audience_inference": {
            "primary_language": {
                "status": "available",
                "value": "English",
                "provenance": "ai_inference",
            }
        }
    }
    session.commit()
    assert (
        auth_client.get(f"/api/v2/library/creators/{creator_id}").json()["languages"]
        == []
    )
    profile.current_facts = {**profile.current_facts, "languages": []}
    profile.works[0].source_fields = {
        **profile.works[0].source_fields,
        "language": "en",
    }
    session.commit()
    assert (
        auth_client.get(f"/api/v2/library/creators/{creator_id}").json()["languages"]
        == []
    )
