import base64
import binascii
import json
from collections.abc import Callable, Sequence
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.errors import APIError
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.repositories.profiles import CursorValue, ProfilesRepository
from app.schemas.common import CursorPage
from app.schemas.profiles import (
    CreatorContactResponse,
    CreatorManualUpdate,
    CreatorProfileCard,
    CreatorProfileDetail,
    FavoriteUpdate,
    GameProfileCard,
    GameProfileDetail,
)


PROFILE_TYPES = frozenset({"games", "creators"})


def _unknown_profile_type() -> APIError:
    return APIError(
        status_code=404,
        code="profile_type_unknown",
        message="The requested profile type is not supported.",
    )


def _require_profile_type(profile_type: str) -> str:
    if profile_type not in PROFILE_TYPES:
        raise _unknown_profile_type()
    return profile_type


def _profile_not_found() -> APIError:
    return APIError(
        status_code=404,
        code="profile_not_found",
        message="The requested profile was not found.",
    )


def _invalid_cursor() -> APIError:
    return APIError(
        status_code=400,
        code="profile_cursor_invalid",
        message="The profile cursor is invalid.",
    )


def _encode_cursor(sort_name: str, profile_id: UUID) -> str:
    raw = json.dumps(
        [sort_name, str(profile_id)], separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> CursorValue | None:
    if cursor is None:
        return None
    if not cursor or len(cursor) > 2048:
        raise _invalid_cursor()
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not isinstance(value[0], str)
            or not value[0]
            or len(value[0]) > 255
            or not isinstance(value[1], str)
        ):
            raise ValueError("invalid cursor shape")
        profile_id = UUID(value[1])
        if str(profile_id) != value[1]:
            raise ValueError("non-canonical UUID")
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _invalid_cursor() from None
    return value[0], profile_id


