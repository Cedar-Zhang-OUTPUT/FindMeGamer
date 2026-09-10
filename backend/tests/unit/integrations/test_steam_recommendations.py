import httpx
import pytest
from app.integrations.steam import SteamGateway
from app.integrations.steam_recommendations import recommended_app_ids
from tests.unit.integrations.test_steam import _steam_payload


def capsule(app, host="store.steampowered.com"):
    return f'<a class="similar_grid_capsule" data-ds-appid="{app}" href="https://{host}/app/{app}/Title/"></a>'


def test_only_released_section_fixed_store_app_links_dedup_self_and_limit():
    html = capsule("88") + '<div id="released" class="similar_grid_ctn"><div>'
    html += capsule("10") + capsule("11") * 2 + capsule("12", "attacker.example")
    html += "".join(capsule(str(i)) for i in range(20, 40))
    html += '</div></div><div id="upcoming">' + capsule("99") + "</div>"
    assert recommended_app_ids(html, "10") == ["11", *map(str, range(20, 28))]


def test_missing_section_is_failure_not_success_empty():
    with pytest.raises(ValueError):
        recommended_app_ids("<html>Sign in</html>", "10")
    assert recommended_app_ids('<div id="released"></div>', "10") == []


def test_fetch_game_includes_real_named_recommendations_without_recursing():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "/recommended/" in request.url.path:
            return httpx.Response(
                200, text='<div id="released">' + capsule("20") + "</div>"
            )
        app = request.url.params["appids"]
        payload = _steam_payload(app)
        payload[app]["data"]["name"] = (
            "Actual Steam Name" if app == "20" else "Source Game"
        )
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = SteamGateway(http_client=client).fetch_game("10")
    assert len(calls) == 3
    assert source.steam_recommendations.status == "available"
    assert source.steam_recommendations.items[0].name == "Actual Steam Name"
    assert (
        source.steam_recommendations.items[0].url
        == "https://store.steampowered.com/app/20/"
    )


@pytest.mark.parametrize("failure", [503, 302])
def test_optional_recommendation_failure_does_not_fail_base_game(failure):
    def handler(request):
        if "/recommended/" in request.url.path:
            return httpx.Response(failure, headers={"Location": "http://127.0.0.1/"})
        return httpx.Response(200, json=_steam_payload("10"))

    source = SteamGateway(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ).fetch_game("10")
    assert source.name == "Elden Ring"
    assert source.steam_recommendations.status == "unavailable"


def test_one_name_lookup_failure_reports_partial_without_inventing_name():
    def handler(request):
        if "/recommended/" in request.url.path:
            return httpx.Response(
                200,
                text='<div id="released">' + capsule("20") + capsule("21") + "</div>",
            )
        app = request.url.params["appids"]
        return (
            httpx.Response(503)
            if app == "21"
            else httpx.Response(200, json=_steam_payload(app))
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = SteamGateway(http_client=client).fetch_game("10")
    assert source.steam_recommendations.status == "partial"
    assert [item.app_id for item in source.steam_recommendations.items] == ["20"]
