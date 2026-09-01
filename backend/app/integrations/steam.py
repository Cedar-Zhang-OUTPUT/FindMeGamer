from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from app.analysis.contracts import SteamGameSource, SteamMovie, SteamScreenshot
from app.core.config import validate_external_base_url
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError

DEFAULT_STEAM_STORE_BASE_URL = "https://store.steampowered.com/api"
MAX_STEAM_RESPONSE_BYTES = 2_000_000
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)


class SteamGateway:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_STEAM_STORE_BASE_URL,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = validate_external_base_url(base_url)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=HTTP_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        )

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "SteamGateway":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_game(self, app_id: str) -> SteamGameSource:
        _validate_app_id(app_id)
        try:
            response = self._client.get(
                f"{self._base_url}/appdetails",
                params={"appids": app_id, "l": "english", "cc": "US"},
                timeout=HTTP_TIMEOUT,
                follow_redirects=False,
            )
        except httpx.TransportError:
            raise TransientIntegrationError("steam_unavailable") from None
        _raise_for_status(response)
        payload = _bounded_json(response)
        data = _extract_game(payload, app_id)
        try:
            return _map_game(data, app_id)
        except (TypeError, ValueError, ValidationError):
            raise PermanentIntegrationError("steam_response_invalid") from None


def _validate_app_id(app_id: str) -> None:
    if (
        not isinstance(app_id, str)
        or not app_id.isascii()
        or not app_id.isdecimal()
        or app_id.startswith("0")
        or len(app_id) > 10
    ):
        raise PermanentIntegrationError("steam_app_id_invalid")
    numeric = int(app_id)
    if not 1 <= numeric <= 2_147_483_647:
        raise PermanentIntegrationError("steam_app_id_invalid")


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 429 or response.status_code >= 500:
        raise TransientIntegrationError("steam_unavailable")
    if response.status_code >= 400:
        raise PermanentIntegrationError("steam_request_rejected")


def _bounded_json(response: httpx.Response) -> object:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_STEAM_RESPONSE_BYTES:
                raise PermanentIntegrationError("steam_response_too_large")
        except ValueError:
            raise PermanentIntegrationError("steam_response_invalid") from None
    if len(response.content) > MAX_STEAM_RESPONSE_BYTES:
        raise PermanentIntegrationError("steam_response_too_large")
    try:
        return response.json()
    except ValueError:
        raise PermanentIntegrationError("steam_response_invalid") from None


