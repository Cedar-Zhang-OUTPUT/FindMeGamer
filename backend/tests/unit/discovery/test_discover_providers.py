import httpx
import pytest

from app.schemas.discover import DiscoverConditions


def test_youtube_deduplicates_authors_uses_audio_and_postfilters_subscribers():
    from app.integrations.youtube_discovery import YouTubeDiscovery

    def respond(request):
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "search":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": {"videoId": v}, "snippet": {"channelId": c}}
                        for v, c in [
                            ("v1", "UCaaaaaaa"),
                            ("v2", "UCaaaaaaa"),
                            ("v3", "UCbbbbbbb"),
                            ("v4", "UCccccccc"),
                        ]
                    ]
                },
            )
        if endpoint == "videos":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "v1",
                            "snippet": {
                                "channelId": "UCaaaaaaa",
                                "defaultAudioLanguage": "en-US",
                            },
                        },
                        {
                            "id": "v2",
                            "snippet": {
                                "channelId": "UCaaaaaaa",
                                "defaultAudioLanguage": "en",
                            },
                        },
                        {
                            "id": "v3",
                            "snippet": {
                                "channelId": "UCbbbbbbb",
                                "defaultLanguage": "en",
                            },
                        },
                        {
                            "id": "v4",
                            "snippet": {
                                "channelId": "UCccccccc",
                                "defaultAudioLanguage": "en",
                            },
                        },
                    ]
                },
            )
        assert endpoint == "channels"
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": c, "snippet": {"title": c}, "statistics": stats}
                    for c, stats in [
                        ("UCaaaaaaa", {"subscriberCount": "1000"}),
                        ("UCbbbbbbb", {"subscriberCount": "2000"}),
                        ("UCccccccc", {"hiddenSubscriberCount": True}),
                    ]
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider = YouTubeDiscovery(api_key="test", http_client=client)
        rows = [
            r
            for page in provider.search(
                ["horror"],
                DiscoverConditions(content_languages=["en"], min_followers=100),
                limit=100,
            )
            for r in page
        ]
        assert [(r.platform_account_id, r.content_languages) for r in rows] == [
            ("UCaaaaaaa", ["en"])
        ]
        any_rows = [
            r
            for page in provider.search(["horror"], DiscoverConditions(), limit=100)
            for r in page
        ]
        assert len(any_rows) == 3
        assert any_rows[-1].followers is None


def test_x_dedup_languages_and_bounded_repeated_pagination():
    from app.integrations.x_discovery import XDiscovery

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "1", "author_id": "10", "lang": "en"},
                    {"id": "2", "author_id": "10", "lang": "en-US"},
                    {"id": "3", "author_id": "11", "lang": "fr"},
                ],
                "includes": {
                    "users": [
                        {
                            "id": "10",
                            "name": "Author",
                            "public_metrics": {"followers_count": 1000},
                        },
                        {
                            "id": "11",
                            "name": "French",
                            "public_metrics": {"followers_count": 1000},
                        },
                    ]
                },
                "meta": {"next_token": "repeated"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        rows = [
            r
            for page in XDiscovery(api_key="test", http_client=client).search(
                ["horror"], DiscoverConditions(content_languages=["en"]), limit=100
            )
            for r in page
        ]
    assert [r.platform_account_id for r in rows] == ["10"]
    assert rows[0].canonical_url == "https://x.com/i/user/10"
    assert len(calls) <= 3
    assert "lang:en" in calls[0].url.params["query"]


@pytest.mark.parametrize(
    "status, code",
    [(402, "x_payment_required"), (403, "x_request_rejected"), (429, "x_rate_limited")],
)
def test_x_failure_is_safe(status, code):
    from app.integrations.x_discovery import XDiscovery
    from app.integrations.errors import (
        PermanentIntegrationError,
        TransientIntegrationError,
    )

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status, json={"detail": "private-provider-detail"}
            )
        )
    ) as client:
        with pytest.raises(
            (PermanentIntegrationError, TransientIntegrationError)
        ) as error:
            list(
                XDiscovery(api_key="test", http_client=client).search(
                    ["horror"], DiscoverConditions(), limit=100
                )
            )
        assert error.value.code == code
        assert "private-provider-detail" not in str(error.value)