def _contains_stale_status(value: Any) -> bool:
    if isinstance(value, str):
        return value.casefold() == "stale"
    if isinstance(value, dict):
        return any(_contains_stale_status(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_stale_status(item) for item in value)
    return False


def _selected_contact(creator: CreatorProfile) -> CreatorContactResponse | None:
    active = [contact for contact in creator.contacts if contact.is_active]
    manual = sorted(
        (contact for contact in active if contact.is_manual),
        key=lambda contact: (contact.created_at, str(contact.id)),
    )
    if manual:
        selected = manual[0]
        source = "manual"
    else:
        validation_rank = {
            "verified": 3,
            "valid": 2,
            "unverified": 1,
            "invalid": 0,
        }
        discovered = sorted(
            (contact for contact in active if not contact.is_manual),
            key=lambda contact: (
                -contact.priority,
                -validation_rank.get(contact.validation_state.casefold(), -1),
                contact.created_at,
                str(contact.id),
            ),
        )
        if not discovered:
            return None
        selected = discovered[0]
        source = selected.source_type
    return CreatorContactResponse(
        email=selected.email,
        source=source,
        source_url=selected.source_url,
        validation_state=selected.validation_state,
    )


def _game_card(profile: GameProfile) -> GameProfileCard:
    return GameProfileCard(
        id=profile.id,
        name=profile.sort_name,
        steam_app_id=profile.steam_app_id,
        canonical_url=profile.canonical_url,
        favorite=profile.favorite,
        current_facts=profile.current_facts,
        brief=profile.brief,
        source_status=profile.source_status,
        last_analyzed_at=profile.last_analyzed_at,
        next_analysis_at=profile.next_analysis_at,
    )


def _game_detail(profile: GameProfile) -> GameProfileDetail:
    return GameProfileDetail(
        **_game_card(profile).model_dump(),
        analysis=profile.analysis,
        model_metadata=profile.model_metadata,
        prompt_metadata=profile.prompt_metadata,
    )


def _creator_card(profile: CreatorProfile) -> CreatorProfileCard:
    current_facts = (
        {} if _contains_stale_status(profile.source_status) else profile.current_facts
    )
    return CreatorProfileCard(
        id=profile.id,
        name=profile.sort_name,
        youtube_channel_id=profile.youtube_channel_id,
        canonical_url=profile.canonical_url,
        favorite=profile.favorite,
        current_facts=current_facts,
        brief=profile.brief,
        source_status=profile.source_status,
        last_analyzed_at=profile.last_analyzed_at,
        next_analysis_at=profile.next_analysis_at,
        contact=_selected_contact(profile),
    )


def _creator_detail(profile: CreatorProfile) -> CreatorProfileDetail:
    return CreatorProfileDetail(
        **_creator_card(profile).model_dump(),
        analysis=profile.analysis,
        model_metadata=profile.model_metadata,
        prompt_metadata=profile.prompt_metadata,
        manual_notes=profile.manual_notes,
    )


def _next_cursor(
    rows: Sequence[GameProfile] | Sequence[CreatorProfile], *, has_more: bool
) -> str | None:
    if not has_more or not rows:
        return None
    last = rows[-1]
    return _encode_cursor(last.sort_name, last.id)


def _validated_cursor(
    repository: ProfilesRepository,
    profile_type: str,
    raw_cursor: str | None,
    *,
    query: str,
    only_collection: bool,
) -> CursorValue | None:
    cursor = _decode_cursor(raw_cursor)
    if cursor is not None and not repository.cursor_matches(
        profile_type,
        cursor,
        query=query,
        only_collection=only_collection,
    ):
        raise _invalid_cursor()
    return cursor


def create_router(authenticate_workspace: Callable) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/profiles",
        tags=["profiles"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get("/games", response_model=CursorPage[GameProfileCard])
    def list_games(
        query: Annotated[str, Query(max_length=255)] = "",
        only_collection: bool = False,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        database_session: Session = Depends(get_session),
    ) -> CursorPage[GameProfileCard]:
        repository = ProfilesRepository(database_session)
        decoded_cursor = _validated_cursor(
            repository,
            "games",
            cursor,
            query=query,
            only_collection=only_collection,
        )
        rows, has_more = repository.list_games(
            query=query,
            only_collection=only_collection,
            cursor=decoded_cursor,
            limit=limit,
        )
        return CursorPage(
            items=[_game_card(profile) for profile in rows],
            next_cursor=_next_cursor(rows, has_more=has_more),
        )

    @router.get("/creators", response_model=CursorPage[CreatorProfileCard])
    def list_creators(
        query: Annotated[str, Query(max_length=255)] = "",
        only_collection: bool = False,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        database_session: Session = Depends(get_session),
    ) -> CursorPage[CreatorProfileCard]:
        repository = ProfilesRepository(database_session)
        decoded_cursor = _validated_cursor(
            repository,
            "creators",
            cursor,
            query=query,
            only_collection=only_collection,
        )
        rows, has_more = repository.list_creators(
            query=query,
            only_collection=only_collection,
            cursor=decoded_cursor,
            limit=limit,
        )
        return CursorPage(
            items=[_creator_card(profile) for profile in rows],
            next_cursor=_next_cursor(rows, has_more=has_more),
        )

    @router.patch(
        "/creators/{profile_id}/manual", response_model=CreatorProfileDetail
    )
    def update_creator_manual(
        profile_id: UUID,
        update: CreatorManualUpdate,
        database_session: Session = Depends(get_session),
    ) -> CreatorProfileDetail:
        creator = ProfilesRepository(database_session).update_creator_manual(
            profile_id,
            contact_email=str(update.contact_email) if update.contact_email else None,
            notes=update.notes,
        )
        if creator is None:
            raise _profile_not_found()
        database_session.commit()
        return _creator_detail(creator)

    @router.get(
        "/{profile_type}/{profile_id}",
        response_model=GameProfileDetail | CreatorProfileDetail,
    )
    def read_profile(
        profile_type: Annotated[str, Depends(_require_profile_type)],
        profile_id: UUID,
        database_session: Session = Depends(get_session),
    ) -> GameProfileDetail | CreatorProfileDetail:
        repository = ProfilesRepository(database_session)
        if profile_type == "games":
            game = repository.get_game(profile_id)
            if game is None:
                raise _profile_not_found()
            return _game_detail(game)
        if profile_type == "creators":
            creator = repository.get_creator(profile_id)
            if creator is None:
                raise _profile_not_found()
            return _creator_detail(creator)
        raise _unknown_profile_type()

    @router.patch(
        "/{profile_type}/{profile_id}/favorite",
        response_model=GameProfileCard | CreatorProfileCard,
    )
    def set_favorite(
        profile_type: Annotated[str, Depends(_require_profile_type)],
        profile_id: UUID,
        update: FavoriteUpdate,
        database_session: Session = Depends(get_session),
    ) -> GameProfileCard | CreatorProfileCard:
        repository = ProfilesRepository(database_session)
        if profile_type == "games":
            game = repository.set_game_favorite(
                profile_id, favorite=update.favorite
            )
            if game is None:
                raise _profile_not_found()
            database_session.commit()
            return _game_card(game)
        if profile_type == "creators":
            creator = repository.set_creator_favorite(
                profile_id, favorite=update.favorite
            )
            if creator is None:
                raise _profile_not_found()
            database_session.commit()
            return _creator_card(creator)
        raise _unknown_profile_type()

    @router.get("/{profile_type}")
    def reject_unknown_list_type(profile_type: str) -> None:
        raise _unknown_profile_type()

    return router
