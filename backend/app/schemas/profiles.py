import re
from datetime import datetime
from math import isfinite
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


_camel_acronym_boundary = re.compile(r"([A-Z]+)([A-Z][a-z])")
_camel_word_boundary = re.compile(r"([a-z0-9])([A-Z])")
_key_separator = re.compile(r"[^A-Za-z0-9]+")
_security_segments = frozenset(
    {
        "authorization",
        "authentication",
        "jwt",
        "passwd",
        "password",
        "pwd",
        "bearer",
        "cookie",
        "cookies",
        "secret",
        "secrets",
        "credential",
        "credentials",
    }
)
_key_security_qualifiers = frozenset(
    {"api", "access", "private", "signing", "encryption", "auth"}
)
_session_credential_segments = frozenset(
    {"id", "key", "token", "cookie", "credential", "secret", "data", "value"}
)
_compact_security_keys = frozenset(
    {
        "apikey",
        "accesskey",
        "privatekey",
        "signingkey",
        "encryptionkey",
        "authkey",
        "authheader",
        "authheaders",
        "authorizationheader",
        "authorizationheaders",
        "sessionid",
        "sessionkey",
        "sessioncookie",
        "sessioncredential",
        "sessiondata",
        "sessionvalue",
        "tokenpayload",
        "tokendata",
        "tokenvalue",
        "tokenhash",
        "accesstoken",
        "refreshtoken",
        "authtoken",
        "bearertoken",
        "sessiontoken",
        "apitoken",
        "secrettoken",
        "passwordhash",
        "passwdhash",
        "pwdhash",
    }
)
_metric_context_segments = frozenset(
    {
        "match",
        "matches",
        "matching",
        "hidden",
        "private",
        "internal",
        "backend",
        "numeric",
    }
)
_metric_segments = frozenset(
    {
        "score",
        "scores",
        "scoring",
        "rank",
        "ranks",
        "ranking",
        "order",
        "orders",
        "ordering",
    }
)


def public_json_object(value: object) -> PublicJSONObject:
    """Validate and project one public JSON object.

    Only actual JSON values are accepted. Security-bearing keys are removed
    recursively. Score/rank/order fields are removed only when their key or an
    ancestor identifies a match, hidden, internal, backend, or numeric context.
    """
    if not isinstance(value, dict):
        raise ValueError("public profile JSON fields must be objects")
    projected = _public_json_value(value, path=())
    if not isinstance(projected, dict):
        raise ValueError("public profile JSON fields must be objects")
    return projected


def _public_json_value(
    value: object, *, path: tuple[tuple[str, ...], ...]
) -> PublicJSONValue:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("public profile JSON numbers must be finite")
        return value
    if isinstance(value, list):
        return [_public_json_value(item, path=path) for item in value]
    if isinstance(value, dict):
        projected: PublicJSONObject = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("public profile JSON object keys must be strings")
            key_segments = _public_key_segments(raw_key)
            if _is_sensitive_public_key(key_segments, path=path):
                continue
            projected[raw_key] = _public_json_value(
                item, path=(*path, key_segments)
            )
        return projected
    raise ValueError("public profile JSON contains an unsupported value")


def _public_key_segments(key: str) -> tuple[str, ...]:
    split_acronyms = _camel_acronym_boundary.sub(r"\1 \2", key)
    split_words = _camel_word_boundary.sub(r"\1 \2", split_acronyms)
    return tuple(
        segment.casefold()
        for segment in _key_separator.split(split_words)
        if segment
    )


def _is_sensitive_public_key(
    key_segments: tuple[str, ...],
    *,
    path: tuple[tuple[str, ...], ...],
) -> bool:
    segments = frozenset(key_segments)
    compact_key = "".join(key_segments)
    if compact_key in _compact_security_keys:
        return True
    if segments & _security_segments:
        return True
    if "token" in segments:
        return True
    if "key" in segments and segments & _key_security_qualifiers:
        return True
    if segments & {"header", "headers"} and segments & {
        "auth",
        "authorization",
    }:
        return True
    if "session" in segments and segments & _session_credential_segments:
        return True

    metric_key = bool(segments & _metric_segments)
    if not metric_key:
        return False
    context_segments = segments.union(
        *(frozenset(ancestor) for ancestor in path)
    )
    return bool(context_segments & _metric_context_segments)


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
