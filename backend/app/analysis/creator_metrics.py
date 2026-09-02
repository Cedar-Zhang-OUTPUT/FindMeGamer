"""Deterministic public metrics and thumbnail selection for Creator Analyze."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from math import isfinite
from statistics import median
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.contracts import VideoSource


class PublishingFrequency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sample_count: Annotated[int, Field(ge=2, le=50)]
    span_days: Annotated[float, Field(gt=0)]
    uploads_per_30_days: Annotated[float, Field(gt=0)]


class CreatorComputedMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    recent_public_video_count: Annotated[int, Field(ge=0, le=50)]
    numeric_view_sample_count: Annotated[int, Field(ge=0, le=50)]
    average_views: int | float | None
    median_views: int | float | None
    publishing_frequency: PublishingFrequency | None
    newest_published_at: datetime | None
    oldest_published_at: datetime | None


def compute_creator_metrics(
    videos: Sequence[VideoSource],
) -> CreatorComputedMetrics:
    """Compute bounded JSON-safe public metrics from unique official records."""

    unique = _unique_videos(videos)[:50]
    counts = [
        value
        for video in unique
        if (value := _valid_nonnegative_int(video.view_count)) is not None
    ]
    timestamps = [
        value
        for video in unique
        if (value := _aware_utc(video.published_at)) is not None
    ]
    average: int | float | None = None
    middle: int | float | None = None
    if counts:
        raw_average = sum(counts) / len(counts)
        average = _finite_number(raw_average)
        middle = _finite_number(float(median(counts)))
    frequency: PublishingFrequency | None = None
    newest: datetime | None = None
    oldest: datetime | None = None
    if timestamps:
        newest = max(timestamps)
        oldest = min(timestamps)
        span_days = (newest - oldest).total_seconds() / 86_400
        if len(timestamps) >= 2 and isfinite(span_days) and span_days > 0:
            rate = len(timestamps) * 30 / span_days
            if isfinite(rate) and rate > 0:
                frequency = PublishingFrequency(
                    sample_count=len(timestamps),
                    span_days=round(span_days, 6),
                    uploads_per_30_days=round(rate, 6),
                )
    return CreatorComputedMetrics(
        recent_public_video_count=len(unique),
        numeric_view_sample_count=len(counts),
        average_views=average,
        median_views=middle,
        publishing_frequency=frequency,
        newest_published_at=newest,
        oldest_published_at=oldest,
    )


def select_representative_thumbnails(
    videos: Sequence[VideoSource], count: int = 12
) -> list[VideoSource]:
    """Balance newest and highest-view official thumbnails deterministically."""

    if type(count) is not int or not 1 <= count <= 12:
        raise ValueError("thumbnail count must be an integer from 1 through 12")
    eligible = [video for video in _unique_videos(videos)[:50] if video.thumbnail_urls]
    if not eligible:
        return []
    by_recency = sorted(eligible, key=_recency_key)
    by_performance = sorted(eligible, key=_performance_key)
    selected: list[VideoSource] = []
    identifiers: set[str] = set()

    def add(video: VideoSource) -> None:
        if len(selected) < count and video.id not in identifiers:
            selected.append(video)
            identifiers.add(video.id)

    add(by_recency[0])
    if count > 1:
        add(by_performance[0])
    recency_index = 1
    performance_index = 1
    while len(selected) < count and (
        recency_index < len(by_recency) or performance_index < len(by_performance)
    ):
        if recency_index < len(by_recency):
            add(by_recency[recency_index])
            recency_index += 1
        if len(selected) >= count:
            break
        if performance_index < len(by_performance):
            add(by_performance[performance_index])
            performance_index += 1
    return selected


def _unique_videos(videos: Sequence[VideoSource]) -> list[VideoSource]:
    if not isinstance(videos, Sequence) or isinstance(videos, str | bytes | bytearray):
        raise TypeError("videos must be a sequence of VideoSource")
    by_id: dict[str, VideoSource] = {}
    for video in videos:
        if not isinstance(video, VideoSource) or not video.id:
            continue
        existing = by_id.get(video.id)
        if existing is None or _canonical_record_key(video) < _canonical_record_key(
            existing
        ):
            by_id[video.id] = video
    return sorted(by_id.values(), key=lambda video: video.id)


def _canonical_record_key(video: VideoSource) -> tuple[object, ...]:
    return (*_recency_key(video), *_performance_key(video), video.title)


def _recency_key(video: VideoSource) -> tuple[int, float, str]:
    published = _aware_utc(video.published_at)
    return (
        0 if published is not None else 1,
        -published.timestamp() if published is not None else 0.0,
        video.id,
    )


def _performance_key(video: VideoSource) -> tuple[int, int, int, float, str]:
    count = _valid_nonnegative_int(video.view_count)
    published = _aware_utc(video.published_at)
    return (
        0 if count is not None else 1,
        -count if count is not None else 0,
        0 if published is not None else 1,
        -published.timestamp() if published is not None else 0.0,
        video.id,
    )


def _valid_nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _aware_utc(value: object) -> datetime | None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        return None
    return value.astimezone(UTC)


def _finite_number(value: float) -> int | float | None:
    if not isfinite(value):
        return None
    return int(value) if value.is_integer() else round(value, 6)


__all__ = [
    "compute_creator_metrics",
    "CreatorComputedMetrics",
    "select_representative_thumbnails",
]
