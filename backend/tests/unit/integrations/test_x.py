import httpx
import pytest

from app.analysis.targets import canonicalize_target
from app.db.models.enums import TargetType
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError


def test_x_gateway_fetches_official_account_and_posts_without_video_facts():
    from app.integrations.x import XGateway

    def respond(request):
        assert request.url.host == "api.x.com"
        assert request.headers["authorization"] == "Bearer fixture-token"
        assert "fixture-token" not in str(request.url)
        if request.url.path == "/2/users/by/username/example":
            return httpx.Response(
                200,
                json={
                    "data": {"id": "12345", "name": "Example", "username": "example"}
                },
            )
        if request.url.path == "/2/users/12345":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "12345",
                        "name": "Example",
                        "username": "example",
                        "description": "Indie games",
                        "public_metrics": {"followers_count": 123, "tweet_count": 10},
                    }
                },
            )
        assert request.url.path == "/2/users/12345/tweets"
        assert request.url.params["max_results"] == "50"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "777",
                        "author_id": "12345",
                        "text": "New indie game",
                        "public_metrics": {"like_count": 7},
                    }
                ],
                "meta": {"result_count": 1},
            },
        )

    gateway = XGateway(
        api_key="fixture-token",
        http_client=httpx.Client(
            transport=httpx.MockTransport(respond), auth=("wrong", "auth")
        ),
    )
    assert (
        gateway.resolve_channel(
            canonicalize_target(TargetType.CREATOR, "https://x.com/example")
        )
        == "12345"
    )
    source = gateway.fetch_creator("12345")
    assert source.platform_account_id == "12345"
    assert source.follower_count == 123
    assert source.posts[0].canonical_url == "https://x.com/i/status/777"
    assert "videos" not in source.model_dump()


@pytest.mark.parametrize(
    ("status", "body", "code", "error"),
    [
        (402, {}, "x_payment_required", PermanentIntegrationError),
        (
            403,
            {"reason": "usage-capped"},
            "x_spend_cap_reached",
            PermanentIntegrationError,
        ),
        (403, {}, "x_request_rejected", PermanentIntegrationError),
        (429, {}, "x_rate_limited", TransientIntegrationError),
        (302, {}, "x_request_rejected", PermanentIntegrationError),
    ],
)
def test_x_provider_failures_are_distinct_safe_errors(status, body, code, error):
    from app.integrations.x import XGateway

    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    )
    with pytest.raises(error) as caught:
        XGateway(api_key="fixture-token", http_client=client).fetch_creator("12345")
    assert str(caught.value) == code


def test_x_missing_configuration_is_explicit():
    from app.integrations.x import XGateway

    with pytest.raises(PermanentIntegrationError, match="x_configuration_invalid"):
        XGateway(api_key="")


def test_x_connection_probe_keeps_bearer_on_official_host():
    from app.integrations.connection_probe import ProductionConnectionProbe

    def handler(request):
        assert str(request.url) == "https://api.x.com/2/users/by/username/XDevelopers"
        assert request.headers["authorization"] == "Bearer fixture-token"
        return httpx.Response(200, json={"data": {"id": "12345"}})

    probe = ProductionConnectionProbe(
        deepseek_base_url="https://api.deepseek.com",
        youtube_base_url="https://www.googleapis.com/youtube/v3",
        google_ai_base_url="https://generativelanguage.googleapis.com/v1beta/models",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert probe.test_connection("x", "fixture-token")
