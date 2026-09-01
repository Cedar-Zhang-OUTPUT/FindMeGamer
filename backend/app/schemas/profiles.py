import re
from datetime import datetime
from math import isfinite
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StrictStr,
    model_validator,
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


_non_alphanumeric = re.compile(r"[^a-z0-9]+")
_security_stem = re.compile(
    r"authorization|jwt|passw(?:or)?d|pwd|bearer|cookie|"
    r"secret|credential|token"
)
_auth_header_stem = re.compile(
    r"auth(?:entication|orization)?[a-z0-9]*headers?"
)
_qualified_key_stem = re.compile(
    r"(?:api|access|private|signing|encryption|auth(?:entication)?|session)"
    r"[a-z0-9]*keys?"
)
_session_credential_stem = re.compile(
    r"session[a-z0-9]*(?:ids?|data|values?|headers?)"
)
_restricted_context_stems = (
    "match",
    "private",
    "internal",
    "hidden",
    "backend",
    "numeric",
)
_contextual_metric_suffix = re.compile(
    r"(?:scores?|scoring|ranks?|ranking|orders?|ordering)$"
)
_public_json_fields = (
    "current_facts",
    "brief",
    "source_status",
    "analysis",
    "model_metadata",
    "prompt_metadata",
)


class _InvalidPublicJSON:
    def __repr__(self) -> str:
        return "<invalid public JSON>"


_invalid_public_json = _InvalidPublicJSON()


def public_json_object(value: object) -> PublicJSONObject:
    """Validate and project one public JSON object.

    Only actual JSON values are accepted. Security-bearing keys are removed
    recursively after case-folding and removal of non-alphanumeric separators.
    Security semantic stems are conservative and work for compact/plural forms.
    Score/rank/order suffixes are removed only when their key or an ancestor
    contains a match, private, hidden, internal, backend, or numeric stem.
    """
    if not isinstance(value, dict):
        raise ValueError("public profile JSON fields must be objects")
    projected = _public_json_value(value, path=())
    if not isinstance(projected, dict):
        raise ValueError("public profile JSON fields must be objects")
    return projected


def _public_json_value(
    value: object, *, path: tuple[str, ...]
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
            normalized_key = _normalized_public_key(raw_key)
            if _is_sensitive_public_key(normalized_key, path=path):
                continue
            projected[raw_key] = _public_json_value(
                item, path=(*path, normalized_key)
            )
        return projected
    raise ValueError("public profile JSON contains an unsupported value")


def _normalized_public_key(key: str) -> str:
    return _non_alphanumeric.sub("", key.casefold())


def _is_sensitive_public_key(
    normalized_key: str,
    *,
    path: tuple[str, ...],
) -> bool:
    if (
        _security_stem.search(normalized_key)
        or _auth_header_stem.search(normalized_key)
        or _qualified_key_stem.search(normalized_key)
        or _session_credential_stem.search(normalized_key)
    ):
        return True

    if not _contextual_metric_suffix.search(normalized_key):
        return False
    return any(
        stem in context_key
        for context_key in (*path, normalized_key)
        for stem in _restricted_context_stems
    )


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
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def project_and_redact_public_json(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        projected = dict(value)
        for field_name in _public_json_fields:
            if field_name not in projected:
                continue
            try:
                projected[field_name] = public_json_object(projected[field_name])
            except ValueError:
                projected[field_name] = _invalid_public_json
        return projected


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
