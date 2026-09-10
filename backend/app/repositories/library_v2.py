"""Small shared Library, with explicit manual/source layers and serialized writes."""

import re
from uuid import UUID, uuid4

import bleach
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.db.models.jobs import acquire_job_change_lock
from app.db.models.profiles import GameProfile
from app.schemas.library_v2 import (
    GameCreate,
    GameDetail,
    GameFields,
    GamePage,
    GamePatch,
    ReferenceWork,
    SourceIdentity,
    SteamRecommendationStatus,
    reference_key,
)


def _error(status: int, code: str, message: str) -> APIError:
    return APIError(status_code=status, code=code, message=message)


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def source_fields(profile: GameProfile) -> GameFields:
    facts = profile.current_facts or {}
    developers = facts.get("developers")
    developer = (
        ", ".join(x for x in developers if isinstance(x, str))
        if isinstance(developers, list)
        else _text(facts.get("developer"))
    )
    raw_languages = facts.get("supported_languages")
    languages = facts.get("languages", [])
    if isinstance(raw_languages, str):
        languages = re.split(r"[,;]", bleach.clean(raw_languages, tags=[], strip=True))
    values = {
        "name": _text(facts.get("name")),
        "website_url": _text(facts.get("website_url")) or _text(profile.canonical_url),
        "steam_app_id": profile.steam_app_id,
        "developer": developer,
        "description": _text(facts.get("short_description"))
        or _text(facts.get("description")),
        "tags": facts.get("tags", facts.get("genres", [])),
        "languages": languages,
        "release_date": _text(facts.get("release_date")),
        "cover_url": _text(facts.get("cover_image_url"))
        or _text(facts.get("header_image_url")),
    }
    # Source projections are best-effort. One missing/legacy field must not make
    # a valid stored game unreadable; manual input remains strictly validated.
    clean: dict = {}
    for key, value in values.items():
        try:
            clean[key] = GameFields.model_validate({key: value}).model_dump()[key]
        except ValidationError:
            continue
    return GameFields.model_validate(clean)


def effective_fields(profile: GameProfile) -> GameFields:
    return GameFields.model_validate(
        source_fields(profile).model_dump() | (profile.manual_overrides or {})
    )


