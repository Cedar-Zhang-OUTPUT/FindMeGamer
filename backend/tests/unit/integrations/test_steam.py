import logging

import httpx
import pytest

from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.steam import SteamGateway


def _steam_payload(app_id: str = "1245620") -> dict[str, object]:
    return {
        app_id: {
            "success": True,
            "data": {
                "steam_appid": int(app_id),
                "type": "game",
                "name": "Elden Ring",
                "required_age": 17,
                "is_free": False,
                "developers": ["FromSoftware"],
                "publishers": ["Bandai Namco"],
                "release_date": {"coming_soon": False, "date": "24 Feb, 2022"},
                "short_description": "An action RPG.",
                "detailed_description": "A detailed description.",
                "about_the_game": "Explore the Lands Between.",
                "genres": [{"id": "1", "description": "Action"}],
                "categories": [{"id": 2, "description": "Single-player"}],
                "platforms": {"windows": True, "mac": False, "linux": True},
                "supported_languages": "English, Japanese",
                "recommendations": {"total": 900_001},
                "review_score_desc": "Very Positive",
                "header_image": "https://cdn.example/header.jpg",
                "capsule_image": "https://cdn.example/cover.jpg",
                "screenshots": [
                    {
                        "id": 1,
                        "path_full": "https://cdn.example/full.jpg",
                        "path_thumbnail": "https://cdn.example/thumb.jpg",
                    }
                ],
                "movies": [
                    {
                        "id": 7,
                        "name": "Trailer",
                        "thumbnail": "https://cdn.example/movie.jpg",
                        "mp4": {"480": "https://cdn.example/movie-480.mp4"},
                        "webm": {"max": "https://cdn.example/movie.webm"},
                    }
                ],
            },
        }
    }


def test_steam_fetches_english_us_store_data_and_maps_public_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_steam_payload())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = SteamGateway(http_client=client).fetch_game("1245620")

    assert len(requests) == 2  # Base source plus best-effort recommendations page.
    assert requests[0].url.path == "/api/appdetails"
    assert dict(requests[0].url.params) == {
        "appids": "1245620",
        "l": "english",
        "cc": "US",
    }
    assert source.app_id == "1245620"
    assert source.name == "Elden Ring"
    assert source.developers == ("FromSoftware",)
    assert source.publishers == ("Bandai Namco",)
    assert source.genres == ("Action",)
    assert source.categories == ("Single-player",)
    assert source.platforms == ("linux", "windows")
    assert source.recommendation_count == 900_001
    assert source.review_summary == "Very Positive"
    assert source.header_image_url == "https://cdn.example/header.jpg"
    assert source.cover_image_url == "https://cdn.example/cover.jpg"
    assert source.screenshots[0].full_url == "https://cdn.example/full.jpg"
    assert source.movies[0].mp4_urls == ("https://cdn.example/movie-480.mp4",)
    assert source.raw["steam_appid"] == 1245620


@pytest.mark.parametrize(
    "app_id", ["", "0", "-1", "+1", "01", "1.0", "2147483648", "x" * 64]
)
def test_steam_rejects_noncanonical_app_id_before_network(app_id: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be called")

    gateway = SteamGateway(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(PermanentIntegrationError, match="steam_app_id_invalid"):
        gateway.fetch_game(app_id)


@pytest.mark.parametrize("payload", [{"1245620": {"success": False}}, {}])
def test_steam_classifies_missing_game_as_permanent(payload: dict[str, object]) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    with pytest.raises(PermanentIntegrationError, match="steam_game_not_found"):
        SteamGateway(http_client=client).fetch_game("1245620")


@pytest.mark.parametrize(
    "payload",
    [
        {"1245620": {"success": True, "data": []}},
        {"1245620": {"success": True, "data": {"steam_appid": 999, "name": "X"}}},
        {"1245620": {"success": True, "data": {"steam_appid": 1245620}}},
        ["not", "an", "object"],
    ],
)
def test_steam_rejects_malformed_or_mismatched_success_payload(payload: object) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    with pytest.raises(PermanentIntegrationError, match="steam_response_invalid"):
        SteamGateway(http_client=client).fetch_game("1245620")


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_steam_classifies_ordinary_http_errors_as_permanent(status: int) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="private response body")
        )
    )

    with pytest.raises(PermanentIntegrationError, match="steam_request_rejected"):
        SteamGateway(http_client=client).fetch_game("1245620")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_steam_classifies_rate_limit_and_server_errors_as_transient(
    status: int,
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="private response body")
        )
    )

    with pytest.raises(TransientIntegrationError, match="steam_unavailable"):
        SteamGateway(http_client=client).fetch_game("1245620")


def test_steam_classifies_timeout_as_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("contains signed-url?secret=canary", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(TransientIntegrationError, match="steam_unavailable"):
        SteamGateway(http_client=client).fetch_game("1245620")


def test_steam_rejects_oversized_response_without_leaking_body(caplog) -> None:
    secret = "steam-response-canary-secret"
    body = (secret + "x" * 2_100_000).encode()
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(
        PermanentIntegrationError, match="steam_response_too_large"
    ) as caught:
        SteamGateway(http_client=client).fetch_game("1245620")

    rendered = f"{caught.value!s}{caught.value!r}{caplog.text}"
    assert secret not in rendered


def test_steam_stops_streaming_at_cap_and_closes_lying_length_response(
    monkeypatch, gateway_byte_stream_factory, caplog
) -> None:
    monkeypatch.setattr("app.integrations.steam.MAX_STEAM_RESPONSE_BYTES", 5)
    secret = "steam-unread-stream-canary"
    stream = gateway_byte_stream_factory(
        [b"1234", b"56", secret.encode()],
    )
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

    with caplog.at_level(logging.DEBUG), pytest.raises(
        PermanentIntegrationError, match="steam_response_too_large"
    ) as caught:
        SteamGateway(http_client=client).fetch_game("1245620")

    assert requests == 1
    assert stream.yielded == 2
    assert stream.closed is True
    assert secret not in f"{caught.value!s}{caught.value!r}{caplog.text}"


def test_steam_rejects_unsafe_base_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        SteamGateway(base_url="http://store.steampowered.com/api")


def test_steam_does_not_close_caller_owned_client() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_steam_payload())
        )
    )
    gateway = SteamGateway(http_client=client)

    gateway.fetch_game("1245620")
    gateway.close()

    assert not client.is_closed


def test_steam_disables_redirects_and_applies_explicit_timeouts_to_injected_client() -> (
    None
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "https://attacker.example/provider-returned"},
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        timeout=99.0,
    )

    with pytest.raises(PermanentIntegrationError, match="steam_response_invalid"):
        SteamGateway(http_client=client).fetch_game("1245620")

    assert len(requests) == 1
    assert requests[0].extensions["timeout"] == {
        "connect": 5.0,
        "read": 20.0,
        "write": 10.0,
        "pool": 5.0,
    }


def test_steam_closes_owned_client() -> None:
    gateway = SteamGateway(base_url="http://localhost:18080/api")

    gateway.close()

    assert gateway.is_closed
