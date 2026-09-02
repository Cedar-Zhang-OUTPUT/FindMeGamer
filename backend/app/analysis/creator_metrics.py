"""Deterministic public metrics and thumbnail selection for Creator Analyze."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.contracts import VideoSource


MAX_PUBLIC_COUNT = 9_223_372_036_854_775_807


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
        average = _bounded_metric_number(Decimal(sum(counts)) / len(counts))
        ordered_counts = sorted(counts)
        midpoint = len(ordered_counts) // 2
        if len(ordered_counts) % 2:
            raw_median = Decimal(ordered_counts[midpoint])
        else:
            raw_median = (
                Decimal(ordered_counts[midpoint - 1])
                + Decimal(ordered_counts[midpoint])
            ) / 2
        middle = _bounded_metric_number(raw_median)
    frequency: PublishingFrequency | None = None
    newest: datetime | None = None
    oldest: datetime | None = None
    if timestamps:
        newest = max(timestamps)
        oldest = min(timestamps)
        span_days = (newest - oldest).total_seconds() / 86_400
        if len(timestamps) >= 2 and isfinite(span_days) and span_days > 0:
            rounded_span_days = round(span_days, 6)
            rate = len(timestamps) * 30 / span_days
            if rounded_span_days > 0 and isfinite(rate) and rate > 0:
                frequency = PublishingFrequency(
                    sample_count=len(timestamps),
                    span_days=rounded_span_days,
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
        if existing is None:
            by_id[video.id] = video
            continue
        candidate_key = _canonical_record_key(video)
        existing_key = _canonical_record_key(existing)
        if candidate_key < existing_key:
            by_id[video.id] = video
        elif candidate_key == existing_key:
            by_id[video.id] = existing.model_copy(update={"raw": {}})
    return sorted(by_id.values(), key=lambda video: video.id)


def _canonical_record_key(video: VideoSource) -> tuple[object, ...]:
    return (
        *_recency_key(video),
        *_performance_key(video),
        video.title,
        video.description,
        _stable_datetime_key(video.published_at),
        _stable_optional_text_key(video.channel_id),
        video.tags,
        _stable_optional_text_key(video.category_id),
        _stable_optional_int_key(video.duration_seconds),
        _stable_optional_text_key(video.definition),
        _stable_optional_bool_key(video.caption_available),
        _stable_optional_int_key(video.view_count),
        _stable_optional_int_key(video.like_count),
        _stable_optional_int_key(video.comment_count),
        video.thumbnail_urls,
    )


def _stable_datetime_key(value: object) -> tuple[int, str]:
    if isinstance(value, datetime):
        return (0, value.isoformat())
    if value is None:
        return (1, "")
    return (2, f"{type(value).__qualname__}:{value!r}")


def _stable_optional_text_key(value: object) -> tuple[int, str]:
    if isinstance(value, str):
        return (0, value)
    if value is None:
        return (1, "")
    return (2, f"{type(value).__qualname__}:{value!r}")


def _stable_optional_int_key(value: object) -> tuple[int, int, str]:
    if type(value) is int:
        return (0, value, "")
    if value is None:
        return (1, 0, "")
    return (2, 0, f"{type(value).__qualname__}:{value!r}")


def _stable_optional_bool_key(value: object) -> tuple[int, int, str]:
    if type(value) is bool:
        return (0, int(value), "")
    if value is None:
        return (1, 0, "")
    return (2, 0, f"{type(value).__qualname__}:{value!r}")


def _recency_key(video: VideoSource) -> tuple[int, int, int, int, int, int, str]:
    published = _aware_utc(video.published_at)
    return (*_descending_datetime_key(published), video.id)


def _performance_key(
    video: VideoSource,
) -> tuple[int, int, int, int, int, int, int, int, str]:
    count = _valid_nonnegative_int(video.view_count)
    published = _aware_utc(video.published_at)
    return (
        0 if count is not None else 1,
        -count if count is not None else 0,
        *_descending_datetime_key(published),
        video.id,
    )


def _descending_datetime_key(
    value: datetime | None,
) -> tuple[int, int, int, int, int, int]:
    if value is None:
        return (1, 0, 0, 0, 0, 0)
    return (
        0,
        -value.toordinal(),
        -value.hour,
        -value.minute,
        -value.second,
        -value.microsecond,
    )


def _valid_nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= MAX_PUBLIC_COUNT else None


def _aware_utc(value: object) -> datetime | None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        return None
    return value.astimezone(UTC)


def _bounded_metric_number(value: Decimal) -> int | float | None:
    if not value.is_finite() or not 0 <= value <= MAX_PUBLIC_COUNT:
        return None
    if value == value.to_integral_value():
        return int(value)
    rounded = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    candidate = float(rounded)
    if (
        isfinite(candidate)
        and 0 <= candidate <= MAX_PUBLIC_COUNT
        and Decimal(str(candidate)) == rounded
    ):
        return candidate
    bounded_integer = int(value.to_integral_value(rounding=ROUND_HALF_UP))
    return min(bounded_integer, MAX_PUBLIC_COUNT)


__all__ = [
    "compute_creator_metrics",
    "CreatorComputedMetrics",
    "select_representative_thumbnails",
]
