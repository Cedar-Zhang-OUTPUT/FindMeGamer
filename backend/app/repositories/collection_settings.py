"""Administrative policy is independent of credentials and provider outcomes."""

from sqlalchemy import select
from app.analysis.targets import creator_platform

from app.core.errors import APIError
from app.db.models.settings import SharedSettings
from app.repositories.settings import SHARED_SETTINGS_ID, SettingsRepository

PLATFORMS = ("youtube", "x", "twitch", "instagram")
IMPLEMENTED = frozenset(("youtube", "x"))


class CollectionPaused(Exception):
    """Administrative pause, never a provider or Analysis failure."""


def guard_collection(session, platform):
    if not collection_enabled(session, platform):
        raise CollectionPaused()


def require_platform(platform):
    if platform not in PLATFORMS:
        raise APIError(
            status_code=404,
            code="collection_platform_unknown",
            message="The collection platform is not supported.",
        )
    return platform


def collection_enabled(session, platform):
    require_platform(platform)
    values = session.scalar(
        select(SharedSettings.collection_enabled).where(
            SharedSettings.id == SHARED_SETTINGS_ID
        )
    )
    if values is None:
        raise RuntimeError("shared settings row is missing")
    return values.get(platform, platform in IMPLEMENTED)


def collection_settings(session):
    settings = SettingsRepository(session)
    items = []
    for platform in PLATFORMS:
        enabled = collection_enabled(session, platform)
        implemented = platform in IMPLEMENTED
        configured = settings.get_connection(platform) is not None
        availability = (
            "disabled"
            if not enabled
            else (
                "not_implemented"
                if not implemented
                else "missing_connection" if not configured else "configured_unverified"
            )
        )
        items.append(
            dict(
                platform=platform,
                enabled=enabled,
                implemented=implemented,
                credentials_configured=configured,
                availability=availability,
            )
        )
    return {"items": items}


def require_collection(session, platform):
    if not collection_enabled(session, platform):
        raise APIError(
            status_code=409,
            code="collection_disabled",
            message="Collection is paused for this platform. Enable it in Settings before continuing.",
        )


def analysis_waiting_state(session, job):
    if job.target_type != "creator" or job.status not in ("queued", "running"):
        return None, False
    enabled = collection_enabled(session, creator_platform(job.canonical_target_id))
    if job.collection_paused:
        return (
            "explicit_resume_required" if enabled else "collection_disabled"
        ), enabled
    if job.status == "queued" and not enabled:
        return "collection_disabled", False
    return None, False


def update_collection(session, platform, enabled):
    require_platform(platform)
    settings = session.scalar(
        select(SharedSettings)
        .where(SharedSettings.id == SHARED_SETTINGS_ID)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if settings is None:
        raise RuntimeError("shared settings row is missing")
    settings.collection_enabled = {**settings.collection_enabled, platform: enabled}
    session.flush()
    return collection_settings(session)
