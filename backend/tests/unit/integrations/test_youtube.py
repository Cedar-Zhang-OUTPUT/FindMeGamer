import logging
from datetime import datetime, timezone

import httpx
import pytest

from app.analysis.targets import canonicalize_target
from app.db.models.enums import TargetType
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.youtube import YouTubeGateway


class _OverrideYouTubeKeyAuth(httpx.Auth):
    def __init__(self, *, append: bool) -> None:
        self.append = append
        self.calls = 0

    def auth_flow(self, request: httpx.Request):
        self.calls += 1
        if self.append:
            request.headers = httpx.Headers(
                [
                    *request.headers.multi_items(),
                    ("X-Goog-Api-Key", "auth-extra-key"),
                ]
            )
        else:
            request.headers["X-Goog-Api-Key"] = "auth-wrong-key"
        yield request


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
                                "channelId": "UC123456",
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


def test_youtube_api_key_uses_header_and_never_completed_request_url_or_logs(
    caplog,
) -> None:
    secret = "youtube-success-key-canary"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [{"id": "UCresolved123"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    target = canonicalize_target(TargetType.CREATOR, "https://youtube.com/@example")

    caplog.set_level(logging.INFO, logger="httpx")
    caplog.set_level(logging.INFO, logger="httpcore")
    with caplog.at_level(logging.INFO):
        resolved = YouTubeGateway(api_key=secret, http_client=client).resolve_channel(
            target
        )

    assert resolved == "UCresolved123"
    assert secret not in caplog.text
    assert len(requests) == 1
    assert requests[0].headers.get_list("x-goog-api-key") == [secret]
    assert "key" not in requests[0].url.params
    assert secret not in str(requests[0].url)


@pytest.mark.parametrize("append", [False, True])
def test_youtube_disables_injected_client_auth_for_api_key_header(
    append: bool, caplog
) -> None:
    secret = "youtube-client-auth-canary"
    auth = _OverrideYouTubeKeyAuth(append=append)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [{"id": "UCresolved123"}]})

    client = httpx.Client(auth=auth, transport=httpx.MockTransport(handler))
    target = canonicalize_target(TargetType.CREATOR, "https://youtube.com/@example")

    with caplog.at_level(logging.DEBUG):
        resolved = YouTubeGateway(api_key=secret, http_client=client).resolve_channel(
            target
        )

    assert resolved == "UCresolved123"
    assert auth.calls == 0
    assert requests[0].headers.get_list("x-goog-api-key") == [secret]
    assert "key" not in requests[0].url.params
    assert secret not in f"{requests[0].url}{caplog.text}"
    assert not client.is_closed


def test_youtube_replaces_duplicate_injected_client_default_key_headers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [{"id": "UCresolved123"}]})

    client = httpx.Client(
        headers=[
            ("X-Goog-Api-Key", "default-wrong-key"),
            ("X-Goog-Api-Key", "default-extra-key"),
        ],
        transport=httpx.MockTransport(handler),
    )
    original_headers = client.headers.get_list("x-goog-api-key")
    target = canonicalize_target(TargetType.CREATOR, "https://youtube.com/@example")

    YouTubeGateway(api_key="correct-key", http_client=client).resolve_channel(target)

    assert requests[0].headers.get_list("x-goog-api-key") == ["correct-key"]
    assert client.headers.get_list("x-goog-api-key") == original_headers


@pytest.mark.parametrize(
    ("status", "error_type", "code"),
    [
        (400, PermanentIntegrationError, "youtube_request_rejected"),
        (429, TransientIntegrationError, "youtube_unavailable"),
        (503, TransientIntegrationError, "youtube_unavailable"),
    ],
)
def test_youtube_http_error_redaction_keeps_api_key_out_of_url_and_logs(
    status: int,
    error_type: type[Exception],
    code: str,
    caplog,
) -> None:
    secret = "youtube-http-error-key-canary"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, text="provider body")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.INFO), pytest.raises(error_type, match=code) as caught:
        YouTubeGateway(api_key=secret, http_client=client).fetch_creator("UC123456")

    rendered = f"{caught.value!s}{caught.value!r}{caplog.text}{requests[0].url}"
    assert secret not in rendered
    assert requests[0].headers.get_list("x-goog-api-key") == [secret]
    assert "key" not in requests[0].url.params


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


