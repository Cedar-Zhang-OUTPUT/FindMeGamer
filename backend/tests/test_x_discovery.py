import importlib

import httpx
import pytest

from app.schemas.discovery import DiscoveryRequest


SECRET = "fixture-bearer-must-not-escape"


def gateway(client):
    module = importlib.import_module("app.integrations.x_discovery")
    return module.XDiscoveryGateway(bearer_token=SECRET, http_client=client)


def test_maps_public_facts_and_deduplicates_accounts_and_posts_across_page():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "100",
                        "author_id": "20",
                        "text": "Game review",
                        "lang": "en",
                        "created_at": "2026-09-08T01:02:03Z",
                        "public_metrics": {"like_count": 4},
                    },
                    {"id": "101", "author_id": "20", "text": "More games"},
                    {"id": "100", "author_id": "20", "text": "Game review"},
                ],
                "includes": {
                    "users": [
                        {
                            "id": "20",
                            "name": "Gamer",
                            "username": "gamer",
                            "description": "Reviews",
                            "location": "The Moon",
                            "public_metrics": {"followers_count": 123},
                        }
                    ]
                },
                "meta": {"result_count": 3, "next_token": "next-page"},
            },
        )

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        gateway(client) as api,
    ):
        request = DiscoveryRequest(
            platform="x", query="indie game -is:retweet", page_size=10
        )
        page = api.discover(request)
        assert page.status == "more"
        assert page.requests_used == 1
        assert page.provider_items_received == 3
        assert page.coverage == "recent_7_days"
        assert page.estimated_cost is None
        assert [a.account_id for a in page.accounts] == ["20"]
        account = page.accounts[0]
        assert account.follower_count == 123
        assert account.profile_url == "https://x.com/i/user/20"
        assert account.handle == "gamer"
        assert account.location_text == "The Moon"
        assert account.country is None
        assert [c.content_id for c in page.contents] == ["100", "101"]
        content = page.contents[0]
        assert content.source_url == "https://x.com/i/web/status/100"
        assert content.evidence_status == "unverified"
        assert content.public_metrics == {"like_count": 4}
        assert content.published_at.isoformat() == "2026-09-08T01:02:03+00:00"
        assert page.next_cursor.token == "next-page"
        continuation = DiscoveryRequest(
            **{**request.model_dump(), "cursor": page.next_cursor}
        )
        api.discover(continuation)
    assert len(requests) == 2
    assert requests[0].url.path == "/2/tweets/search/recent"
    assert requests[0].url.params["query"] == "indie game -is:retweet"
    assert requests[0].url.params["max_results"] == "10"
    assert requests[0].url.params["expansions"] == "author_id"
    assert "public_metrics" in requests[0].url.params["tweet.fields"]
    assert requests[1].url.params["next_token"] == "next-page"
    assert requests[0].headers["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in str(requests[0].url)


def test_missing_authors_retains_stub_unknown_metrics_and_partial_data():
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "data": [{"id": "100", "author_id": "20"}, {"id": "101"}],
                        "errors": [{"detail": SECRET}],
                        "meta": {"result_count": 2},
                    },
                )
            )
        ) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.status == "partial"
    assert len(page.contents) == 2
    assert page.contents[1].account_id is None
    assert page.accounts[0].metadata_complete is False
    assert page.accounts[0].follower_count is None
    assert page.accounts[0].display_name is None
    assert page.contents[0].public_metrics == {}
    assert page.issues[0].code == "partial_data"
    assert SECRET not in page.model_dump_json()


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "unauthorized", False),
        (403, "forbidden", False),
        (429, "rate_limited", True),
        (503, "unavailable", True),
        (400, "invalid_request", False),
        (422, "invalid_request", False),
        (402, "unavailable", False),
    ],
)
def test_http_errors_are_safe_and_do_not_retry(status, code, retryable):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "23"}, text=SECRET)

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.status == "failed"
    assert page.requests_used == len(calls) == 1
    assert page.issues[0].code == code
    assert page.issues[0].retryable is retryable
    if status == 429:
        assert page.issues[0].retry_after_seconds == 23
    assert SECRET not in page.model_dump_json()


