from datetime import datetime
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _SourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Message(_SourceModel):
    role: Literal["system", "user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=131_072)]


class SteamScreenshot(_SourceModel):
    id: int | None = None
    full_url: str
    thumbnail_url: str | None = None


class SteamMovie(_SourceModel):
    id: int | None = None
    name: str
    thumbnail_url: str | None = None
    mp4_urls: tuple[str, ...] = ()
    webm_urls: tuple[str, ...] = ()


class SteamGameSource(_SourceModel):
    app_id: str
    canonical_url: str
    name: str
    type: str | None = None
    required_age: int | None = None
    is_free: bool | None = None
    developers: tuple[str, ...] = ()
    publishers: tuple[str, ...] = ()
    release_date: str | None = None
    coming_soon: bool | None = None
    short_description: str | None = None
    detailed_description: str | None = None
    about_the_game: str | None = None
    genres: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    supported_languages: str | None = None
    review_summary: str | None = None
    recommendation_count: int | None = None
    header_image_url: str | None = None
    cover_image_url: str | None = None
    screenshots: tuple[SteamScreenshot, ...] = ()
    movies: tuple[SteamMovie, ...] = ()
    raw: dict[str, Any]


class VideoSource(_SourceModel):
    id: str
    title: str
    description: str = ""
    published_at: datetime | None = None
    channel_id: str | None = None
    tags: tuple[str, ...] = ()
    category_id: str | None = None
    duration_seconds: int | None = None
    definition: str | None = None
    caption_available: bool | None = None
    audio_language: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    thumbnail_urls: tuple[str, ...] = ()
    raw: dict[str, Any]


class CreatorSource(_SourceModel):
    channel_id: str
    canonical_url: str
    title: str
    description: str = ""
    custom_url: str | None = None
    published_at: datetime | None = None
    country: str | None = None
    thumbnail_urls: tuple[str, ...] = ()
    banner_url: str | None = None
    subscriber_count: int | None = None
    hidden_subscriber_count: bool | None = None
    total_view_count: int | None = None
    public_video_count: int | None = None
    uploads_playlist_id: str
    videos: tuple[VideoSource, ...]
    raw_channel: dict[str, Any]
    raw_playlist_pages: tuple[dict[str, Any], ...]
    raw_video_responses: tuple[dict[str, Any], ...]


@runtime_checkable
class ArtifactStore(Protocol):
    def put_json(
        self,
        job_id: UUID,
        name: str,
        payload: Mapping[str, Any],
    ) -> str: ...