@pytest.mark.parametrize("returned_channel_id", ["UCother123", None])
def test_youtube_rejects_public_video_from_missing_or_different_channel(
    returned_channel_id: str | None, caplog
) -> None:
    secret_body_value = "cross-channel-provider-canary"

    def handler(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(200, json=_channel_response())
        if endpoint == "playlistItems":
            return httpx.Response(
                200,
                json={"items": [{"contentDetails": {"videoId": "video-001"}}]},
            )
        if endpoint == "videos":
            item = _video_item("video-001")
            snippet = item["snippet"]
            assert isinstance(snippet, dict)
            if returned_channel_id is None:
                snippet.pop("channelId")
            else:
                snippet["channelId"] = returned_channel_id
            snippet["description"] = secret_body_value
            return httpx.Response(200, json={"items": [item]})
        raise AssertionError(f"unexpected endpoint {endpoint}")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.DEBUG), pytest.raises(
        PermanentIntegrationError, match="youtube_response_invalid"
    ) as caught:
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")

    assert secret_body_value not in f"{caught.value!s}{caught.value!r}{caplog.text}"


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


def _single_video_client(video: dict[str, object]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(200, json=_channel_response())
        if endpoint == "playlistItems":
            return httpx.Response(
                200,
                json={"items": [{"contentDetails": {"videoId": "video-001"}}]},
            )
        if endpoint == "videos":
            return httpx.Response(200, json={"items": [video]})
        raise AssertionError(f"unexpected endpoint {endpoint}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_youtube_normalizes_offset_and_fractional_timestamps_to_aware_utc() -> None:
    video = _video_item("video-001")
    snippet = video["snippet"]
    assert isinstance(snippet, dict)
    snippet["publishedAt"] = "2026-09-01T08:30:15.123456+08:00"

    source = YouTubeGateway(
        api_key="test-key", http_client=_single_video_client(video)
    ).fetch_creator("UC123456")

    assert source.published_at == datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert source.videos[0].published_at == datetime(
        2026, 9, 1, 0, 30, 15, 123456, tzinfo=timezone.utc
    )
    assert source.videos[0].published_at.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "published_at",
    [
        "2026-09-01T00:00:00",
        "2026-13-01T00:00:00Z",
        "not-a-date",
        123,
        "2026-09-01 00:00:00Z",
        "x" * 65,
    ],
)
def test_youtube_rejects_present_malformed_video_timestamp(
    published_at: object, caplog
) -> None:
    raw_canary = "malformed-video-time-canary"
    video = _video_item("video-001")
    snippet = video["snippet"]
    assert isinstance(snippet, dict)
    snippet["publishedAt"] = published_at
    snippet["description"] = raw_canary

    with caplog.at_level(logging.DEBUG), pytest.raises(
        PermanentIntegrationError, match="youtube_response_invalid"
    ) as caught:
        YouTubeGateway(
            api_key="test-key", http_client=_single_video_client(video)
        ).fetch_creator("UC123456")

    assert raw_canary not in f"{caught.value!s}{caught.value!r}{caplog.text}"


def test_youtube_rejects_present_offset_free_channel_timestamp() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response = _channel_response()
        channel = response["items"]
        assert isinstance(channel, list)
        snippet = channel[0]["snippet"]
        assert isinstance(snippet, dict)
        snippet["publishedAt"] = "2020-01-02T03:04:05"
        return httpx.Response(200, json=response)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(PermanentIntegrationError, match="youtube_response_invalid"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")


@pytest.mark.parametrize(
    "duration",
    [
        "P",
        "PT",
        "P1DT",
        "not-a-duration",
        123,
        "P999999999D",
        "PT999999999999S",
        "p1D",
        "P1d",
        "P1Dt1H",
        "PT1.5S",
        "PT1S1S",
        "PT1M1H",
        "P-1D",
        "P+1D",
        "PT-1S",
        "PT+1S",
        "PT24H",
        "PT60M",
        "PT60S",
        "P01D",
        "PT01H",
        "P3652DT12H1S",
        "PT1٢S",
        "P1٢D",
        "PT1２S",
        "P1२D",
    ],
)
def test_youtube_rejects_present_malformed_or_unbounded_duration(
    duration: object,
) -> None:
    video = _video_item("video-001")
    content = video["contentDetails"]
    assert isinstance(content, dict)
    content["duration"] = duration

    with pytest.raises(PermanentIntegrationError, match="youtube_response_invalid"):
        YouTubeGateway(
            api_key="test-key", http_client=_single_video_client(video)
        ).fetch_creator("UC123456")


@pytest.mark.parametrize("caption", ["TRUE", "False", "", True, 1])
def test_youtube_rejects_present_nonofficial_caption_flag(caption: object) -> None:
    video = _video_item("video-001")
    content = video["contentDetails"]
    assert isinstance(content, dict)
    content["caption"] = caption

    with pytest.raises(PermanentIntegrationError, match="youtube_response_invalid"):
        YouTubeGateway(
            api_key="test-key", http_client=_single_video_client(video)
        ).fetch_creator("UC123456")


@pytest.mark.parametrize(
    ("duration", "expected_seconds"),
    [
        ("PT0S", 0),
        ("P0D", 0),
        ("P0DT0S", 0),
        ("P1D", 86_400),
        ("P1DT2H3M4S", 93_784),
        ("P3652DT12H", 315_576_000),
    ],
)
def test_youtube_accepts_zero_and_bounded_iso_duration(
    duration: str, expected_seconds: int
) -> None:
    video = _video_item("video-001")
    content = video["contentDetails"]
    assert isinstance(content, dict)
    content["duration"] = duration

    source = YouTubeGateway(
        api_key="test-key", http_client=_single_video_client(video)
    ).fetch_creator("UC123456")

    assert source.videos[0].duration_seconds == expected_seconds


def test_youtube_keeps_missing_optional_typed_video_fields_as_none() -> None:
    video = _video_item("video-001")
    snippet = video["snippet"]
    content = video["contentDetails"]
    assert isinstance(snippet, dict)
    assert isinstance(content, dict)
    snippet.pop("publishedAt")
    content.pop("duration")
    content.pop("caption")

    source = YouTubeGateway(
        api_key="test-key", http_client=_single_video_client(video)
    ).fetch_creator("UC123456")

    assert source.videos[0].published_at is None
    assert source.videos[0].duration_seconds is None
    assert source.videos[0].caption_available is None


@pytest.mark.parametrize(
    "tokens",
    [
        ["token-a", "token-a"],
        ["token-a", "token-b", "token-a"],
    ],
)
def test_youtube_rejects_pagination_token_cycle_before_redundant_request(
    tokens: list[str], caplog
) -> None:
    playlist_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal playlist_requests
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(200, json=_channel_response())
        if endpoint == "playlistItems":
            token = tokens[playlist_requests]
            playlist_requests += 1
            return httpx.Response(
                200,
                json={
                    "items": [],
                    "nextPageToken": token,
                    "providerCanary": "pagination-cycle-secret",
                },
            )
        raise AssertionError("cycle must fail before video fetch")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.DEBUG), pytest.raises(
        PermanentIntegrationError, match="youtube_response_invalid"
    ) as caught:
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")

    assert playlist_requests == len(tokens)
    assert (
        "pagination-cycle-secret"
        not in f"{caught.value!s}{caught.value!r}{caplog.text}"
    )


@pytest.mark.parametrize("next_token", [123, "x" * 513, ""])
def test_youtube_rejects_malformed_page_token_after_one_page(
    next_token: object,
) -> None:
    playlist_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal playlist_requests
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(200, json=_channel_response())
        if endpoint == "playlistItems":
            playlist_requests += 1
            return httpx.Response(200, json={"items": [], "nextPageToken": next_token})
        raise AssertionError("malformed token must stop pagination")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(PermanentIntegrationError, match="youtube_response_invalid"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")

    assert playlist_requests == 1


@pytest.mark.parametrize(
    "next_token",
    [
        "token,other",
        "token&other",
        "token=other",
        "token\nother",
        "token other",
        "token\tother",
        "töken",
        "token%20other",
        "token/other",
        "token\\other",
        "token+other",
        "token?other",
        "token#other",
    ],
)
def test_youtube_rejects_non_url_safe_page_token_before_second_request(
    next_token: str,
) -> None:
    playlist_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal playlist_requests
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(200, json=_channel_response())
        if endpoint == "playlistItems":
            playlist_requests += 1
            return httpx.Response(
                200,
                json=(
                    {"items": [], "nextPageToken": next_token}
                    if playlist_requests == 1
                    else {"items": []}
                ),
            )
        raise AssertionError("invalid page token must stop pagination")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(PermanentIntegrationError, match="youtube_response_invalid"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")

    assert playlist_requests == 1


@pytest.mark.parametrize("next_token", ["A", "abcDEF012-_", "x" * 512])
def test_youtube_accepts_bounded_ascii_url_safe_page_token(next_token: str) -> None:
    playlist_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal playlist_requests
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(200, json=_channel_response())
        if endpoint == "playlistItems":
            playlist_requests += 1
            if playlist_requests == 1:
                return httpx.Response(
                    200, json={"items": [], "nextPageToken": next_token}
                )
            assert request.url.params["pageToken"] == next_token
            return httpx.Response(200, json={"items": []})
        raise AssertionError(f"unexpected endpoint {endpoint}")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    source = YouTubeGateway(api_key="test-key", http_client=client).fetch_creator(
        "UC123456"
    )

    assert source.videos == ()
    assert playlist_requests == 2


def test_youtube_duplicate_video_response_keeps_first_official_mapping() -> None:
    first = _video_item("video-001")
    second = _video_item("video-001")
    first_snippet = first["snippet"]
    second_snippet = second["snippet"]
    assert isinstance(first_snippet, dict)
    assert isinstance(second_snippet, dict)
    first_snippet["title"] = "First mapping"
    second_snippet["title"] = "Second mapping"

    def handler(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(200, json=_channel_response())
        if endpoint == "playlistItems":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"contentDetails": {"videoId": "video-001"}},
                        {"contentDetails": {"videoId": "video-001"}},
                    ]
                },
            )
        if endpoint == "videos":
            return httpx.Response(200, json={"items": [first, second]})
        raise AssertionError(f"unexpected endpoint {endpoint}")

    source = YouTubeGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).fetch_creator("UC123456")

    assert len(source.videos) == 1
    assert source.videos[0].title == "First mapping"