def test_timeout_is_safe_and_does_not_retry():
    def timeout(request):
        raise httpx.ReadTimeout(SECRET, request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(timeout)) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.requests_used == 1
    assert page.issues[0].code == "timeout"
    assert page.issues[0].retryable
    assert SECRET not in page.model_dump_json()


@pytest.mark.parametrize(
    "payload", [{}, [], {"data": "bad"}, {"errors": [{"detail": SECRET}]}]
)
def test_invalid_response_is_not_a_successful_empty_search(payload):
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.status == "failed"
    assert page.issues[0].code == "invalid_response"
    assert SECRET not in page.model_dump_json()


def test_explicit_zero_results_is_complete():
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"meta": {"result_count": 0}})
            )
        ) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.status == "complete"
    assert page.accounts == page.contents == []


def test_exhausted_budget_makes_no_request():
    def forbidden(request):
        pytest.fail("Budget exhausted must not make a paid call")

    with (
        httpx.Client(transport=httpx.MockTransport(forbidden)) as client,
        gateway(client) as api,
    ):
        page = api.discover(
            DiscoveryRequest(platform="x", query="games", max_requests=0)
        )
    assert page.status == "budget_exhausted"
    assert page.requests_used == 0


def test_redirect_does_not_forward_bearer():
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://other.example/stolen"})

    with (
        httpx.Client(
            transport=httpx.MockTransport(redirect), follow_redirects=True
        ) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert len(calls) == 1
    assert page.status == "failed"


def test_oversized_response_is_bounded_and_safe():
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, headers={"Content-Length": "4000001"}, text=SECRET
                )
            )
        ) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.issues[0].code == "invalid_response"
    assert SECRET not in page.model_dump_json()


def test_unknown_and_invalid_optional_facts_are_not_fabricated():
    payload = {
        "data": [
            {
                "id": "100",
                "author_id": "20",
                "created_at": "bad-date",
                "public_metrics": {
                    "like_count": -1,
                    "reply_count": True,
                    "quote_count": 0,
                },
            }
        ],
        "includes": {
            "users": [
                {
                    "id": "20",
                    "public_metrics": {"followers_count": "50"},
                    "profile_image_url": "javascript:alert(1)",
                }
            ]
        },
        "meta": {"result_count": 1},
    }
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.accounts[0].follower_count is None
    assert page.accounts[0].avatar_url is None
    assert page.contents[0].published_at is None
    assert page.contents[0].public_metrics == {"quote_count": 0}


def test_wrong_platform_makes_no_provider_call():
    def forbidden(request):
        pytest.fail("Wrong platform must not make a paid call")

    with (
        httpx.Client(transport=httpx.MockTransport(forbidden)) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="youtube", query="games"))
    assert page.status == "unavailable"
    assert page.platform == "youtube"
    assert page.requests_used == 0
    assert page.issues[0].code == "not_supported"


def test_network_failure_is_safe_and_retryable_without_automatic_retry():
    def unavailable(request):
        raise httpx.ConnectError(SECRET, request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(unavailable)) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.issues[0].code == "unavailable"
    assert page.issues[0].retryable
    assert page.requests_used == 1
    assert SECRET not in page.model_dump_json()


def test_malformed_json_is_safe():
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=SECRET))
        ) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.status == "failed"
    assert page.issues[0].code == "invalid_response"
    assert SECRET not in page.model_dump_json()


def test_all_malformed_items_are_partial_not_exhausted_search():
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "data": [{"id": "bad-id"}, None],
                        "meta": {"result_count": 2, "next_token": "next-page"},
                    },
                )
            )
        ) as client,
        gateway(client) as api,
    ):
        page = api.discover(DiscoveryRequest(platform="x", query="games"))
    assert page.status == "partial"
    assert page.provider_items_received == 2
    assert page.contents == []
    assert page.next_cursor.token == "next-page"
