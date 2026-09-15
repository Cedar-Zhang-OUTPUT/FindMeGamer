import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path):
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token
    from fmg_agent.config import Settings
    from fmg_agent.db import Base

    app = create_app(
        Settings(
            database_url=f'sqlite:///{tmp_path / "provider.sqlite"}',
            youtube_api_key="private-youtube-key",
            x_bearer_token="private-x-token",
        )
    )
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as session:
        token = issue_token(session, label="reader", scopes=["read"])
    requests = []
    responses = []

    def upstream(request):
        requests.append(request)
        return responses.pop(0)

    with TestClient(app) as client:
        app.state.provider_transport = httpx.MockTransport(upstream)
        yield client, {"Authorization": f"Bearer {token.token}"}, requests, responses


def call(api, provider, operation, params):
    client, headers, _, _ = api
    return client.post(
        f"/v1/providers/{provider}/call",
        headers=headers,
        json={"operation": operation, "params": params},
    )


def test_preserves_provider_fields_and_single_page(api):
    _, _, requests, responses = api
    responses.append(
        httpx.Response(
            200, json={"items": [], "futureField": {"x": 1}, "nextPageToken": "p2"}
        )
    )
    r = call(api, "youtube", "search.list", {"part": "snippet", "q": "indie"})
    assert r.status_code == 200
    assert r.json()["data"] == {
        "items": [],
        "futureField": {"x": 1},
        "nextPageToken": "p2",
    }
    assert len(requests) == 1
    assert requests[0].url.params["key"] == "private-youtube-key"
    assert r.json()["meta"]["next_cursor"] == "p2"


def test_x_arrays_and_path_preserved(api):
    _, _, requests, responses = api
    responses.append(
        httpx.Response(
            200,
            json={"data": {"id": "123"}, "errors": [{"detail": "partial"}]},
            headers={"x-rate-limit-remaining": "12"},
        )
    )
    r = call(
        api,
        "x",
        "getUsersById",
        {"id": "123", "user.fields": ["description", "public_metrics"]},
    )
    assert r.status_code == 200
    assert requests[0].url.path == "/2/users/123"
    assert requests[0].url.params["user.fields"] == "description,public_metrics"
    assert requests[0].headers["Authorization"] == "Bearer private-x-token"
    assert r.json()["data"]["errors"] == [{"detail": "partial"}]
    assert r.json()["meta"]["rate_limit"]["remaining"] == 12


@pytest.mark.parametrize(
    "params",
    [
        {"part": "snippet", "key": "injected"},
        {"part": "snippet", "url": "http://127.0.0.1"},
        {"part": "snippet", "access_token": "injected"},
        {"part": "snippet", "callback": "evil"},
        {"part": "snippet", "alt": "media"},
    ],
)
def test_unsafe_overrides_do_not_reach_upstream(api, params):
    r = call(api, "youtube", "search.list", params)
    assert r.status_code == 422
    assert api[2] == []


def test_missing_required_param_does_not_consume_quota(api):
    r = call(api, "youtube", "search.list", {"q": "indie"})
    assert r.status_code == 422
    assert api[2] == []


@pytest.mark.parametrize(
    "path", ["../me", "..", "%2e%2e%2fme", "123?x=1", "123/liked_tweets"]
)
def test_path_cannot_select_another_endpoint(api, path):
    r = call(api, "x", "getUsersById", {"id": path})
    assert r.status_code == 422
    assert api[2] == []


@pytest.mark.parametrize(
    "status,body,code",
    [
        (429, {"detail": "private-x-token"}, "rate_limited"),
        (402, {"detail": "balance exhausted"}, "quota_exhausted"),
        (401, {"detail": "private-x-token"}, "provider_authorization_required"),
        (500, {"error": "private-x-token"}, "upstream_unavailable"),
    ],
)
def test_upstream_failures_are_sanitized_and_not_retried(api, status, body, code):
    api[3].append(httpx.Response(status, json=body, headers={"retry-after": "30"}))
    r = call(api, "x", "getUsersById", {"id": "123"})
    assert r.json()["error"]["code"] == code
    assert "private-x-token" not in r.text
    assert len(api[2]) == 1
    if status == 429:
        assert r.json()["error"]["retry_after_seconds"] == 30


