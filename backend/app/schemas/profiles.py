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
    WithJsonSchema,
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
type PublicJSONObject = Annotated[
    dict[str, PublicJSONValue],
    WithJsonSchema({"type": "object", "additionalProperties": True}),
]


# Public profile JSON is deliberately smaller than arbitrary JSON so response
# work remains bounded even when persisted source data is unexpectedly large.
PUBLIC_JSON_MAX_KEY_LENGTH = 512
PUBLIC_JSON_MAX_DEPTH = 32
PUBLIC_JSON_MAX_NODES = 10_000
PUBLIC_JSON_MAX_KEYS = 2_000

_security_material_words = frozenset(
    {
        "authorization",
        "jwt",
        "passwd",
        "password",
        "pwd",
        "bearer",
        "cookie",
        "secret",
        "credential",
        "token",
    }
)
_key_qualifier_words = frozenset(
    {
        "api",
        "access",
        "private",
        "signing",
        "encryption",
        "auth",
        "authentication",
        "session",
    }
)
_session_object_words = frozenset({"id", "data", "value", "header"})
_restricted_context_words = frozenset(
    {"match", "private", "internal", "hidden", "backend", "numeric"}
)
_contextual_metric_words = frozenset(
    {"score", "scoring", "rank", "ranking", "order", "ordering"}
)
_semantic_vocabulary = frozenset(
    _security_material_words
    | _key_qualifier_words
    | _session_object_words
    | _restricted_context_words
    | _contextual_metric_words
    | {
        "result",
        "key",
        "total",
        "display",
        "primary",
        "request",
        "client",
        "service",
        "refresh",
        "payload",
        "hash",
    }
)


def _word_forms(word: str) -> tuple[str, ...]:
    # Only exact singular/plural forms are semantic. Sharing a prefix with a
    # security concept never classifies an otherwise unknown word.
    return (word, f"{word}s")


