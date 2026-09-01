import logging
import httpx
import pytest

from app.analysis.targets import canonicalize_target
from app.db.models.enums import TargetType
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.youtube import YouTubeGateway


def test_youtube_fetches_only_fifty_recent_videos() -> None:
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC123456",
                            "snippet": {"title": "Example"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "UU123456"}
                            },
                            "statistics": {},
                            "brandingSettings": {},
                        }
                    ]
                },
            )
        if endpoint == "playlistItems":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"contentDetails": {"videoId": f"video-{index:03d}"}}
                        for index in range(50)
                    ]
                },
            )
        if endpoint == "videos":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": video_id,
                            "snippet": {
                                "title": video_id,
                                "publishedAt": "2026-09-01T00:00:00Z",
                            },
                            "contentDetails": {"duration": "PT1M"},
                            "statistics": {},
                            "status": {"privacyStatus": "public"},
                        }
                        for video_id in request.url.params["id"].split(",")
                    ]
                },
            )
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = YouTubeGateway(api_key="test-key", http_client=client)

    source = gateway.fetch_creator("UC123456", video_limit=50)

    assert len(source.videos) == 50
    assert all(request.url.host == "www.googleapis.com" for request in requests_seen)


def test_youtube_resolves_handle_with_official_channels_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [{"id": "UCresolved123"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = YouTubeGateway(api_key="canary-api-key", http_client=client)
    target = canonicalize_target(
        TargetType.CREATOR, "https://youtube.com/@ExampleCreator"
    )

    assert gateway.resolve_channel(target) == "UCresolved123"
    assert len(requests) == 1
    assert requests[0].url.path == "/youtube/v3/channels"
    assert requests[0].url.params["forHandle"] == "@examplecreator"
    assert requests[0].url.params["part"] == "id"


def test_youtube_returns_valid_channel_id_without_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("channel ID targets must not make a request")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = YouTubeGateway(api_key="test-key", http_client=client)
    target = canonicalize_target(
        TargetType.CREATOR, "https://youtube.com/channel/UCabc123"
    )

    assert gateway.resolve_channel(target) == "UCabc123"


@pytest.mark.parametrize(
    "items", [[], [{"id": "bad"}], [{"id": "UCone123"}, {"id": "UCtwo123"}]]
)
def test_youtube_rejects_missing_or_ambiguous_handle_resolution(
    items: list[dict[str, str]],
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"items": items})
        )
    )
    target = canonicalize_target(TargetType.CREATOR, "https://youtube.com/@example")

    with pytest.raises(PermanentIntegrationError, match="youtube_channel_not_found"):
        YouTubeGateway(api_key="test-key", http_client=client).resolve_channel(target)


def test_youtube_paginates_deduplicates_filters_private_and_preserves_recent_order() -> (
    None
):
    requests: list[httpx.Request] = []
    first_ids = [f"video-{index:03d}" for index in range(50)]
    second_ids = ["video-049", *[f"video-{index:03d}" for index in range(50, 61)]]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(200, json=_channel_response(hidden=True))
        if endpoint == "playlistItems":
            if "pageToken" not in request.url.params:
                ids, token = first_ids, "next-page"
            else:
                ids, token = second_ids, None
            body: dict[str, object] = {
                "items": [{"contentDetails": {"videoId": value}} for value in ids]
            }
            if token:
                body["nextPageToken"] = token
            return httpx.Response(200, json=body)
        if endpoint == "videos":
            items = []
            for video_id in request.url.params["id"].split(","):
                if video_id == "video-010":
                    continue
                items.append(
                    _video_item(
                        video_id,
                        privacy="private" if video_id < "video-010" else "public",
                    )
                )
            return httpx.Response(200, json={"items": items})
        raise AssertionError(f"unexpected endpoint {endpoint}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = YouTubeGateway(api_key="test-key", http_client=client).fetch_creator(
        "UC123456", video_limit=50
    )

    assert [video.id for video in source.videos] == [
        *[f"video-{index:03d}" for index in range(11, 50)],
        *[f"video-{index:03d}" for index in range(50, 61)],
    ]
    assert source.subscriber_count is None
    assert source.hidden_subscriber_count is True
    assert source.videos[0].duration_seconds == 62
    assert len(source.raw_playlist_pages) == 2
    assert all(
        request.url.path.rsplit("/", 1)[-1] in {"channels", "playlistItems", "videos"}
        for request in requests
    )
    assert all(
        len(request.url.params["id"].split(",")) <= 50
        for request in requests
        if request.url.path.endswith("/videos")
    )


