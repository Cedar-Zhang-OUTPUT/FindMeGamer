"""Shared public and editor visibility policy for retained Creator sources."""

from datetime import UTC, datetime, timedelta


def curated_source_is_expired(profile, *, now=None) -> bool:
    """Enforce curated freshness even between periodic stale-marker runs."""
    return (
        profile.platform in {"twitch", "instagram"}
        and profile.last_analyzed_at is not None
        and profile.last_analyzed_at < (now or datetime.now(UTC)) - timedelta(days=30)
    )


def creator_source_is_stale(profile) -> bool:
    return _creator_youtube_is_stale(
        profile.source_status
    ) or curated_source_is_expired(profile)


def visible_creator_source_status(profile):
    status = dict(profile.source_status)
    if curated_source_is_expired(profile):
        status["freshness"] = "stale"
    return status


def _canonical_status_is_stale(value: object) -> bool:
    if isinstance(value, str):
        return value.casefold() == "stale"
    if isinstance(value, dict):
        return any(
            _canonical_status_is_stale(value.get(key))
            for key in ("status", "state", "freshness")
            if key in value
        )
    return False


def _creator_youtube_is_stale(source_status: object) -> bool:
    if not isinstance(source_status, dict):
        return False
    if any(
        _canonical_status_is_stale(source_status.get(key))
        for key in ("status", "state", "freshness")
        if key in source_status
    ):
        return True
    if any(
        _canonical_status_is_stale(source_status.get(platform))
        for platform in ("youtube", "x")
    ):
        return True
    if any(
        _canonical_status_is_stale(source_status.get(key))
        for key in (
            "youtube_status",
            "youtube_state",
            "youtube_freshness",
            "x_status",
            "x_state",
            "x_freshness",
        )
        if key in source_status
    ):
        return True
    sources = source_status.get("sources")
    return isinstance(sources, dict) and any(
        _canonical_status_is_stale(sources.get(platform))
        for platform in ("youtube", "x")
    )
