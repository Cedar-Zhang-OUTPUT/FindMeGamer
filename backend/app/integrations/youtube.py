from datetime import datetime, timezone
import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.analysis.contracts import CreatorSource, VideoSource
from app.analysis.targets import CanonicalTarget
from app.core.config import validate_external_base_url
from app.db.models.enums import TargetType
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.http import (
    InvalidContentLength,
    ResponseTooLarge,
    read_bounded_bytes,
    streaming_response,
)

DEFAULT_YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
MAX_YOUTUBE_RESPONSE_BYTES = 4_000_000
MAX_PLAYLIST_PAGES = 5
MAX_SCANNED_VIDEO_IDS = 250
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
_channel_id = re.compile(r"^UC[A-Za-z0-9_-]{6,126}$")
_handle = re.compile(r"^@[a-z0-9._-]{3,30}$")
_playlist_id = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_video_id = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
# YouTube page tokens are opaque, bounded ASCII URL-safe identifiers.
_page_token = re.compile(r"^[A-Za-z0-9_-]{1,512}$")
# Durations use canonical, integer ISO 8601 components; time fields are normalized.
_duration = re.compile(
    r"^P(?:(?P<days>0|[1-9][0-9]{0,3})D)?"
    r"(?:T(?:(?P<hours>0|[1-9][0-9]?)H)?"
    r"(?:(?P<minutes>0|[1-9][0-9]?)M)?"
    r"(?:(?P<seconds>0|[1-9][0-9]?)S)?)?$"
)
_rfc3339_timestamp = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}" r"(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
MAX_VIDEO_DURATION_SECONDS = 315_576_000
_TRANSIENT_403_REASONS = frozenset(
    {
        "quotaExceeded",
        "dailyLimitExceeded",
        "userRateLimitExceeded",
        "rateLimitExceeded",
        "backendError",
    }
)


class YouTubeGateway:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_YOUTUBE_API_BASE_URL,
        http_client: httpx.Client | None = None,
    ) -> None:
        _validate_api_key(api_key)
        self._api_key = api_key
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

    def __enter__(self) -> "YouTubeGateway":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def resolve_channel(self, target: CanonicalTarget) -> str:
        if target.target_type is not TargetType.CREATOR:
            raise PermanentIntegrationError("youtube_target_invalid")
        if not target.requires_resolution:
            _validate_channel_id(target.canonical_id)
            return target.canonical_id
        if not _handle.fullmatch(target.canonical_id):
            raise PermanentIntegrationError("youtube_target_invalid")
        payload = self._request_json(
            "channels",
            {"part": "id", "forHandle": target.canonical_id},
        )
        items = _items(payload, limit=2)
        if len(items) != 1:
            raise PermanentIntegrationError("youtube_channel_not_found")
        resolved = items[0].get("id")
        if not isinstance(resolved, str) or not _channel_id.fullmatch(resolved):
            raise PermanentIntegrationError("youtube_channel_not_found")
        return resolved

    def fetch_creator(self, channel_id: str, video_limit: int = 50) -> CreatorSource:
        _validate_channel_id(channel_id)
        if (
            isinstance(video_limit, bool)
            or not isinstance(video_limit, int)
            or not 1 <= video_limit <= 50
        ):
            raise PermanentIntegrationError("youtube_video_limit_invalid")
        channel_payload = self._request_json(
            "channels",
            {
                "part": "snippet,contentDetails,statistics,brandingSettings",
                "id": channel_id,
            },
        )
        channel_items = _items(channel_payload, limit=2)
        if not channel_items:
            raise PermanentIntegrationError("youtube_channel_not_found")
        if len(channel_items) != 1 or channel_items[0].get("id") != channel_id:
            raise PermanentIntegrationError("youtube_response_invalid")
        channel = channel_items[0]
        try:
            playlist_id = _uploads_playlist_id(channel)
            playlist_ids, raw_pages = self._scan_uploads(playlist_id)
            videos, raw_video_responses = self._fetch_videos(
                playlist_ids,
                channel_id=channel_id,
                limit=video_limit,
            )
            return _map_creator(
                channel,
                channel_id=channel_id,
                playlist_id=playlist_id,
                videos=videos,
                raw_pages=raw_pages,
                raw_video_responses=raw_video_responses,
            )
        except (TypeError, ValueError, ValidationError):
            raise PermanentIntegrationError("youtube_response_invalid") from None

    def _scan_uploads(
        self, playlist_id: str
    ) -> tuple[list[str], tuple[dict[str, Any], ...]]:
        video_ids: list[str] = []
        seen: set[str] = set()
        seen_page_tokens: set[str] = set()
        raw_pages: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(MAX_PLAYLIST_PAGES):
            params = {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": "50",
            }
            if page_token is not None:
                params["pageToken"] = page_token
            page = self._request_json("playlistItems", params)
            raw_pages.append(page)
            for item in _items(page, limit=50):
                content = item.get("contentDetails")
                if not isinstance(content, dict):
                    continue
                video_id = content.get("videoId")
                if video_id is None:
                    continue
                if not isinstance(video_id, str) or not _video_id.fullmatch(video_id):
                    raise PermanentIntegrationError("youtube_response_invalid")
                if video_id in seen:
                    continue
                seen.add(video_id)
                video_ids.append(video_id)
                if len(video_ids) >= MAX_SCANNED_VIDEO_IDS:
                    return video_ids, tuple(raw_pages)
            next_token = page.get("nextPageToken")
            if next_token is None:
                break
            if not isinstance(next_token, str) or not _page_token.fullmatch(next_token):
                raise ValueError("invalid next page token")
            if next_token in seen_page_tokens:
                raise PermanentIntegrationError("youtube_response_invalid")
            seen_page_tokens.add(next_token)
            page_token = next_token
        return video_ids, tuple(raw_pages)

    def _fetch_videos(
        self,
        video_ids: list[str],
        *,
        channel_id: str,
        limit: int,
    ) -> tuple[tuple[VideoSource, ...], tuple[dict[str, Any], ...]]:
        by_id: dict[str, VideoSource] = {}
        raw_responses: list[dict[str, Any]] = []
        for offset in range(0, len(video_ids), 50):
            chunk = video_ids[offset : offset + 50]
            payload = self._request_json(
                "videos",
                {
                    "part": "snippet,contentDetails,statistics,status",
                    "id": ",".join(chunk),
                    "maxResults": "50",
                },
            )
            raw_responses.append(payload)
            for item in _items(payload, limit=50):
                video_id = item.get("id")
                if not isinstance(video_id, str) or video_id not in chunk:
                    continue
                status = item.get("status")
                if (
                    not isinstance(status, dict)
                    or status.get("privacyStatus") != "public"
                ):
                    continue
                if video_id in by_id:
                    continue
                by_id[video_id] = _map_video(item, expected_channel_id=channel_id)
        ordered = tuple(by_id[value] for value in video_ids if value in by_id)[:limit]
        return ordered, tuple(raw_responses)

    def _request_json(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            with streaming_response(
                self._client,
                "GET",
                f"{self._base_url}/{endpoint}",
                params=params,
                headers={"X-Goog-Api-Key": self._api_key},
                auth=None,
                timeout=HTTP_TIMEOUT,
                follow_redirects=False,
            ) as response:
                if response.status_code == 403:
                    error_body = read_bounded_bytes(
                        response,
                        max_bytes=MAX_YOUTUBE_RESPONSE_BYTES,
                    )
                    _raise_for_status(
                        response.status_code,
                        error_payload=_decode_json_or_none(error_body),
                    )
                _raise_for_status(response.status_code)
                body = read_bounded_bytes(
                    response,
                    max_bytes=MAX_YOUTUBE_RESPONSE_BYTES,
                )
        except ResponseTooLarge:
            raise PermanentIntegrationError("youtube_response_too_large") from None
        except InvalidContentLength:
            raise PermanentIntegrationError("youtube_response_invalid") from None
        except httpx.TransportError:
            raise TransientIntegrationError("youtube_unavailable") from None
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, ValueError):
            raise PermanentIntegrationError("youtube_response_invalid") from None
        if not isinstance(payload, dict):
            raise PermanentIntegrationError("youtube_response_invalid")
        return payload


