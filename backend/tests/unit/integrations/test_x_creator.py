import importlib.util
from importlib import import_module

import httpx
import pytest

from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError


def gateway(client):
    module = "app.integrations.x_creator"
    assert importlib.util.find_spec(
        module
    ), "The X account-analysis source gateway is missing"
    return import_module(module).XCreatorGateway(
        bearer_token="fixture-token", http_client=client
    )


def user_payload():
    return {
        "data": {
            "id": "123456",
            "username": "fixturecreator",
            "name": "Creator",
            "description": "Game reviews. Contact press@example.com",
            "protected": False,
            "public_metrics": {"followers_count": 1200},
        }
    }


def posts_payload():
    return {
        "data": [
            {
                "id": "456789",
                "author_id": "123456",
                "text": "A game review",
                "lang": "en",
                "created_at": "2026-09-08T00:00:00Z",
                "public_metrics": {"like_count": 20},
            }
        ],
        "meta": {"result_count": 1, "next_token": "more-content"},
    }


def test_selected_account_fetch_uses_two_official_reads_and_reports_bounded_coverage():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer fixture-token"
        assert request.url.host == "api.x.com"
        if request.url.path == "/2/users/123456":
            return httpx.Response(200, json=user_payload())
        assert request.url.path == "/2/users/123456/tweets"
        assert request.url.params["max_results"] == "50"
        assert request.url.params["exclude"] == "retweets,replies"
        assert "lang" in request.url.params["tweet.fields"]
        return httpx.Response(200, json=posts_payload())

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        gateway(client) as source_gateway,
    ):
        source = source_gateway.fetch_creator("123456")
    assert len(calls) == 2
    assert source.account.account_id == "123456"
    assert source.account.follower_count == 1200
    assert source.contents[0].language == "en"
    assert source.contents[0].text == "A game review"
    assert source.coverage == "recent_account_posts"
    assert source.more_available and source.post_limit == 50
    assert source.contents[0].evidence_status == "unverified"


def test_empty_timeline_is_explicit_unknown_not_a_failed_or_invented_post():
    def handler(request):
        return httpx.Response(
            200,
            json=(
                {"meta": {"result_count": 0}}
                if request.url.path.endswith("tweets")
                else user_payload()
            ),
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        gateway(client) as source_gateway,
    ):
        source = source_gateway.fetch_creator("123456")
    assert source.contents == [] and not source.more_available


@pytest.mark.parametrize(
    "status,exception,code",
    [
        (401, PermanentIntegrationError, "x_request_rejected"),
        (403, PermanentIntegrationError, "x_request_rejected"),
        (404, PermanentIntegrationError, "x_account_not_found"),
        (429, TransientIntegrationError, "x_unavailable"),
        (503, TransientIntegrationError, "x_unavailable"),
    ],
)
def test_source_errors_are_safe_and_do_not_retry_paid_reads(status, exception, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="provider secret or raw details")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        gateway(client) as source_gateway,
    ):
        with pytest.raises(exception) as caught:
            source_gateway.fetch_creator("123456")
    assert caught.value.code == code and len(calls) == 1
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "bad", ["account_mismatch", "post_author_mismatch", "partial", "protected"]
)
def test_invalid_identity_or_inaccessible_source_is_not_published_as_complete(bad):
    def handler(request):
        if request.url.path.endswith("tweets"):
            payload = posts_payload()
            if bad == "post_author_mismatch":
                payload["data"][0]["author_id"] = "999999"
            if bad == "partial":
                payload["errors"] = [{"detail": "Partial source"}]
        else:
            payload = user_payload()
            if bad == "account_mismatch":
                payload["data"]["id"] = "999999"
            if bad == "protected":
                payload["data"]["protected"] = True
        return httpx.Response(200, json=payload)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        gateway(client) as source_gateway,
    ):
        with pytest.raises(PermanentIntegrationError):
            source_gateway.fetch_creator("123456")


def test_account_identifier_cannot_be_a_url_or_change_the_request_path():
    def handler(request):
        pytest.fail("Invalid identity must fail before network")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        gateway(client) as source_gateway,
    ):
        with pytest.raises(PermanentIntegrationError):
            source_gateway.fetch_creator("https://127.0.0.1/secret")
