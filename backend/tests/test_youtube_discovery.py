import importlib

import httpx
import pytest

from app.schemas.discovery import DiscoveryRequest

CHANNEL = "UCabcdefghijklmnopqrstuv"


def test_language_is_taken_from_official_video_metadata_not_guessed_from_title():
    calls = []

    def handler(req):
        calls.append(req.url.path.rsplit("/", 1)[-1])
        if calls[-1] == "search":
            return httpx.Response(200, json={"items": [video(), video("second12345")]})
        if calls[-1] == "channels":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": CHANNEL,
                            "snippet": {"country": "US"},
                            "statistics": {"subscriberCount": "1000"},
                        }
                    ]
                },
            )
        assert calls[-1] == "videos"
        assert req.url.params["part"] == "snippet"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "video123456",
                        "snippet": {
                            "defaultAudioLanguage": "en-US",
                            "defaultLanguage": "ja",
                        },
                    },
                    {"id": "second12345", "snippet": {}},
                ]
            },
        )

    result = gateway(handler).discover(
        DiscoveryRequest(platform="youtube", query="horror gameplay", max_requests=3)
    )
    assert calls == ["search", "channels", "videos"]
    assert result.requests_used == 3
    assert [c.language for c in result.contents] == ["en-US", None]
    assert [c.language_source for c in result.contents] == [
        "defaultAudioLanguage",
        None,
    ]


@pytest.mark.parametrize("cap", [2, 3])
def test_language_metadata_failure_or_insufficient_cap_never_guesses(cap):
    seen = []

    def handler(req):
        path = req.url.path.rsplit("/", 1)[-1]
        seen.append(path)
        if path == "search":
            return httpx.Response(200, json={"items": [video()]})
        if path == "channels":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": CHANNEL,
                            "snippet": {"country": "US", "defaultLanguage": "en"},
                            "statistics": {},
                        }
                    ]
                },
            )
        return httpx.Response(429)

    result = gateway(handler).discover(
        DiscoveryRequest(
            platform="youtube", query="English horror gameplay", max_requests=cap
        )
    )
    assert len(seen) == result.requests_used == cap
    assert result.contents[0].language is None
    assert result.contents[0].language_source is None
    if cap == 3:
        assert result.issues[0].code == "rate_limited"


@pytest.mark.parametrize("status", [400, 422])
def test_invalid_query_or_cursor_does_not_claim_service_unavailable(status):
    result = gateway(lambda req: httpx.Response(status)).discover(
        DiscoveryRequest(platform="youtube", query="games")
    )
    assert result.issues[0].code == "invalid_request"
    assert result.issues[0].retryable is False


@pytest.mark.parametrize(
    "reason",
    [
        "quotaExceeded",
        "dailyLimitExceeded",
        "userRateLimitExceeded",
        "rateLimitExceeded",
    ],
)
def test_quota_forbidden_is_retryable_rate_limit_without_reflecting_body(reason):
    result = gateway(
        lambda req: httpx.Response(
            403,
            json={
                "error": {
                    "message": "fake-secret-canary",
                    "errors": [{"reason": reason}],
                }
            },
        )
    ).discover(DiscoveryRequest(platform="youtube", query="games"))
    assert result.issues[0].code == "rate_limited"
    assert result.issues[0].retryable is True
    assert "fake-secret-canary" not in result.model_dump_json()


def gateway(handler):
    module = importlib.import_module("app.integrations.youtube_discovery")
    return module.YouTubeDiscoveryGateway(
        api_key="fake-secret-canary",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def video(video_id="video123456", channel=CHANNEL):
    return {
        "id": {"videoId": video_id},
        "snippet": {
            "channelId": channel,
            "channelTitle": "Search Name",
            "title": "A game",
            "description": "Not watched",
            "publishedAt": "2026-09-01T01:02:03Z",
        },
    }


def test_video_search_deduplicates_accounts_and_contents_and_enriches():
    seen = []

    def handler(req):
        seen.append(req)
        assert req.headers["X-Goog-Api-Key"] == "fake-secret-canary"
        assert "key" not in req.url.params
        if req.url.path.endswith("/search"):
            assert req.url.params["type"] == "video"
            assert req.url.params["q"] == "roguelike|strategy"
            assert req.url.params["regionCode"] == "US"
            assert req.url.params["relevanceLanguage"] == "en"
            return httpx.Response(
                200,
                json={
                    "items": [video(), video(), video("second12345")],
                    "nextPageToken": "NEXT",
                },
            )
        assert req.url.params["id"] == CHANNEL
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": CHANNEL,
                        "snippet": {
                            "title": "Real Name",
                            "country": "CA",
                            "customUrl": "@real",
                            "description": "Games",
                        },
                        "statistics": {
                            "subscriberCount": "1200",
                            "hiddenSubscriberCount": False,
                        },
                    }
                ]
            },
        )

    request = DiscoveryRequest(
        platform="youtube",
        query="roguelike|strategy",
        region_hint="US",
        language_hint="en",
    )
    result = gateway(handler).discover(request)
    assert result.status == "more"
    assert result.requests_used == 2
    assert result.provider_items_received == 3
    assert len(result.accounts) == 1
    assert result.accounts[0].follower_count == 1200
    assert result.accounts[0].country == "CA"
    assert (
        result.accounts[0].profile_url == f"https://www.youtube.com/channel/{CHANNEL}"
    )
    assert result.accounts[0].handle == "@real"
    assert len(result.contents) == 2
    assert result.contents[0].evidence_status == "unverified"
    assert result.contents[0].language is None
    assert result.next_cursor.token == "NEXT"
    assert result.next_cursor.query_fingerprint == request.fingerprint()
    assert "fake-secret-canary" not in result.model_dump_json()