def _validate_api_key(api_key: str) -> None:
    if (
        not isinstance(api_key, str)
        or not api_key
        or len(api_key) > 16_384
        or any(character.isspace() or ord(character) < 32 for character in api_key)
    ):
        raise PermanentIntegrationError("youtube_configuration_invalid")


def _validate_channel_id(channel_id: str) -> None:
    if not isinstance(channel_id, str) or not _channel_id.fullmatch(channel_id):
        raise PermanentIntegrationError("youtube_channel_id_invalid")


def _raise_for_status(status: int, *, error_payload: object = None) -> None:
    if status == 403:
        if _has_transient_403_reason(error_payload):
            raise TransientIntegrationError("youtube_quota_unavailable")
        raise PermanentIntegrationError("youtube_request_rejected")
    if status == 429 or status >= 500:
        raise TransientIntegrationError("youtube_unavailable")
    if status >= 400:
        raise PermanentIntegrationError("youtube_request_rejected")


def _decode_json_or_none(body: bytes) -> object:
    try:
        return json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None


def _has_transient_403_reason(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if not isinstance(error, dict):
        return False
    errors = error.get("errors")
    if not isinstance(errors, list) or len(errors) > 20:
        return False
    return any(
        isinstance(item, dict) and item.get("reason") in _TRANSIENT_403_REASONS
        for item in errors
    )


def _items(payload: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list) or len(items) > limit:
        raise PermanentIntegrationError("youtube_response_invalid")
    if not all(isinstance(item, dict) for item in items):
        raise PermanentIntegrationError("youtube_response_invalid")
    return items


def _uploads_playlist_id(channel: dict[str, Any]) -> str:
    content = channel.get("contentDetails")
    if not isinstance(content, dict):
        raise ValueError("missing content details")
    related = content.get("relatedPlaylists")
    if not isinstance(related, dict):
        raise ValueError("missing related playlists")
    playlist_id = related.get("uploads")
    if not isinstance(playlist_id, str) or not _playlist_id.fullmatch(playlist_id):
        raise ValueError("invalid uploads playlist")
    return playlist_id


def _map_creator(
    channel: dict[str, Any],
    *,
    channel_id: str,
    playlist_id: str,
    videos: tuple[VideoSource, ...],
    raw_pages: tuple[dict[str, Any], ...],
    raw_video_responses: tuple[dict[str, Any], ...],
) -> CreatorSource:
    snippet = _mapping(channel.get("snippet"))
    statistics = _mapping(channel.get("statistics"))
    branding = _mapping(channel.get("brandingSettings"))
    branding_image = _mapping(branding.get("image"))
    hidden = _optional_bool(statistics.get("hiddenSubscriberCount"))
    subscribers = (
        None if hidden is True else _optional_count(statistics.get("subscriberCount"))
    )
    return CreatorSource(
        channel_id=channel_id,
        canonical_url=f"https://www.youtube.com/channel/{channel_id}",
        title=_required_string(snippet.get("title"), max_length=512),
        description=_optional_string(snippet.get("description"), max_length=500_000)
        or "",
        custom_url=_optional_string(snippet.get("customUrl"), max_length=256),
        published_at=_optional_datetime(snippet.get("publishedAt")),
        country=_optional_string(snippet.get("country"), max_length=16),
        thumbnail_urls=_thumbnail_urls(snippet.get("thumbnails")),
        banner_url=_optional_string(
            branding_image.get("bannerExternalUrl"), max_length=2_048
        ),
        subscriber_count=subscribers,
        hidden_subscriber_count=hidden,
        total_view_count=_optional_count(statistics.get("viewCount")),
        public_video_count=_optional_count(statistics.get("videoCount")),
        uploads_playlist_id=playlist_id,
        videos=videos,
        raw_channel=channel,
        raw_playlist_pages=raw_pages,
        raw_video_responses=raw_video_responses,
    )


def _map_video(item: dict[str, Any], *, expected_channel_id: str) -> VideoSource:
    video_id = _required_string(item.get("id"), max_length=128)
    snippet = _mapping(item.get("snippet"))
    returned_channel_id = snippet.get("channelId")
    if returned_channel_id != expected_channel_id:
        raise PermanentIntegrationError("youtube_response_invalid")
    content = _mapping(item.get("contentDetails"))
    statistics = _mapping(item.get("statistics"))
    tags_value = snippet.get("tags")
    if tags_value is None:
        tags: tuple[str, ...] = ()
    elif isinstance(tags_value, list) and len(tags_value) <= 100:
        tags = tuple(_required_string(value, max_length=512) for value in tags_value)
    else:
        raise ValueError("invalid tags")
    return VideoSource(
        id=video_id,
        title=_required_string(snippet.get("title"), max_length=512),
        description=_optional_string(snippet.get("description"), max_length=500_000)
        or "",
        published_at=_optional_datetime(snippet.get("publishedAt")),
        channel_id=expected_channel_id,
        tags=tags,
        category_id=_optional_string(snippet.get("categoryId"), max_length=32),
        duration_seconds=_optional_duration(content.get("duration")),
        definition=_optional_string(content.get("definition"), max_length=16),
        caption_available=_caption_bool(content.get("caption")),
        audio_language=_optional_string(
            snippet.get("defaultAudioLanguage"), max_length=255
        ),
        view_count=_optional_count(statistics.get("viewCount")),
        like_count=_optional_count(statistics.get("likeCount")),
        comment_count=_optional_count(statistics.get("commentCount")),
        thumbnail_urls=_thumbnail_urls(snippet.get("thumbnails")),
        raw=item,
    )


def _mapping(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 100:
        raise ValueError("invalid object")
    return value


def _required_string(value: object, *, max_length: int) -> str:
    result = _optional_string(value, max_length=max_length)
    if not result:
        raise ValueError("missing string")
    return result


def _optional_string(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError("invalid string")
    return value


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("invalid boolean")
    return value


def _optional_count(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid count")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        result = int(value)
    else:
        raise ValueError("invalid count")
    if not 0 <= result <= 9_223_372_036_854_775_807:
        raise ValueError("invalid count")
    return result


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > 64
        or _rfc3339_timestamp.fullmatch(value) is None
    ):
        raise ValueError("invalid date")
    try:
        parsed = datetime.fromisoformat(
            f"{value[:-1]}+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        raise ValueError("invalid date") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid date")
    return parsed.astimezone(timezone.utc)


def _optional_duration(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid duration")
    match = _duration.fullmatch(value)
    if match is None:
        raise ValueError("invalid duration")
    groups = match.groupdict()
    if all(part is None for part in groups.values()):
        raise ValueError("invalid duration")
    if "T" in value and all(
        groups[name] is None for name in ("hours", "minutes", "seconds")
    ):
        raise ValueError("invalid duration")
    parts = {name: int(number or 0) for name, number in groups.items()}
    if parts["hours"] > 23 or parts["minutes"] > 59 or parts["seconds"] > 59:
        raise ValueError("invalid duration")
    seconds = (
        parts["days"] * 86_400
        + parts["hours"] * 3_600
        + parts["minutes"] * 60
        + parts["seconds"]
    )
    if seconds > MAX_VIDEO_DURATION_SECONDS:
        raise ValueError("invalid duration")
    return seconds


def _caption_bool(value: object) -> bool | None:
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("invalid caption flag")


def _thumbnail_urls(value: object) -> tuple[str, ...]:
    mapping = _mapping(value)
    if len(mapping) > 10:
        raise ValueError("too many thumbnails")
    urls: list[str] = []
    for entry in mapping.values():
        item = _mapping(entry)
        url = _optional_string(item.get("url"), max_length=2_048)
        if url is not None:
            urls.append(url)
    return tuple(urls)
