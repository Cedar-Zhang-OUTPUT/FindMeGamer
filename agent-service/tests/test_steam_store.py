import httpx
import pytest

from test_provider_calls import api, call


def test_search_keeps_multiple_candidates_and_raw_fields(api):
    _, _, requests, responses = api
    responses.append(
        httpx.Response(
            200,
            json={
                "total": 2,
                "items": [
                    {"type": "app", "id": 10, "name": "Game", "future": True},
                    {"type": "app", "id": 11, "name": "Game Two"},
                ],
            },
        )
    )
    result = call(api, "steam", "store.search", {"term": "Game"})
    assert result.status_code == 200
    body = result.json()
    assert [x["app_id"] for x in body["data"]["candidates"]] == ["10", "11"]
    assert body["data"]["upstream"]["items"][0]["future"] is True
    assert (
        body["data"]["candidates"][0]["url"] == "https://store.steampowered.com/app/10/"
    )
    assert len(requests) == 1
    assert (
        str(requests[0].url)
        == "https://store.steampowered.com/api/storesearch/?l=english&cc=US&term=Game"
    )
    assert body["meta"]["retrieved_at"]


PAGE = """<html><div class="similar_grid_ctn">
<a class="similar_grid_capsule" href="https://store.steampowered.com/app/570/Dota_2/" data-ds-appid="570"></a>
<a class="similar_grid_capsule" href="https://store.steampowered.com/app/10/Some_Game/?snr=1" data-ds-appid="10"><img src="image"></a>
<a class="similar_grid_capsule" href="https://store.steampowered.com/app/10/Some_Game/" data-ds-appid="10"></a>
<a class="similar_grid_capsule" href="https://evil.example/app/12/" data-ds-appid="12"></a>
<a href="https://store.steampowered.com/app/13/Advert/" data-ds-appid="13"></a>
</div></html>"""


def test_recommendations_deduplicate_exclude_self_and_unrelated_links(api):
    _, _, requests, responses = api
    responses.append(httpx.Response(200, text=PAGE))
    result = call(
        api,
        "steam",
        "store.recommendations",
        {"appid": "https://store.steampowered.com/app/570/Dota_2/?snr=1"},
    )
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["items"] == [
        {
            "app_id": "10",
            "name": None,
            "name_hint": "Some Game",
            "url": "https://store.steampowered.com/app/10/",
        }
    ]
    assert len(requests) == 1
    assert requests[0].url.path == "/recommended/morelike/app/570/"
    assert result.json()["meta"]["next_cursor"] is None


@pytest.mark.parametrize(
    "appid",
    [
        "https://evil.example/app/570",
        "https://store.steampowered.com.evil/app/570/",
        "../570",
        "https://store.steampowered.com:444/app/570/",
    ],
)
def test_bad_game_identity_rejected_before_fetch(api, appid):
    result = call(api, "steam", "store.recommendations", {"appid": appid})
    assert result.status_code == 422
    assert api[2] == []


def test_empty_recommendations_differ_from_changed_page_and_failure(api):
    api[3].extend(
        [
            httpx.Response(200, text='<div class="similar_grid_ctn"></div>'),
            httpx.Response(200, text="<html>Please sign in</html>"),
            httpx.Response(503, text="secret detail"),
        ]
    )
    first = call(api, "steam", "store.recommendations", {"appid": 570})
    assert first.status_code == 200 and first.json()["data"]["items"] == []
    second = call(api, "steam", "store.recommendations", {"appid": 570})
    assert (
        second.status_code == 502
        and second.json()["error"]["code"] == "invalid_provider_response"
    )
    third = call(api, "steam", "store.recommendations", {"appid": 570})
    assert third.status_code == 502 and "secret detail" not in third.text


def test_search_invalid_shape_and_redirect_are_not_empty_success(api):
    api[3].extend(
        [
            httpx.Response(200, json={"error": "bad"}),
            httpx.Response(302, headers={"location": "http://127.0.0.1/private"}),
        ]
    )
    assert call(api, "steam", "store.search", {"term": "Game"}).status_code == 502
    assert call(api, "steam", "store.search", {"term": "Game"}).status_code == 502
    assert len(api[2]) == 2


def test_steam_response_size_is_bounded(api):
    api[3].append(httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)))
    result = call(api, "steam", "store.recommendations", {"appid": 570})
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "provider_response_too_large"
