import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Callable, Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.errors import APIError
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.repositories.profiles import CursorValue, ProfilesRepository
from app.schemas.profile_editing import ProfileEditDocument, ProfileEditPatch
from app.services.profile_editing import (
    apply_edit,
    edit_document,
    effective_name,
    effective_section,
)
from app.services.profile_source_visibility import _creator_youtube_is_stale
from app.schemas.common import CursorPage
from app.schemas.profiles import (
    CreatorContactResponse,
    CreatorManualUpdate,
    CreatorProfileCard,
    CreatorProfileDetail,
    FavoriteUpdate,
    GameProfileCard,
    GameProfileDetail,
    public_json_object,
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


def _cursor_scope(
    profile_type: str, *, query: str, only_collection: bool
) -> dict[str, str | bool]:
    return {
        "profile_type": profile_type,
        "query": query.strip().casefold(),
        "only_collection": only_collection,
    }


def _cursor_signature(payload: dict[str, object], *, signing_key: bytes) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hmac.new(signing_key, canonical, hashlib.sha256).hexdigest()


def _encode_cursor(
    sort_name: str,
    profile_id: UUID,
    *,
    profile_type: str,
    query: str,
    only_collection: bool,
    signing_key: bytes,
) -> str:
    signed_payload: dict[str, object] = {
        "v": 1,
        "key": [sort_name, str(profile_id)],
        "scope": _cursor_scope(
            profile_type, query=query, only_collection=only_collection
        ),
    }
    payload = {
        **signed_payload,
        "signature": _cursor_signature(signed_payload, signing_key=signing_key),
    }
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None,
    *,
    profile_type: str,
    query: str,
    only_collection: bool,
    signing_key: bytes,
) -> CursorValue | None:
    if cursor is None:
        return None
    if not cursor or len(cursor) > 2048:
        raise _invalid_cursor()
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(value, dict)
            or set(value) != {"v", "key", "scope", "signature"}
            or type(value["v"]) is not int
            or value["v"] != 1
            or not isinstance(value["key"], list)
            or len(value["key"]) != 2
            or not isinstance(value["key"][0], str)
            or not value["key"][0]
            or len(value["key"][0]) > 255
            or not isinstance(value["key"][1], str)
            or not isinstance(value["scope"], dict)
            or not isinstance(value["signature"], str)
        ):
            raise ValueError("invalid cursor shape")
        expected_scope = _cursor_scope(
            profile_type, query=query, only_collection=only_collection
        )
        if value["scope"] != expected_scope:
            raise ValueError("cursor scope mismatch")
        signed_payload = {
            "v": value["v"],
            "key": value["key"],
            "scope": value["scope"],
        }
        expected_signature = _cursor_signature(signed_payload, signing_key=signing_key)
        if not hmac.compare_digest(value["signature"], expected_signature):
            raise ValueError("cursor signature mismatch")
        profile_id = UUID(value["key"][1])
        if str(profile_id) != value["key"][1]:
            raise ValueError("non-canonical UUID")
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _invalid_cursor() from None
    return value["key"][0], profile_id


def _available_contacts(
    creator: CreatorProfile, *, manual_only: bool = False
) -> list[CreatorContactResponse]:
    active = [contact for contact in creator.contacts if contact.is_active]
    if manual_only:
        active = [contact for contact in active if contact.is_manual]
    validation_rank = {
        "verified": 3,
        "valid": 2,
        "unverified": 1,
        "invalid": 0,
    }
    ordered = sorted(
        active,
        key=lambda contact: (
            0 if contact.is_manual else 1,
            -contact.priority,
            -validation_rank.get(contact.validation_state.casefold(), -1),
            contact.created_at,
            str(contact.id),
        ),
    )
    projected: list[CreatorContactResponse] = []
    seen: set[str] = set()
    for contact in ordered:
        email_key = contact.email.casefold()
        if email_key in seen:
            continue
        seen.add(email_key)
        projected.append(
            CreatorContactResponse(
                email=contact.email,
                purpose=contact.purpose,
                source="manual" if contact.is_manual else contact.source_type,
                source_url=contact.source_url,
                validation_state=contact.validation_state,
            )
        )
    return projected


def _game_card(profile: GameProfile) -> GameProfileCard:
    return GameProfileCard(
        id=profile.id,
        name=effective_name(profile),
        profile_revision=profile.profile_revision,
        manual_overrides=profile.manual_overrides,
        steam_app_id=profile.steam_app_id,
        canonical_url=profile.canonical_url,
        favorite=profile.favorite,
        current_facts=public_json_object(effective_section(profile, "facts")),
        brief=public_json_object(effective_section(profile, "brief")),
        source_status=public_json_object(profile.source_status),
        last_analyzed_at=profile.last_analyzed_at,
        next_analysis_at=profile.next_analysis_at,
    )


def _game_detail(profile: GameProfile) -> GameProfileDetail:
    return GameProfileDetail(
        **_game_card(profile).model_dump(),
        analysis=public_json_object(effective_section(profile, "analysis")),
        model_metadata=public_json_object(profile.model_metadata),
        prompt_metadata=public_json_object(profile.prompt_metadata),
    )


def _creator_card(profile: CreatorProfile) -> CreatorProfileCard:
    stale = _creator_youtube_is_stale(profile.source_status)
    contacts = _available_contacts(profile, manual_only=stale)
    current_facts = effective_section(profile, "facts", source_visible=not stale)
    brief = effective_section(profile, "brief", source_visible=not stale)
    return CreatorProfileCard(
        id=profile.id,
        name=effective_name(profile),
        profile_revision=profile.profile_revision,
        manual_overrides=profile.manual_overrides,
        youtube_channel_id=profile.youtube_channel_id,
        canonical_url=profile.canonical_url,
        favorite=profile.favorite,
        current_facts=public_json_object(current_facts),
        brief=public_json_object(brief),
        source_status=public_json_object(profile.source_status),
        last_analyzed_at=profile.last_analyzed_at,
        next_analysis_at=profile.next_analysis_at,
        contact=contacts[0] if contacts else None,
        contacts=contacts,
    )


