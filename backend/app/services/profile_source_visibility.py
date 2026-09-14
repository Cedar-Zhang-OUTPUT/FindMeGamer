"""Shared public and editor visibility policy for retained Creator sources."""


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
    if _canonical_status_is_stale(source_status.get("youtube")):
        return True
    if any(
        _canonical_status_is_stale(source_status.get(key))
        for key in ("youtube_status", "youtube_state", "youtube_freshness")
        if key in source_status
    ):
        return True
    sources = source_status.get("sources")
    return isinstance(sources, dict) and _canonical_status_is_stale(
        sources.get("youtube")
    )