def test_youtube_rejects_playlist_video_id_with_query_delimiter() -> None:
    video_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal video_requests
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            return httpx.Response(200, json=_channel_response())
        if endpoint == "playlistItems":
            return httpx.Response(
                200,
                json={
                    "items": [{"contentDetails": {"videoId": "video-001,video-002"}}]
                },
            )
        if endpoint == "videos":
            video_requests += 1
            return httpx.Response(200, json={"items": []})
        raise AssertionError(f"unexpected endpoint {endpoint}")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(PermanentIntegrationError, match="youtube_response_invalid"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")

    assert video_requests == 0


def test_youtube_rejects_uploads_playlist_id_with_query_delimiter() -> None:
    playlist_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal playlist_requests
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "channels":
            response = _channel_response()
            items = response["items"]
            assert isinstance(items, list)
            content = items[0]["contentDetails"]
            assert isinstance(content, dict)
            content["relatedPlaylists"] = {"uploads": "UU123,other"}
            return httpx.Response(200, json=response)
        if endpoint == "playlistItems":
            playlist_requests += 1
            return httpx.Response(200, json={"items": []})
        raise AssertionError(f"unexpected endpoint {endpoint}")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(PermanentIntegrationError, match="youtube_response_invalid"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")

    assert playlist_requests == 0


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

    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(recording_handler))

    with caplog.at_level(logging.DEBUG), pytest.raises(
        TransientIntegrationError, match="youtube_unavailable"
    ) as caught:
        YouTubeGateway(api_key=secret, http_client=client).fetch_creator("UC123456")

    assert (
        secret not in f"{caught.value!s}{caught.value!r}{caplog.text}{requests[0].url}"
    )
    assert requests[0].headers.get_list("x-goog-api-key") == [secret]
    assert "key" not in requests[0].url.params


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


def test_youtube_stops_streaming_at_cap_and_closes_lying_length_response(
    monkeypatch, gateway_byte_stream_factory, caplog
) -> None:
    monkeypatch.setattr("app.integrations.youtube.MAX_YOUTUBE_RESPONSE_BYTES", 5)
    secret = "youtube-unread-stream-canary"
    stream = gateway_byte_stream_factory([b"1234", b"56", secret.encode()])
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            headers={"Content-Length": "1"},
            stream=stream,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    target = canonicalize_target(TargetType.CREATOR, "https://youtube.com/@example")

    with caplog.at_level(logging.DEBUG), pytest.raises(
        PermanentIntegrationError, match="youtube_response_too_large"
    ) as caught:
        YouTubeGateway(api_key="test-key", http_client=client).resolve_channel(target)

    assert requests == 1
    assert stream.yielded == 2
    assert stream.closed is True
    assert secret not in f"{caught.value!s}{caught.value!r}{caplog.text}"


def test_youtube_reads_bounded_403_body_for_quota_reason(
    gateway_byte_stream_factory,
) -> None:
    stream = gateway_byte_stream_factory(
        [b'{"error":{"errors":[', b'{"reason":"quotaExceeded"}]}}']
    )
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(403, stream=stream)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(TransientIntegrationError, match="youtube_quota_unavailable"):
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")

    assert requests == 1
    assert stream.yielded == 2
    assert stream.closed is True


def test_youtube_does_not_read_rate_limit_body(
    gateway_byte_stream_factory, caplog
) -> None:
    secret = "youtube-rate-limit-body-canary"
    stream = gateway_byte_stream_factory([secret.encode(), b"unused"])
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(429, stream=stream)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.DEBUG), pytest.raises(
        TransientIntegrationError, match="youtube_unavailable"
    ) as caught:
        YouTubeGateway(api_key="test-key", http_client=client).fetch_creator("UC123456")

    assert requests == 1
    assert stream.yielded == 0
    assert stream.closed is True
    assert secret not in f"{caught.value!s}{caught.value!r}{caplog.text}"


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
