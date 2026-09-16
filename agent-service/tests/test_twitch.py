import asyncio
import json

import httpx
import pytest

from fmg_agent.config import Settings
from fmg_agent.errors import ApiError


def settings(tmp_path, **kwargs):
    return Settings(
        database_url=f"sqlite:///{tmp_path}/test.sqlite",
        twitch_client_id="client",
        twitch_client_secret="secret",
        twitch_token_store=tmp_path / "tokens.json",
        **kwargs,
    )


def test_app_token_reused_and_public_fields_paging_preserved(tmp_path):
    from fmg_agent.providers.twitch import TwitchAuth
    from fmg_agent.providers.catalog import Catalog
    from fmg_agent.providers.transport import call_provider

    config = settings(tmp_path)
    requests = []

    def upstream(req):
        requests.append(req)
        if req.url.path == "/oauth2/token":
            assert b"grant_type=client_credentials" in req.content
            return httpx.Response(
                200, json={"access_token": "app-secret", "expires_in": 3600}
            )
        if req.url.path == "/oauth2/validate":
            return httpx.Response(200, json={"client_id": "client", "expires_in": 3600})
        assert req.headers["Client-Id"] == "client"
        assert req.headers["Authorization"] == "Bearer app-secret"
        assert req.url.params.get_list("id") == ["1", "2"]
        return httpx.Response(
            200,
            json={
                "data": [{"id": "1", "future": True}],
                "pagination": {"cursor": "next"},
            },
            headers={
                "Ratelimit-Limit": "800",
                "Ratelimit-Remaining": "797",
                "Ratelimit-Reset": "9999999999",
            },
        )

    transport = httpx.MockTransport(upstream)

    async def run():
        auth = TwitchAuth(config)
        op, path, params = Catalog(config.catalog_dir).prepare(
            "twitch", "getUsers", {"id": ["1", "2"]}
        )
        for _ in range(2):
            result = await call_provider(
                config, op, path, params, "twitch", "test", transport, twitch_auth=auth
            )
            assert result["data"]["data"][0]["future"] is True
            assert result["meta"]["rate_limit"]["remaining"] == 797
        assert sum(r.url.path == "/oauth2/token" for r in requests) == 1
        assert sum(r.url.path == "/oauth2/validate" for r in requests) == 1

    asyncio.run(run())


def test_user_expiry_refresh_and_rotated_token_survive_restart(tmp_path):
    from fmg_agent.providers.twitch import TwitchAuth

    config = settings(
        tmp_path, twitch_user_token="expired", twitch_refresh_token="old-refresh"
    )
    requests = []

    def upstream(req):
        requests.append(req)
        if req.url.path.endswith("validate"):
            if req.headers["Authorization"] == "OAuth expired":
                return httpx.Response(401, json={"message": "expired"})
            return httpx.Response(
                200, json={"client_id": "client", "user_id": "123", "expires_in": 3600}
            )
        assert b"refresh_token=old-refresh" in req.content
        return httpx.Response(
            200,
            json={
                "access_token": "new-user",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        )

    async def run():
        transport = httpx.MockTransport(upstream)
        assert await TwitchAuth(config).token("twitch-user", transport) == "new-user"
        assert await TwitchAuth(config).token("twitch-user", transport) == "new-user"

    asyncio.run(run())
    assert sum(r.url.path.endswith("token") for r in requests) == 1
    saved = json.loads(config.twitch_token_store.read_text())
    assert saved["refresh_token"] == "new-refresh"
    assert config.twitch_token_store.stat().st_mode & 0o777 == 0o600


def test_wrong_client_validation_fails_without_exposing_tokens(tmp_path):
    from fmg_agent.providers.twitch import TwitchAuth

    def upstream(req):
        if req.url.path.endswith("token"):
            return httpx.Response(
                200, json={"access_token": "private-value", "expires_in": 3600}
            )
        return httpx.Response(200, json={"client_id": "wrong", "expires_in": 3600})

    with pytest.raises(ApiError) as error:
        asyncio.run(
            TwitchAuth(settings(tmp_path)).token(
                "twitch-app", httpx.MockTransport(upstream)
            )
        )
    assert error.value.code == "provider_authorization_required"
    assert "private-value" not in str(error.value)


def test_catalog_followers_is_total_only_and_limits_are_validated(tmp_path):
    from fmg_agent.providers.catalog import Catalog

    catalog = Catalog(settings(tmp_path).catalog_dir)
    op, _, _ = catalog.prepare(
        "twitch", "getChannelFollowers", {"broadcaster_id": "123", "first": 1}
    )
    assert op["auth"] == "twitch-user"
    assert "total" in op["authorization_note"]
    assert (
        "broadcaster_id"
        in catalog.resolve("twitch", "getChannelChatBadges")["parameters"]
    )
    assert "started_at" in catalog.resolve("twitch", "getClips")["parameters"]
    assert "future" not in catalog.resolve("twitch", "getUsers")["parameters"]
    assert catalog.resolve("twitch", "getStreams")["pagination"]["response_path"] == [
        "pagination",
        "cursor",
    ]
    catalog.prepare("twitch", "getVideos", {"game_id": "27471", "first": 5})
    catalog.prepare("twitch", "getClips", {"game_id": "27471"})
    with pytest.raises(ApiError):
        catalog.prepare("twitch", "getVideos", {"game_id": "1", "user_id": "2"})
    for params in (
        {"first": 101},
        {"access_token": "bad"},
        {"url": "https://evil.test"},
    ):
        with pytest.raises(ApiError):
            catalog.prepare("twitch", "getStreams", params)


def test_rate_reset_header_and_twitch_cost():
    from fmg_agent.providers.transport import retry_after
    from fmg_agent.pricing import estimate

    assert retry_after(httpx.Headers({"Ratelimit-Reset": "1"})) == 0
    cost = estimate("twitch", "getUsers", "succeeded", data={"data": []})
    assert cost["estimated_cost"] == "0"
    assert cost["actual_cost"] is None


def test_catalog_parser_handles_singular_and_intervening_paragraph():
    from fmg_agent.providers.build_twitch_catalog import table

    source = "<h3>Request Query Parameter</h3><p>Selectors are exclusive.</p><table><tr><td>id</td><td>String</td><td>Yes</td><td>Account ID</td></tr></table><h3>Response Body</h3><table><tr><td>data</td></tr></table>"
    assert table(source, "Request Query Parameters?") == [
        ["id", "String", "Yes", "Account ID"]
    ]


def test_oauth_logging_redacts_authorization_and_query_secrets():
    import logging
    from fmg_agent.providers.logging import CredentialFilter

    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        "",
        0,
        "OAuth private-auth https://id.twitch.tv/?client_secret=private-client&refresh_token=private-refresh",
        (),
        None,
    )
    CredentialFilter().filter(record)
    assert "private-" not in record.getMessage()


