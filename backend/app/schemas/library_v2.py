"""Editable game fields are distinct from immutable acquisition identity."""

import re
from datetime import datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.schemas.profiles import PublicJSONObject


def _blank_to_none(value: object) -> object:
    return value.strip() or None if isinstance(value, str) else value


def _http_url(value: str | None) -> str | None:
    if value is None:
        return None
    url = TypeAdapter(AnyHttpUrl).validate_python(value)
    if url.username is not None or url.password is not None:
        raise ValueError("URL credentials are not allowed")
    return str(url)


ShortText = Annotated[
    StrictStr | None, Field(max_length=255), BeforeValidator(_blank_to_none)
]
LongText = Annotated[
    StrictStr | None, Field(max_length=20000), BeforeValidator(_blank_to_none)
]
WebURL = Annotated[
    StrictStr | None,
    Field(max_length=2048),
    BeforeValidator(_blank_to_none),
    AfterValidator(_http_url),
]
SteamID = Annotated[
    StrictStr | None,
    Field(pattern=r"^[1-9][0-9]{0,19}$"),
    BeforeValidator(_blank_to_none),
]
Labels = Annotated[
    list[Annotated[StrictStr, Field(min_length=1, max_length=255)]],
    Field(max_length=100),
]


class GameFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ShortText = None
    website_url: WebURL = None
    steam_app_id: SteamID = None
    developer: ShortText = None
    description: LongText = None
    tags: Labels = Field(default_factory=list)
    languages: Labels = Field(default_factory=list)
    release_date: ShortText = None
    cover_url: WebURL = None

    @field_validator("tags", "languages", mode="after")
    @classmethod
    def clean_labels(cls, values: list[str]) -> list[str]:
        return unique_labels(values)


def unique_labels(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        if value and value.casefold() not in seen:
            result.append(value)
            seen.add(value.casefold())
    return result


class ReferenceWork(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    name: ShortText = None
    url: WebURL = None
    similarities: Labels = Field(default_factory=list)
    reason: LongText = None

    @model_validator(mode="after")
    def require_identity(self) -> Self:
        if not self.name and not self.url:
            raise ValueError("A reference needs a name or URL")
        self.similarities = unique_labels(self.similarities)
        return self


def reference_key(work: ReferenceWork) -> tuple[str, str]:
    if work.url:
        parts = urlsplit(work.url)
        if parts.hostname in {"store.steampowered.com", "www.store.steampowered.com"}:
            match = re.match(r"^/app/([1-9][0-9]*)(?:/|$)", parts.path)
            if match:
                return "steam", match[1]
        return (
            "url",
            f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}?{parts.query}",
        )
    return "name", (work.name or "").casefold()


References = Annotated[list[ReferenceWork], Field(max_length=100)]
GameFieldName = Literal[
    "name",
    "website_url",
    "steam_app_id",
    "developer",
    "description",
    "tags",
    "languages",
    "release_date",
    "cover_url",
]


class GameCreate(GameFields):
    favorite: StrictBool = False
    reference_works: References = Field(default_factory=list)

    @model_validator(mode="after")
    def require_name_or_url(self) -> Self:
        if not self.name and not self.website_url:
            raise ValueError("A game needs a name or website URL")
        return self


class GamePatch(GameFields):
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    favorite: StrictBool = False
    reference_works: References = Field(default_factory=list)
    reset_fields: list[GameFieldName] = Field(default_factory=list, max_length=9)

    @model_validator(mode="after")
    def require_unambiguous_patch(self) -> Self:
        if set(self.reset_fields) & self.model_fields_set:
            raise ValueError("A field cannot be set and reset together")
        return self


class SourceIdentity(BaseModel):
    steam_app_id: str | None
    canonical_url: str | None


class GameDetail(GameFields):
    id: UUID
    revision: int
    favorite: bool
    reference_works: list[ReferenceWork]
    source_fields: GameFields
    manual_overrides: PublicJSONObject
    overridden_fields: list[GameFieldName]
    source_identity: SourceIdentity
    last_analyzed_at: datetime | None
    next_analysis_at: datetime | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GamePage(BaseModel):
    items: list[GameDetail]
    total: int
    limit: int
    offset: int
