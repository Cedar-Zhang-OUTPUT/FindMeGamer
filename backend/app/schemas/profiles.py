import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
)


type PublicJSONValue = (
    str
    | int
    | float
    | bool
    | None
    | list[PublicJSONValue]
    | dict[str, PublicJSONValue]
)
type PublicJSONObject = dict[str, PublicJSONValue]


_key_separator = re.compile(r"[^a-z0-9]+")
_sensitive_key_markers = (
    "secret",
    "password",
    "credential",
    "apikey",
    "accesskey",
    "privatekey",
    "signingkey",
    "encryptionkey",
)
_sensitive_token_markers = (
    "accesstoken",
    "refreshtoken",
    "authtoken",
    "bearertoken",
    "sessiontoken",
    "apitoken",
    "secrettoken",
    "tokenhash",
    "tokenvalue",
)
_match_numeric_keys = frozenset(
    {"score", "rank", "totalscore", "numericscore", "backendorder"}
)


def public_json_object(value: object) -> PublicJSONObject:
    if not isinstance(value, dict):
        return {}
    projected = _public_json_value(value, path=())
    return projected if isinstance(projected, dict) else {}


def _public_json_value(
    value: object, *, path: tuple[str, ...]
) -> PublicJSONValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_public_json_value(item, path=path) for item in value]
    if isinstance(value, dict):
        projected: PublicJSONObject = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                continue
            normalized_key = _normalize_public_key(raw_key)
            if _is_sensitive_public_key(normalized_key, path=path):
                continue
            projected[raw_key] = _public_json_value(
                item, path=(*path, normalized_key)
            )
        return projected
    return str(value)


def _normalize_public_key(key: str) -> str:
    return _key_separator.sub("", key.casefold())


def _is_sensitive_public_key(
    normalized_key: str, *, path: tuple[str, ...]
) -> bool:
    if any(marker in normalized_key for marker in _sensitive_key_markers):
        return True
    if normalized_key.endswith("token") or any(
        marker in normalized_key for marker in _sensitive_token_markers
    ):
        return True
    numeric_marker = any(
        marker in normalized_key for marker in ("scor", "rank", "order")
    )
    if numeric_marker and any(
        marker in normalized_key
        for marker in ("hidden", "internal", "match", "backend", "numeric")
    ):
        return True
    if normalized_key in _match_numeric_keys:
        return True
    inside_match_payload = any("match" in ancestor for ancestor in path)
    return inside_match_payload and numeric_marker


class FavoriteUpdate(BaseModel):
    favorite: StrictBool


class CreatorManualUpdate(BaseModel):
    contact_email: EmailStr | None
    notes: Annotated[StrictStr, Field(max_length=20_000)] | None


class CreatorContactResponse(BaseModel):
    email: str
    source: str
    source_url: str | None
    validation_state: str


class PublicProfileResponse(BaseModel):
    @field_validator(
        "current_facts",
        "brief",
        "source_status",
        "analysis",
        "model_metadata",
        "prompt_metadata",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def remove_sensitive_json_keys(cls, value: object) -> PublicJSONObject:
        return public_json_object(value)


class GameProfileCard(PublicProfileResponse):
    type: Literal["game"] = "game"
    id: UUID
    name: str
    steam_app_id: str
    canonical_url: str
    favorite: bool
    current_facts: PublicJSONObject
    brief: PublicJSONObject
    source_status: PublicJSONObject
    last_analyzed_at: datetime | None
    next_analysis_at: datetime | None


class CreatorProfileCard(PublicProfileResponse):
    type: Literal["creator"] = "creator"
    id: UUID
    name: str
    youtube_channel_id: str
    canonical_url: str
    favorite: bool
    current_facts: PublicJSONObject
    brief: PublicJSONObject
    source_status: PublicJSONObject
    last_analyzed_at: datetime | None
    next_analysis_at: datetime | None
    contact: CreatorContactResponse | None


class GameProfileDetail(GameProfileCard):
    analysis: PublicJSONObject
    model_metadata: PublicJSONObject
    prompt_metadata: PublicJSONObject


class CreatorProfileDetail(CreatorProfileCard):
    analysis: PublicJSONObject
    model_metadata: PublicJSONObject
    prompt_metadata: PublicJSONObject
    manual_notes: str | None
