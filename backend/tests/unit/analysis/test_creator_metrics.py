from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import nan

import pytest

from app.analysis.contracts import VideoSource
from app.analysis.creator_metrics import (
    compute_creator_metrics,
    select_representative_thumbnails,
)


NOW = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def _video(
    identifier: str,
    *,
    days_old: int | None,
    views: int | None,
    thumbnail: bool = True,
) -> VideoSource:
    return VideoSource(
        id=identifier,
        title=f"Video {identifier}",
        published_at=NOW - timedelta(days=days_old) if days_old is not None else None,
        channel_id="UCcreator123",
        view_count=views,
        thumbnail_urls=(f"https://cdn.example/{identifier}.jpg",) if thumbnail else (),
        raw={},
    )


def test_metrics_are_exact_json_safe_and_ignore_duplicate_ids() -> None:
    videos = (
        _video("a", days_old=0, views=100),
        _video("b", days_old=7, views=20),
        _video("a", days_old=1, views=999),
        _video("c", days_old=14, views=None),
    )

    metrics = compute_creator_metrics(videos)

    assert metrics.model_dump(mode="json") == {
        "recent_public_video_count": 3,
        "numeric_view_sample_count": 2,
        "average_views": 60,
        "median_views": 60,
        "publishing_frequency": {
            "sample_count": 3,
            "span_days": 14.0,
            "uploads_per_30_days": 6.428571,
        },
        "newest_published_at": "2026-09-02T08:00:00Z",
        "oldest_published_at": "2026-08-19T08:00:00Z",
    }


def test_metrics_empty_and_missing_values_are_explicit() -> None:
    metrics = compute_creator_metrics((_video("unknown", days_old=None, views=None),))
    assert metrics.recent_public_video_count == 1
    assert metrics.numeric_view_sample_count == 0
    assert metrics.average_views is None
    assert metrics.median_views is None
    assert metrics.publishing_frequency is None
    assert metrics.newest_published_at is None
    assert metrics.oldest_published_at is None


def test_metrics_reject_unaware_timestamps_and_bool_or_nonfinite_counts() -> None:
    unaware = _video("unaware", days_old=1, views=None).model_copy(
        update={"published_at": datetime(2026, 9, 1, 8, 0)}
    )
    boolean = _video("boolean", days_old=None, views=10).model_copy(
        update={"view_count": True}
    )
    nonfinite = _video("nonfinite", days_old=None, views=10).model_copy(
        update={"view_count": nan}
    )

    metrics = compute_creator_metrics((unaware, boolean, nonfinite))

    assert metrics.numeric_view_sample_count == 0
    assert metrics.average_views is None
    assert metrics.newest_published_at is None


def test_metrics_ignore_oversized_integer_counts_without_float_overflow() -> None:
    oversized = _video("oversized", days_old=None, views=10).model_copy(
        update={"view_count": 10**10_000}
    )

    metrics = compute_creator_metrics((oversized,))

    assert metrics.numeric_view_sample_count == 0
    assert metrics.average_views is None
    assert metrics.median_views is None


def test_metrics_round_and_bound_near_limit_fractional_mean_and_median() -> None:
    maximum = 9_223_372_036_854_775_807
    videos = (
        _video("maximum", days_old=None, views=maximum),
        _video("near-maximum", days_old=None, views=maximum - 1),
    )

    metrics = compute_creator_metrics(videos)

    assert metrics.average_views == maximum
    assert metrics.median_views == maximum


@pytest.mark.parametrize(
    ("offset", "rounded_result"),
    [
        (1_023, 9_223_372_036_854_775_296),
        (3_071, 9_223_372_036_854_774_272),
    ],
)
def test_near_limit_fractional_statistics_use_integer_fallback_when_float_is_inexact(
    offset: int, rounded_result: int
) -> None:
    maximum = 9_223_372_036_854_775_807

    metrics = compute_creator_metrics(
        (
            _video("maximum", days_old=None, views=maximum),
            _video("offset", days_old=None, views=maximum - offset),
        )
    )

    assert metrics.average_views == rounded_result
    assert metrics.median_views == rounded_result


def test_sub_rounding_publication_span_is_explicitly_unavailable() -> None:
    newest = _video("newest", days_old=None, views=None).model_copy(
        update={"published_at": NOW}
    )
    almost_same = _video("almost-same", days_old=None, views=None).model_copy(
        update={"published_at": NOW - timedelta(microseconds=1)}
    )

    metrics = compute_creator_metrics((newest, almost_same))

    assert metrics.publishing_frequency is None
    assert metrics.newest_published_at == NOW
    assert metrics.oldest_published_at == NOW - timedelta(microseconds=1)


def test_thumbnail_selection_balances_recency_and_performance_deterministically() -> (
    None
):
    videos = tuple(
        _video(str(index), days_old=index, views=index * 1_000) for index in range(20)
    )

    selected = select_representative_thumbnails(videos, count=12)

    assert len(selected) == 12
    assert selected[0].id == "0"
    assert "19" in {video.id for video in selected}
    assert [video.id for video in selected] == [
        video.id
        for video in select_representative_thumbnails(tuple(reversed(videos)), count=12)
    ]


def test_thumbnail_selection_deduplicates_and_ignores_missing_assets() -> None:
    first = _video("same", days_old=0, views=1)
    duplicate = _video("same", days_old=9, views=999)
    missing = _video("missing", days_old=1, views=5_000, thumbnail=False)

    assert select_representative_thumbnails((duplicate, missing, first), count=12) == [
        first
    ]


def test_duplicate_exact_selection_keys_use_stable_thumbnail_tie_break() -> None:
    prototype = _video("same", days_old=1, views=100)
    first = prototype.model_copy(
        update={"thumbnail_urls": ("https://cdn.example/a.jpg",)}
    )
    second = prototype.model_copy(
        update={"thumbnail_urls": ("https://cdn.example/b.jpg",)}
    )

    forward = select_representative_thumbnails((first, second), count=1)
    reverse = select_representative_thumbnails((second, first), count=1)

    assert forward[0].thumbnail_urls == ("https://cdn.example/a.jpg",)
    assert reverse[0].thumbnail_urls == ("https://cdn.example/a.jpg",)


def test_duplicate_public_ties_canonicalize_provider_raw_data() -> None:
    prototype = _video("same", days_old=1, views=100)
    first = prototype.model_copy(update={"raw": {"provider_order": 1}})
    second = prototype.model_copy(update={"raw": {"provider_order": 2}})

    forward = select_representative_thumbnails((first, second), count=1)
    reverse = select_representative_thumbnails((second, first), count=1)

    assert forward == reverse
    assert forward[0].raw == {}


@pytest.mark.parametrize("count", [True, False, 0, 13, 1.0, "12", None])
def test_thumbnail_selection_rejects_invalid_count(count: object) -> None:
    with pytest.raises(ValueError, match="count"):
        select_representative_thumbnails((), count=count)  # type: ignore[arg-type]