def _channel_response(*, hidden: bool = False) -> dict[str, object]:
    statistics: dict[str, object] = {
        "hiddenSubscriberCount": hidden,
        "viewCount": "12345",
        "videoCount": "99",
    }
    if not hidden:
        statistics["subscriberCount"] = "678"
    return {
        "items": [
            {
                "id": "UC123456",
                "snippet": {
                    "title": "Example Creator",
                    "description": "Channel description",
                    "customUrl": "@example",
                    "publishedAt": "2020-01-02T03:04:05Z",
                    "country": "US",
                    "thumbnails": {
                        "default": {"url": "https://cdn.example/avatar.jpg"}
                    },
                },
                "contentDetails": {"relatedPlaylists": {"uploads": "UU123456"}},
                "statistics": statistics,
                "brandingSettings": {
                    "image": {"bannerExternalUrl": "https://cdn.example/banner.jpg"}
                },
            }
        ]
    }


def _video_item(video_id: str, *, privacy: str = "public") -> dict[str, object]:
    return {
        "id": video_id,
        "snippet": {
            "title": f"Title {video_id}",
            "description": "Description",
            "publishedAt": "2026-09-01T00:00:00Z",
            "channelId": "UC123456",
            "tags": ["games", "review"],
            "categoryId": "20",
            "thumbnails": {"high": {"url": f"https://cdn.example/{video_id}.jpg"}},
        },
        "contentDetails": {
            "duration": "PT1M2S",
            "definition": "hd",
            "caption": "false",
        },
        "statistics": {"viewCount": "100", "likeCount": "5", "commentCount": "2"},
        "status": {"privacyStatus": privacy},
    }


@pytest.mark.parametrize("video_limit", [0, 51, -1, True])
def test_youtube_rejects_invalid_video_limit_before_network(video_limit: int) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("network called"))
        )
    )

    with pytest.raises(PermanentIntegrationError, match="youtube_video_limit_invalid"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator(
            "UC123456", video_limit=video_limit
        )


def test_youtube_rejects_invalid_channel_id_before_network() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("network called"))
        )
    )

    with pytest.raises(PermanentIntegrationError, match="youtube_channel_id_invalid"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("@handle")


@pytest.mark.parametrize("status", [400, 404])
def test_youtube_classifies_ordinary_client_errors_as_permanent(status: int) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status, json={"error": {"message": "secret"}}
            )
        )
    )

    with pytest.raises(PermanentIntegrationError, match="youtube_request_rejected"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_youtube_classifies_rate_limit_and_server_errors_as_transient(
    status: int,
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={}))
    )

    with pytest.raises(TransientIntegrationError, match="youtube_unavailable"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")


def test_youtube_classifies_quota_403_as_transient() -> None:
    response = {
        "error": {"errors": [{"reason": "quotaExceeded"}], "message": "key=secret"}
    }
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json=response)
        )
    )

    with pytest.raises(TransientIntegrationError, match="youtube_quota_unavailable"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")


def test_youtube_classifies_nonquota_403_as_permanent() -> None:
    response = {"error": {"errors": [{"reason": "forbidden"}]}}
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json=response)
        )
    )

    with pytest.raises(PermanentIntegrationError, match="youtube_request_rejected"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")


def test_youtube_timeout_and_secret_are_safely_redacted(caplog) -> None:
    secret = "youtube-api-key-canary"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout(
            f"Authorization={secret}; url={request.url}", request=request
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.DEBUG), pytest.raises(
        TransientIntegrationError, match="youtube_unavailable"
    ) as caught:
        YouTubeGateway(api_key=secret, http_client=client).fetch_creator("UC123456")

    assert secret not in f"{caught.value!s}{caught.value!r}{caplog.text}"


def test_youtube_rejects_malformed_and_oversized_responses() -> None:
    malformed = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"items": "bad"})
        )
    )
    oversized = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * 4_100_000)
        )
    )

    with pytest.raises(PermanentIntegrationError, match="youtube_response_invalid"):
        YouTubeGateway(api_key="test-key", http_client=malformed).fetch_creator(
            "UC123456"
        )
    with pytest.raises(PermanentIntegrationError, match="youtube_response_too_large"):
        YouTubeGateway(api_key="test-key", http_client=oversized).fetch_creator(
            "UC123456"
        )


def test_youtube_respects_caller_client_ownership() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )
    gateway = YouTubeGateway(api_key="test-key", http_client=client)

    gateway.close()

    assert not client.is_closed


def test_youtube_closes_owned_client() -> None:
    gateway = YouTubeGateway(
        api_key="test-key", base_url="http://localhost:18081/youtube/v3"
    )

    gateway.close()

    assert gateway.is_closed