def test_youtube_daily_quota_is_not_classified_as_bad_key(api):
    api[3].append(
        httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
    )
    r = call(api, "youtube", "search.list", {"part": "snippet"})
    assert r.json()["error"]["code"] == "quota_exhausted"
    assert r.json()["error"]["retryable"] is False


def test_redirect_is_not_followed(api):
    api[3].append(httpx.Response(302, headers={"location": "http://127.0.0.1/private"}))
    r = call(api, "x", "getUsersById", {"id": "123"})
    assert r.status_code == 502
    assert len(api[2]) == 1


def test_authorization_only_operation_is_explicit(api):
    r = call(api, "x", "getUsersMe", {})
    assert r.json()["error"]["code"] == "provider_authorization_required"
    assert api[2] == []


def test_directory_requires_auth_and_describes_official_fields(api):
    client, headers, _, _ = api
    assert client.get("/v1/providers/youtube/operations").status_code == 401
    r = client.get("/v1/providers/youtube/operations/search.list", headers=headers)
    assert r.status_code == 200
    assert "relevanceLanguage" in r.json()["data"]["parameters"]
    assert "private-youtube-key" not in r.text


def test_write_operation_not_registered(api):
    r = call(api, "youtube", "videos.delete", {"id": "123"})
    assert r.status_code == 404
    assert api[2] == []


def test_store_appdetails_returns_full_game_payload(api):
    payload = {
        "570": {"success": True, "data": {"name": "Dota 2", "movies": [], "future": 1}}
    }
    api[3].append(httpx.Response(200, json=payload))
    r = call(
        api, "steam", "store.appdetails", {"appids": "570", "l": "english", "cc": "US"}
    )
    assert r.status_code == 200
    assert r.json()["data"] == payload
    assert api[2][0].url.host == "store.steampowered.com"
    assert api[2][0].url.path == "/api/appdetails"


def test_steam_optional_key_does_not_require_company_configuration(api):
    api[3].append(httpx.Response(200, json={"apilist": {"interfaces": []}}))
    r = call(api, "steam", "ISteamWebAPIUtil.GetSupportedAPIList.v1", {})
    assert r.status_code == 200
    assert "key" not in api[2][0].url.params


def test_steam_indexed_batch_params_remain_indexed(api):
    api[3].append(httpx.Response(200, json={"response": {"globalstats": {}}}))
    r = call(
        api,
        "steam",
        "ISteamUserStats.GetGlobalStatsForGame.v1",
        {"appid": 440, "count": 2, "name[0]": "a", "name[1]": "b"},
    )
    assert r.status_code == 200
    assert api[2][0].url.params["name[0]"] == "a"
    assert api[2][0].url.params["name[1]"] == "b"


def test_http_diagnostic_logging_does_not_expose_company_key(api, caplog):
    import logging

    api[3].append(httpx.Response(200, json={"items": []}))
    with caplog.at_level(logging.INFO, logger="httpx"):
        r = call(api, "youtube", "search.list", {"part": "snippet"})
    assert r.status_code == 200
    assert "private-youtube-key" not in caplog.text


def test_steam_service_structured_params_are_encoded_in_input_json(api):
    api[3].append(httpx.Response(200, json={"response": {"items": []}}))
    r = call(
        api,
        "steam",
        "IWishlistService.GetWishlistSortedFiltered.v1",
        {
            "steamid": "123",
            "filters": {"only_free": True},
            "context": {},
            "data_request": {},
            "share_token": "",
        },
    )
    assert r.status_code == 200
    import json

    assert json.loads(api[2][0].url.params["input_json"])["filters"] == {
        "only_free": True
    }