def test_user_missing_is_not_silently_replaced_with_app_token(tmp_path):
    from fmg_agent.providers.twitch import TwitchAuth

    def upstream(req):
        pytest.fail(
            "No OAuth or data calls should be attempted without user authorization"
        )

    with pytest.raises(ApiError) as error:
        asyncio.run(
            TwitchAuth(settings(tmp_path)).token(
                "twitch-user", httpx.MockTransport(upstream)
            )
        )
    assert error.value.code == "provider_authorization_required"


def test_parallel_requests_share_app_token_and_hourly_validation(tmp_path):
    from fmg_agent.providers.twitch import TwitchAuth

    requests = []

    def upstream(req):
        requests.append(req)
        if req.url.path.endswith("token"):
            return httpx.Response(200, json={"access_token": "app", "expires_in": 7200})
        return httpx.Response(200, json={"client_id": "client", "expires_in": 7200})

    async def run():
        auth = TwitchAuth(settings(tmp_path))
        transport = httpx.MockTransport(upstream)
        assert (
            await asyncio.gather(
                *(auth.token("twitch-app", transport) for _ in range(10))
            )
            == ["app"] * 10
        )
        auth.checked["twitch-app"] -= 3601
        assert await auth.token("twitch-app", transport) == "app"

    asyncio.run(run())
    assert sum(r.url.path.endswith("token") for r in requests) == 1
    assert sum(r.url.path.endswith("validate") for r in requests) == 2


def test_helix_429_is_not_retried_and_oauth_errors_do_not_leak(tmp_path):
    from fmg_agent.providers.twitch import TwitchAuth
    from fmg_agent.providers.catalog import Catalog
    from fmg_agent.providers.transport import call_provider

    config = settings(tmp_path)
    requests = []

    def upstream(req):
        requests.append(req)
        if req.url.path.endswith("token"):
            return httpx.Response(
                200, json={"access_token": "hidden", "expires_in": 3600}
            )
        if req.url.path.endswith("validate"):
            return httpx.Response(200, json={"client_id": "client", "expires_in": 3600})
        return httpx.Response(
            429, json={"message": "hidden"}, headers={"Ratelimit-Reset": "1"}
        )

    async def run():
        op, path, params = Catalog(config.catalog_dir).prepare(
            "twitch", "getStreams", {"first": 5}
        )
        with pytest.raises(ApiError) as error:
            await call_provider(
                config,
                op,
                path,
                params,
                "twitch",
                "test",
                httpx.MockTransport(upstream),
                twitch_auth=TwitchAuth(config),
            )
        assert error.value.code == "rate_limited"
        assert error.value.retry_after_seconds == 0
        assert "hidden" not in str(error.value)

    asyncio.run(run())
    assert len(requests) == 3