def _extract_game(payload: object, app_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PermanentIntegrationError("steam_response_invalid")
    envelope = payload.get(app_id)
    if envelope is None:
        raise PermanentIntegrationError("steam_game_not_found")
    if not isinstance(envelope, dict):
        raise PermanentIntegrationError("steam_response_invalid")
    if envelope.get("success") is False:
        raise PermanentIntegrationError("steam_game_not_found")
    if envelope.get("success") is not True or not isinstance(
        envelope.get("data"), dict
    ):
        raise PermanentIntegrationError("steam_response_invalid")
    return envelope["data"]


def _map_game(data: dict[str, Any], app_id: str) -> SteamGameSource:
    if _required_int(data, "steam_appid") != int(app_id):
        raise ValueError("mismatched app id")
    name = _required_string(data, "name", max_length=512)
    release = _optional_mapping(data.get("release_date"))
    recommendations = _optional_mapping(data.get("recommendations"))
    return SteamGameSource(
        app_id=app_id,
        canonical_url=f"https://store.steampowered.com/app/{app_id}",
        name=name,
        type=_optional_string(data.get("type"), max_length=64),
        required_age=_optional_int(data.get("required_age")),
        is_free=_optional_bool(data.get("is_free")),
        developers=_string_list(data.get("developers"), limit=100),
        publishers=_string_list(data.get("publishers"), limit=100),
        release_date=_optional_string(release.get("date"), max_length=256),
        coming_soon=_optional_bool(release.get("coming_soon")),
        short_description=_optional_string(
            data.get("short_description"), max_length=100_000
        ),
        detailed_description=_optional_string(
            data.get("detailed_description"), max_length=500_000
        ),
        about_the_game=_optional_string(data.get("about_the_game"), max_length=500_000),
        genres=_description_list(data.get("genres"), limit=100),
        categories=_description_list(data.get("categories"), limit=200),
        platforms=_platforms(data.get("platforms")),
        supported_languages=_optional_string(
            data.get("supported_languages"), max_length=100_000
        ),
        review_summary=_optional_string(data.get("review_score_desc"), max_length=256),
        recommendation_count=_optional_int(recommendations.get("total")),
        header_image_url=_optional_string(data.get("header_image"), max_length=2_048),
        cover_image_url=_optional_string(
            data.get("capsule_image") or data.get("capsule_imagev5"),
            max_length=2_048,
        ),
        screenshots=_screenshots(data.get("screenshots")),
        movies=_movies(data.get("movies")),
        raw=data,
    )


def _required_string(mapping: Mapping[str, Any], key: str, *, max_length: int) -> str:
    value = _optional_string(mapping.get(key), max_length=max_length)
    if value is None or not value:
        raise ValueError(f"missing {key}")
    return value


def _optional_string(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError("invalid string")
    return value


def _required_int(mapping: Mapping[str, Any], key: str) -> int:
    value = _optional_int(mapping.get(key))
    if value is None:
        raise ValueError(f"missing {key}")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        parsed = int(value)
    else:
        raise ValueError("invalid integer")
    if parsed < 0 or parsed > 9_223_372_036_854_775_807:
        raise ValueError("invalid integer")
    return parsed


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("invalid boolean")
    return value


def _optional_mapping(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("invalid object")
    return value


def _bounded_list(value: object, *, limit: int) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("invalid list")
    return value


def _string_list(value: object, *, limit: int) -> tuple[str, ...]:
    values = _bounded_list(value, limit=limit)
    result: list[str] = []
    for item in values:
        text = _optional_string(item, max_length=512)
        if text is None:
            raise ValueError("invalid string list")
        result.append(text)
    return tuple(result)


def _description_list(value: object, *, limit: int) -> tuple[str, ...]:
    values = _bounded_list(value, limit=limit)
    descriptions: list[str] = []
    for item in values:
        mapping = _optional_mapping(item)
        descriptions.append(_required_string(mapping, "description", max_length=512))
    return tuple(descriptions)


def _platforms(value: object) -> tuple[str, ...]:
    mapping = _optional_mapping(value)
    if len(mapping) > 20:
        raise ValueError("too many platforms")
    enabled: list[str] = []
    for name, state in mapping.items():
        if not isinstance(name, str) or len(name) > 64 or not isinstance(state, bool):
            raise ValueError("invalid platform")
        if state:
            enabled.append(name)
    return tuple(sorted(enabled))


def _screenshots(value: object) -> tuple[SteamScreenshot, ...]:
    result: list[SteamScreenshot] = []
    for item in _bounded_list(value, limit=100):
        mapping = _optional_mapping(item)
        result.append(
            SteamScreenshot(
                id=_optional_int(mapping.get("id")),
                full_url=_required_string(mapping, "path_full", max_length=2_048),
                thumbnail_url=_optional_string(
                    mapping.get("path_thumbnail"), max_length=2_048
                ),
            )
        )
    return tuple(result)


def _movies(value: object) -> tuple[SteamMovie, ...]:
    result: list[SteamMovie] = []
    for item in _bounded_list(value, limit=50):
        mapping = _optional_mapping(item)
        mp4 = _optional_mapping(mapping.get("mp4"))
        webm = _optional_mapping(mapping.get("webm"))
        result.append(
            SteamMovie(
                id=_optional_int(mapping.get("id")),
                name=_required_string(mapping, "name", max_length=512),
                thumbnail_url=_optional_string(
                    mapping.get("thumbnail"), max_length=2_048
                ),
                mp4_urls=_media_urls(mp4),
                webm_urls=_media_urls(webm),
            )
        )
    return tuple(result)


def _media_urls(mapping: Mapping[str, Any]) -> tuple[str, ...]:
    if len(mapping) > 10:
        raise ValueError("too many media variants")
    urls: list[str] = []
    for value in mapping.values():
        url = _optional_string(value, max_length=2_048)
        if url is None:
            raise ValueError("invalid media URL")
        urls.append(url)
    return tuple(urls)
