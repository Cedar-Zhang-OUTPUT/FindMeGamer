"""Typed editable Creator data, independent of acquisition identity/evidence."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from app.schemas.library_v2 import ShortText, LongText, WebURL, Labels, unique_labels
from app.schemas.profiles import PublicJSONObject

Platform = Literal["youtube", "x", "twitch", "instagram"]
CreatorSort = Literal[
    "name", "relevance", "followers", "recent_publish", "recent_added"
]
Count = Annotated[StrictInt | None, Field(ge=0)]


class OtherContact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: ShortText = None
    value: Annotated[str, Field(min_length=1, max_length=1024)]
    url: WebURL = None


class CreatorFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ShortText = None
    public_name: ShortText = None
    public_name_confirmed: StrictBool = False
    handle: ShortText = None
    profile_url: WebURL = None
    avatar_url: WebURL = None
    description: LongText = None
    follower_count: Count = None
    follower_count_collected_at: datetime | None = None
    languages: Labels = Field(default_factory=list)
    country_code: Annotated[str | None, Field(pattern=r"^[A-Z]{2}$")] = None
    country_name: ShortText = None
    other_contacts: list[OtherContact] = Field(default_factory=list, max_length=100)
    source_notes: LongText = None
    internal_notes: LongText = None
    interest_notes: LongText = None

    @field_validator("languages")
    @classmethod
    def clean_languages(cls, value):
        return unique_labels(value)

    @field_validator("follower_count_collected_at")
    @classmethod
    def aware_collection(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("A timezone is required")
        return value


class CreatorCreate(CreatorFields):
    platform: Platform = "youtube"
    account_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    favorite: StrictBool = False

    @model_validator(mode="after")
    def identity_required(self) -> Self:
        if not self.account_id and not self.profile_url:
            raise ValueError("A profile URL or platform account ID is required")
        return self


CreatorFieldName = Literal[
    "name",
    "public_name",
    "public_name_confirmed",
    "handle",
    "profile_url",
    "avatar_url",
    "description",
    "follower_count",
    "follower_count_collected_at",
    "languages",
    "country_code",
    "country_name",
    "other_contacts",
    "source_notes",
    "internal_notes",
    "interest_notes",
]


class CreatorPatch(CreatorFields):
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    favorite: StrictBool = False
    reset_fields: list[CreatorFieldName] = Field(default_factory=list)

    @model_validator(mode="after")
    def unambiguous(self) -> Self:
        if set(self.reset_fields) & self.model_fields_set:
            raise ValueError("Cannot set and reset the same field")
        return self


class IdentityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    platform: Platform
    account_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    profile_url: WebURL = None
    confirmed: Literal[True]

    @model_validator(mode="after")
    def valid_identity(self) -> Self:
        if not self.account_id and not self.profile_url:
            raise ValueError("A profile URL or account ID is required")
        return self


class CreatorIdentity(BaseModel):
    platform: Platform
    account_id: str | None
    canonical_url: str | None
    revision: int


class ContactFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    purpose: Annotated[str | None, Field(max_length=512)] = None
    source_url: WebURL = None
    is_active: StrictBool = True
    verification_notes: LongText = None


class ContactCreate(ContactFields):
    expected_revision: Annotated[StrictInt, Field(ge=0)]


class ContactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    email: EmailStr | None = None
    purpose: Annotated[str | None, Field(max_length=512)] = None
    source_url: WebURL = None
    is_active: StrictBool = True
    verification_notes: LongText = None
    reset_fields: list[
        Literal["email", "purpose", "source_url", "is_active", "verification_notes"]
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def unambiguous(self) -> Self:
        if set(self.reset_fields) & self.model_fields_set:
            raise ValueError("Cannot set and reset the same field")
        if "email" in self.model_fields_set and self.email is None:
            raise ValueError("An email is required")
        return self


class ContactDetail(ContactFields):
    id: UUID
    origin: Literal["manual", "source"]
    source_type: str
    validation_state: str
    source_fields: PublicJSONObject
    manual_overrides: PublicJSONObject
    identity_revision: int
    is_current_identity: bool
    updated_at: datetime


class RecentWorkSummary(BaseModel):
    id: UUID
    work_name: str | None
    content_title: str | None
    source_url: str | None
    published_at: datetime | None
    content_type: str


class CreatorDetail(CreatorFields):
    id: UUID
    platform: Platform
    revision: int
    favorite: bool
    source_identity: CreatorIdentity
    source_fields: CreatorFields
    manual_overrides: PublicJSONObject
    overridden_fields: list[str]
    contacts: list[ContactDetail]
    work_count: int
    last_analyzed_at: datetime | None
    next_analysis_at: datetime | None
    analysis_available: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    latest_published_at: datetime | None = None
    active_email_count: int = 0
    contact_status: Literal["available", "missing"] = "missing"
    recent_works: list[RecentWorkSummary] = Field(default_factory=list)


class CreatorPage(BaseModel):
    items: list[CreatorDetail]
    total: int
    limit: int
    offset: int


class WorkMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=128)]
    value: Annotated[float, Field(ge=0, allow_inf_nan=False)]


class WorkFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Platform | None = None
    work_name: ShortText = None
    content_title: ShortText = None
    content_type: Literal[
        "unverified",
        "gameplay",
        "livestream",
        "review",
        "commentary",
        "trailer",
        "news",
        "other",
    ] = "unverified"
    source_url: WebURL = None
    content_id: ShortText = None
    published_at: datetime | None = None
    collected_at: datetime | None = None
    metrics: list[WorkMetric] = Field(default_factory=list, max_length=30)
    game_id: UUID | None = None
    verification_notes: LongText = None
    evidence_excerpt: LongText = None
    timestamp_seconds: Annotated[float | None, Field(ge=0, allow_inf_nan=False)] = None

    @field_validator("published_at", "collected_at")
    @classmethod
    def aware_time(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("A timezone is required")
        return value


class WorkCreate(WorkFields):
    expected_identity_revision: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def title_or_url(self) -> Self:
        if not self.work_name and not self.content_title and not self.source_url:
            raise ValueError("A work/content title or source URL is required")
        return self


WorkFieldName = Literal[
    "platform",
    "work_name",
    "content_title",
    "content_type",
    "source_url",
    "content_id",
    "published_at",
    "collected_at",
    "metrics",
    "game_id",
    "verification_notes",
    "evidence_excerpt",
    "timestamp_seconds",
]


class WorkPatch(WorkFields):
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    reset_fields: list[WorkFieldName] = Field(default_factory=list)

    @model_validator(mode="after")
    def unambiguous(self) -> Self:
        if set(self.reset_fields) & self.model_fields_set:
            raise ValueError("Cannot set and reset the same field")
        return self


class WorkDetail(WorkFields):
    id: UUID
    creator_id: UUID
    platform: Platform
    source_platform: Platform
    origin: Literal["manual", "source"]
    revision: int
    identity_revision: int
    is_current_identity: bool
    source_content_id: str | None
    source_collected_at: datetime | None
    source_fields: PublicJSONObject
    manual_overrides: PublicJSONObject


class WorkPage(BaseModel):
    items: list[WorkDetail]
    total: int
    limit: int
    offset: int