def test_empty_page_preserves_next_cursor_and_followup_token():
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json={"items": [], "nextPageToken": "NEXT"})

    gw = gateway(handler)
    first = gw.discover(DiscoveryRequest(platform="youtube", query="games"))
    second = gw.discover(
        DiscoveryRequest(platform="youtube", query="games", cursor=first.next_cursor)
    )
    assert first.status == "more" and second.status == "more"
    assert first.requests_used == 1
    assert seen[1]["pageToken"] == "NEXT"


@pytest.mark.parametrize(
    "statistics",
    [
        {},
        {"subscriberCount": "23", "hiddenSubscriberCount": True},
        {"subscriberCount": "oops"},
    ],
)
def test_channel_mode_missing_or_hidden_followers_stay_unknown(statistics):
    def handler(req):
        if req.url.path.endswith("/search"):
            assert req.url.params["type"] == "channel"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": {"channelId": CHANNEL}, "snippet": {"title": "Name"}}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": CHANNEL,
                        "snippet": {"title": "Name"},
                        "statistics": statistics,
                    }
                ]
            },
        )

    result = gateway(handler).discover(
        DiscoveryRequest(
            platform="youtube", query="games", search_mode="channel", region_hint="US"
        )
    )
    assert result.accounts[0].follower_count is None
    assert result.accounts[0].country is None
    assert not result.contents


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "unauthorized"),
        (403, "forbidden"),
        (429, "rate_limited"),
        (500, "unavailable"),
    ],
)
def test_http_failure_is_secret_safe_and_does_not_retry(status, code):
    result = gateway(
        lambda req: httpx.Response(
            status, headers={"Retry-After": "12"}, text="fake-secret-canary"
        )
    ).discover(DiscoveryRequest(platform="youtube", query="games"))
    assert result.status == "failed"
    assert result.requests_used == 1
    assert result.issues[0].code == code
    assert "fake-secret-canary" not in result.model_dump_json()
    if status == 429:
        assert result.issues[0].retry_after_seconds == 12


def test_timeout_is_reported_without_exception_details():
    def handler(req):
        raise httpx.ReadTimeout("fake-secret-canary", request=req)

    result = gateway(handler).discover(
        DiscoveryRequest(platform="youtube", query="games")
    )
    assert result.issues[0].code == "timeout"
    assert result.requests_used == 1
    assert "fake-secret-canary" not in result.model_dump_json()


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"items":null}'])
def test_invalid_response_not_reported_as_empty_success(body):
    result = gateway(lambda req: httpx.Response(200, content=body)).discover(
        DiscoveryRequest(platform="youtube", query="games")
    )
    assert result.status == "failed"
    assert result.issues[0].code == "invalid_response"


@pytest.mark.parametrize(
    "enrichment", [httpx.Response(429), httpx.Response(200, json={"items": []})]
)
def test_partial_enrichment_retains_search_facts_and_cursor(enrichment):
    def handler(req):
        if req.url.path.endswith("/search"):
            return httpx.Response(
                200, json={"items": [video()], "nextPageToken": "MORE"}
            )
        return enrichment

    result = gateway(handler).discover(
        DiscoveryRequest(platform="youtube", query="games")
    )
    assert result.status == "partial"
    assert result.next_cursor.token == "MORE"
    assert result.accounts[0].display_name == "Search Name"
    assert result.accounts[0].metadata_complete is False
    assert result.accounts[0].follower_count is None
    assert len(result.contents) == 1


def test_insufficient_budget_makes_no_network_request():
    def handler(req):
        pytest.fail("budget must be checked before IO")

    result = gateway(handler).discover(
        DiscoveryRequest(platform="youtube", query="games", max_requests=1)
    )
    assert result.status == "budget_exhausted"
    assert result.requests_used == 0


def test_missing_ids_do_not_invent_accounts_or_drop_valid_video():
    result = gateway(
        lambda req: httpx.Response(200, json={"items": [{}, video(channel=None)]})
    ).discover(DiscoveryRequest(platform="youtube", query="games"))
    assert result.status == "partial"
    assert result.accounts == []
    assert result.contents[0].account_id is None
    assert result.requests_used == 1


def test_wrong_platform_is_unavailable_without_io():
    def handler(req):
        pytest.fail("wrong provider must not make IO")

    result = gateway(handler).discover(DiscoveryRequest(platform="x", query="games"))
    assert result.status == "unavailable"
    assert result.platform == "x"
    assert result.requests_used == 0


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "https://user:secret@example.com/avatar", "not-a-url"],
)
def test_unsafe_avatar_url_is_not_exposed(url):
    def handler(req):
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [video()]})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": CHANNEL,
                        "snippet": {
                            "title": "Name",
                            "thumbnails": {"default": {"url": url}},
                        },
                    }
                ]
            },
        )

    result = gateway(handler).discover(
        DiscoveryRequest(platform="youtube", query="games")
    )
    assert result.accounts[0].avatar_url is None


def test_oversized_response_is_rejected_without_reflection():
    result = gateway(
        lambda req: httpx.Response(
            200, headers={"content-length": "4000001"}, content=b"fake-secret-canary"
        )
    ).discover(DiscoveryRequest(platform="youtube", query="games"))
    assert result.issues[0].code == "invalid_response"


def test_redirect_is_not_followed_with_secret():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(302, headers={"location": "https://other.example/"})

    result = gateway(handler).discover(
        DiscoveryRequest(platform="youtube", query="games")
    )
    assert result.status == "failed"
    assert len(calls) == 1
