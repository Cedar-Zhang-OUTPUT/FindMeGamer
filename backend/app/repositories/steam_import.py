"""Publish objective Steam source without running or replacing AI analysis."""

from uuid import uuid4
from sqlalchemy import select
from app.api.routes.activity import _error
from app.db.models.profiles import GameProfile
from app.repositories.library_v2 import (
    LibraryGamesRepository,
    effective_sort_name,
    game_detail,
)
from app.schemas.profiles import public_json_object
from app.core.idempotency import utc_now
from app.repositories.steam_references import merge_steam_references


def import_target(session, value, app_id, *, for_update=False):
    repository = LibraryGamesRepository(session)
    selected = (
        repository.get(value.game_id, for_update=for_update) if value.game_id else None
    )
    if selected is not None:
        if selected.manual_revision != value.expected_revision:
            raise _error(
                409,
                "game_revision_conflict",
                "This game was edited elsewhere. Reload before importing.",
            )
        if selected.steam_app_id and selected.steam_app_id != app_id:
            raise _error(
                409,
                "game_source_identity_conflict",
                "This game already has a different Steam source. Import cannot change its identity.",
            )
    statement = select(GameProfile).where(GameProfile.steam_app_id == app_id)
    if for_update:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    existing = session.scalar(statement)
    if selected is not None and existing is not None and existing.id != selected.id:
        raise _error(
            409,
            "game_identity_conflict",
            "This Steam identity already belongs to another game.",
        )
    profile = selected if selected is not None else existing
    repository._require_unique_identity(
        app_id, exclude_id=profile.id if profile else None
    )
    return profile


def publish_source(session, value, source):
    profile = import_target(session, value, source.app_id, for_update=True)
    if profile is None:
        profile = GameProfile(
            id=uuid4(),
            steam_app_id=source.app_id,
            canonical_url=source.canonical_url,
            sort_name=source.name[:255],
            manual_revision=0,
            manual_overrides={},
            reference_works=[],
            analysis={},
            brief={},
            current_facts={},
            source_status={},
        )
        session.add(profile)
    profile.steam_app_id = source.app_id
    profile.canonical_url = source.canonical_url
    profile.current_facts = public_json_object(
        source.model_dump(mode="json", exclude={"raw"})
    )
    profile.source_status = {
        **(profile.source_status or {}),
        "steam": "available",
        "steam_imported_at": utc_now().isoformat(),
    }
    merge_steam_references(profile, source.steam_recommendations)
    profile.manual_revision += 1
    profile.sort_name = effective_sort_name(profile)
    session.flush()
    return game_detail(profile).model_dump(mode="json")