_semantic_word_forms = {
    form: word
    for word in _semantic_vocabulary
    for form in _word_forms(word)
}
_compact_word_forms = tuple(
    sorted(_semantic_word_forms, key=lambda form: (-len(form), form))
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

    Validation traverses the complete raw tree before projection, including
    values beneath keys which will later be removed. Only actual finite JSON
    values within fixed key/depth/node budgets are accepted, and cycles fail.

    Projection tokenizes explicit separators and camel/Pascal/acronym
    boundaries. A separator-free compound is classified only when its entire
    token can be segmented into the fixed semantic vocabulary. This preserves
    near-miss words such as ``secretary`` and ``matchbox`` while recognizing
    compact semantics such as ``tokenpayload`` and ``matchscore`` in bounded
    O(key length * fixed vocabulary) work.
    """
    if not isinstance(value, dict):
        raise ValueError("public profile JSON fields must be objects")
    _validate_public_json(value)
    projected = _project_public_json(value, restricted_context=False)
    if not isinstance(projected, dict):
        raise ValueError("public profile JSON fields must be objects")
    return projected


def _validate_public_json(value: object) -> None:
    nodes = 0
    keys = 0
    active_containers: set[int] = set()

    def visit(item: object, *, depth: int) -> None:
        nonlocal nodes, keys
        nodes += 1
        if nodes > PUBLIC_JSON_MAX_NODES:
            raise ValueError("public profile JSON exceeds the node budget")
        if depth > PUBLIC_JSON_MAX_DEPTH:
            raise ValueError("public profile JSON exceeds the depth budget")

        if item is None or isinstance(item, str | bool | int):
            return
        if isinstance(item, float):
            if not isfinite(item):
                raise ValueError("public profile JSON numbers must be finite")
            return
        if not isinstance(item, list | dict):
            raise ValueError("public profile JSON contains an unsupported value")

        container_id = id(item)
        if container_id in active_containers:
            raise ValueError("public profile JSON contains a cycle")
        active_containers.add(container_id)
        try:
            if isinstance(item, list):
                for child in item:
                    visit(child, depth=depth + 1)
                return

            for raw_key, child in item.items():
                keys += 1
                if keys > PUBLIC_JSON_MAX_KEYS:
                    raise ValueError("public profile JSON exceeds the key budget")
                if not isinstance(raw_key, str):
                    raise ValueError(
                        "public profile JSON object keys must be strings"
                    )
                if len(raw_key) > PUBLIC_JSON_MAX_KEY_LENGTH:
                    raise ValueError(
                        "public profile JSON object key exceeds the length budget"
                    )
                visit(child, depth=depth + 1)
        finally:
            active_containers.remove(container_id)

    visit(value, depth=0)


def _project_public_json(
    value: object, *, restricted_context: bool
) -> PublicJSONValue:
    # Structural types have already been checked by _validate_public_json.
    if value is None or isinstance(value, str | bool | int | float):
        return value  # type: ignore[return-value]
    if isinstance(value, list):
        return [
            _project_public_json(item, restricted_context=restricted_context)
            for item in value
        ]
    if isinstance(value, dict):
        projected: PublicJSONObject = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):  # pragma: no cover - invariant
                raise ValueError("public profile JSON object keys must be strings")
            words = _semantic_words(raw_key)
            if _is_security_key(words):
                continue
            child_restricted = restricted_context or bool(
                _restricted_context_words.intersection(words)
            )
            if child_restricted and _contextual_metric_words.intersection(words):
                continue
            projected[raw_key] = _project_public_json(
                item,
                restricted_context=child_restricted,
            )
        return projected
    raise ValueError("public profile JSON contains an unsupported value")


def _semantic_words(key: str) -> tuple[str, ...]:
    return tuple(
        semantic_word
        for raw_token in _key_tokens(key)
        for semantic_word in _segment_semantic_token(raw_token)
    )


def _key_tokens(key: str) -> tuple[str, ...]:
    tokens: list[str] = []
    current: list[str] = []

    for index, character in enumerate(key):
        if not character.isalnum():
            if current:
                tokens.append("".join(current).casefold())
                current = []
            continue

        previous = key[index - 1] if index else ""
        following = key[index + 1] if index + 1 < len(key) else ""
        camel_boundary = bool(
            current
            and character.isupper()
            and (
                previous.islower()
                or previous.isdigit()
                or (previous.isupper() and following.islower())
            )
        )
        if camel_boundary:
            tokens.append("".join(current).casefold())
            current = []
        current.append(character)

    if current:
        tokens.append("".join(current).casefold())
    return tuple(tokens)


def _segment_semantic_token(token: str) -> tuple[str, ...]:
    exact = _semantic_word_forms.get(token)
    if exact is not None:
        return (exact,)

    # Full-token dynamic programming: prefix matches never classify a key. The
    # vocabulary is fixed and key length was bounded during validation.
    predecessors: list[tuple[int, str] | None] = [None] * (len(token) + 1)
    reachable = [False] * (len(token) + 1)
    reachable[0] = True
    for start in range(len(token)):
        if not reachable[start]:
            continue
        for form in _compact_word_forms:
            if token.startswith(form, start):
                end = start + len(form)
                if not reachable[end]:
                    reachable[end] = True
                    predecessors[end] = (start, _semantic_word_forms[form])

    if not reachable[-1]:
        return (token,)
    reversed_words: list[str] = []
    end = len(token)
    while end:
        predecessor = predecessors[end]
        if predecessor is None:  # pragma: no cover - reachability invariant
            return (token,)
        end, word = predecessor
        reversed_words.append(word)
    return tuple(reversed(reversed_words))


def _is_security_key(words: tuple[str, ...]) -> bool:
    word_set = frozenset(words)
    if _security_material_words.intersection(word_set):
        return True
    if "header" in word_set and {"auth", "authentication"}.intersection(word_set):
        return True
    if "key" in word_set and _key_qualifier_words.intersection(word_set):
        return True
    return "session" in word_set and bool(
        _session_object_words.intersection(word_set)
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