def game_detail(profile: GameProfile) -> GameDetail:
    manual = profile.manual_overrides or {}
    return GameDetail(
        **effective_fields(profile).model_dump(),
        id=profile.id,
        revision=profile.manual_revision,
        favorite=profile.favorite,
        reference_works=profile.reference_works or [],
        steam_recommendations=SteamRecommendationStatus.model_validate(
            {
                key: value
                for key, value in (
                    (profile.source_status or {}).get("steam_recommendations") or {}
                ).items()
                if key in SteamRecommendationStatus.model_fields
            }
        ),
        source_fields=source_fields(profile),
        manual_overrides=manual,
        overridden_fields=sorted(manual),
        source_identity=SourceIdentity(
            steam_app_id=profile.steam_app_id,
            canonical_url=profile.canonical_url or None,
        ),
        last_analyzed_at=profile.last_analyzed_at,
        next_analysis_at=profile.next_analysis_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def effective_sort_name(profile: GameProfile) -> str:
    fields = effective_fields(profile)
    return (fields.name or fields.website_url or str(profile.id))[:255]


def _reference_values(works: list[ReferenceWork], existing: list[dict]) -> list[dict]:
    existing_by_id = {str(value["id"]): value for value in existing}
    existing_by_key = {
        reference_key(ReferenceWork.model_validate(value)): value["id"]
        for value in existing
    }
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    ids: set[str] = set()
    for work in works:
        key = reference_key(work)
        if key in seen:
            continue
        identifier = str(work.id or existing_by_key.get(key) or uuid4())
        if identifier in ids:
            raise _error(422, "request_invalid", "The request is invalid.")
        previous = existing_by_id.get(identifier, {})
        result.append(
            work.model_dump(mode="json")
            | {
                "id": identifier,
                "source": previous.get("source", "manual"),
                "source_url": previous.get("source_url"),
            }
        )
        seen.add(key)
        ids.add(identifier)
    return result


class LibraryGamesRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, game_id: UUID, *, for_update: bool = False) -> GameProfile:
        statement = select(GameProfile).where(GameProfile.id == game_id)
        if for_update:
            acquire_job_change_lock(self.session)
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        profile = self.session.scalar(statement)
        if profile is None:
            raise _error(404, "game_not_found", "The requested game was not found.")
        return profile

    def list(
        self,
        *,
        query: str,
        only_collection: bool,
        limit: int,
        offset: int,
        website_status="all",
        sort="name",
    ) -> GamePage:
        statement = select(GameProfile)
        if only_collection:
            statement = statement.where(GameProfile.favorite.is_(True))
        profiles = self.session.scalars(statement).all()
        query = query.strip().casefold()
        items = [game_detail(profile) for profile in profiles]
        if website_status != "all":
            items = [
                item
                for item in items
                if bool(item.website_url) == (website_status == "available")
            ]
        if query:
            items = [
                item
                for item in items
                if query
                in " ".join(
                    value or ""
                    for value in (
                        item.name,
                        item.developer,
                        item.steam_app_id,
                        item.website_url,
                    )
                ).casefold()
            ]
        from app.repositories.library_queries import game_sort_key

        items.sort(key=lambda item: game_sort_key(item, sort))
        return GamePage(
            items=items[offset : offset + limit],
            total=len(items),
            limit=limit,
            offset=offset,
        )

    def _require_unique_identity(
        self, steam_id: str | None, *, exclude_id: UUID | None = None
    ) -> None:
        if steam_id is None:
            return
        statement = select(GameProfile.id).where(
            or_(
                GameProfile.steam_app_id == steam_id,
                GameProfile.manual_overrides["steam_app_id"].astext == steam_id,
            )
        )
        if exclude_id is not None:
            statement = statement.where(GameProfile.id != exclude_id)
        if self.session.scalar(statement) is not None:
            raise _error(
                409,
                "game_identity_conflict",
                "This Steam identity already belongs to another game.",
            )

    def create(self, value: GameCreate) -> GameProfile:
        acquire_job_change_lock(self.session)
        self._require_unique_identity(value.steam_app_id)
        fields = value.model_dump(mode="json", exclude_unset=True)
        manual = {
            key: entry
            for key, entry in fields.items()
            if key in GameFields.model_fields
        }
        profile = GameProfile(
            id=uuid4(),
            steam_app_id=value.steam_app_id,
            canonical_url=(
                f"https://store.steampowered.com/app/{value.steam_app_id}"
                if value.steam_app_id
                else ""
            ),
            sort_name=(value.name or value.website_url or "")[:255],
            manual_overrides=manual,
            manual_revision=1,
            reference_works=_reference_values(value.reference_works, []),
            favorite=value.favorite,
            current_facts={},
            analysis={},
            brief={},
            source_status={},
        )
        self.session.add(profile)
        self.session.flush()
        return profile

    def patch(self, game_id: UUID, value: GamePatch) -> GameProfile:
        profile = self.get(game_id, for_update=True)
        if value.expected_revision != profile.manual_revision:
            raise _error(
                409,
                "game_revision_conflict",
                "This game was edited elsewhere. Reload before saving.",
            )
        fields = value.model_dump(mode="json", exclude_unset=True)
        manual = dict(profile.manual_overrides or {})
        for field in value.reset_fields:
            manual.pop(field, None)
        manual.update(
            {
                key: entry
                for key, entry in fields.items()
                if key in GameFields.model_fields
            }
        )
        effective = GameFields.model_validate(
            source_fields(profile).model_dump() | manual
        )
        if not effective.name and not effective.website_url:
            raise _error(422, "request_invalid", "The request is invalid.")
        self._require_unique_identity(effective.steam_app_id, exclude_id=profile.id)
        references = (
            _reference_values(value.reference_works, profile.reference_works or [])
            if "reference_works" in fields
            else profile.reference_works
        )
        profile.manual_overrides = manual
        if "reference_works" in fields:
            from app.repositories.steam_references import remember_reference_removals

            remember_reference_removals(profile, references)
        profile.reference_works = references
        if "favorite" in fields:
            profile.favorite = value.favorite
        profile.manual_revision += 1
        profile.sort_name = effective_sort_name(profile)
        self.session.flush()
        return profile