def _creator_detail(profile: CreatorProfile) -> CreatorProfileDetail:
    analysis = effective_section(
        profile,
        "analysis",
        source_visible=not _creator_youtube_is_stale(profile.source_status),
    )
    return CreatorProfileDetail(
        **_creator_card(profile).model_dump(),
        analysis=public_json_object(analysis),
        model_metadata=public_json_object(profile.model_metadata),
        prompt_metadata=public_json_object(profile.prompt_metadata),
        manual_notes=profile.manual_notes,
    )


def _next_cursor(
    rows: Sequence[GameProfile] | Sequence[CreatorProfile],
    *,
    has_more: bool,
    profile_type: str,
    query: str,
    only_collection: bool,
    signing_key: bytes,
) -> str | None:
    if not has_more or not rows:
        return None
    last = rows[-1]
    return _encode_cursor(
        last.sort_name,
        last.id,
        profile_type=profile_type,
        query=query,
        only_collection=only_collection,
        signing_key=signing_key,
    )


def _validated_cursor(
    repository: ProfilesRepository,
    profile_type: str,
    raw_cursor: str | None,
    *,
    query: str,
    only_collection: bool,
    signing_key: bytes,
) -> CursorValue | None:
    cursor = _decode_cursor(
        raw_cursor,
        profile_type=profile_type,
        query=query,
        only_collection=only_collection,
        signing_key=signing_key,
    )
    if cursor is not None and not repository.cursor_matches(
        profile_type,
        cursor,
        query=query,
        only_collection=only_collection,
    ):
        raise _invalid_cursor()
    return cursor


def create_router(
    authenticate_workspace: Callable, *, cursor_signing_secret: str
) -> APIRouter:
    cursor_signing_key = hashlib.sha256(
        b"find-me-gamer/profile-cursor/v1\0" + cursor_signing_secret.encode("utf-8")
    ).digest()
    router = APIRouter(
        prefix="/api/v1/profiles",
        tags=["profiles"],
        dependencies=[Depends(authenticate_workspace)],
    )

    def editable_profile(profile_type, profile_id, session, *, lock=False):
        if profile_type not in {"game", "creator"}:
            raise _unknown_profile_type()
        profile = ProfilesRepository(session).get_for_edit(
            profile_type, profile_id, lock=lock
        )
        if profile is None:
            raise _profile_not_found()
        return profile

    @router.get(
        "/{profile_type}/{profile_id}/edit",
        response_model=ProfileEditDocument,
        operation_id="getProfileEdit",
    )
    def get_profile_edit(
        profile_type: str,
        profile_id: UUID,
        database_session: Session = Depends(get_session),
    ):
        return edit_document(
            editable_profile(profile_type, profile_id, database_session)
        )

    @router.patch(
        "/{profile_type}/{profile_id}/edit",
        response_model=ProfileEditDocument,
        operation_id="updateProfileEdit",
    )
    def update_profile_edit(
        profile_type: str,
        profile_id: UUID,
        patch: ProfileEditPatch,
        database_session: Session = Depends(get_session),
    ):
        profile = editable_profile(
            profile_type, profile_id, database_session, lock=True
        )
        result = apply_edit(profile, patch)
        database_session.commit()
        return result

    @router.get(
        "/games",
        response_model=CursorPage[GameProfileCard],
        operation_id="listGameProfiles",
    )
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
            signing_key=cursor_signing_key,
        )
        rows, has_more = repository.list_games(
            query=query,
            only_collection=only_collection,
            cursor=decoded_cursor,
            limit=limit,
        )
        return CursorPage(
            items=[_game_card(profile) for profile in rows],
            next_cursor=_next_cursor(
                rows,
                has_more=has_more,
                profile_type="games",
                query=query,
                only_collection=only_collection,
                signing_key=cursor_signing_key,
            ),
        )

    @router.get(
        "/creators",
        response_model=CursorPage[CreatorProfileCard],
        operation_id="listCreatorProfiles",
    )
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
            signing_key=cursor_signing_key,
        )
        rows, has_more = repository.list_creators(
            query=query,
            only_collection=only_collection,
            cursor=decoded_cursor,
            limit=limit,
        )
        return CursorPage(
            items=[_creator_card(profile) for profile in rows],
            next_cursor=_next_cursor(
                rows,
                has_more=has_more,
                profile_type="creators",
                query=query,
                only_collection=only_collection,
                signing_key=cursor_signing_key,
            ),
        )

    @router.patch(
        "/creators/{profile_id}/manual",
        response_model=CreatorProfileDetail,
        operation_id="updateCreatorManual",
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
        operation_id="getProfile",
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
        operation_id="setProfileFavorite",
    )
    def set_favorite(
        profile_type: Annotated[str, Depends(_require_profile_type)],
        profile_id: UUID,
        update: FavoriteUpdate,
        database_session: Session = Depends(get_session),
    ) -> GameProfileCard | CreatorProfileCard:
        repository = ProfilesRepository(database_session)
        if profile_type == "games":
            game = repository.set_game_favorite(profile_id, favorite=update.favorite)
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

    @router.get("/{profile_type}", operation_id="rejectUnknownProfileType")
    def reject_unknown_list_type(profile_type: str) -> None:
        raise _unknown_profile_type()

    return router
