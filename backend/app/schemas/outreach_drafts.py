"""Four constrained personalization values, never a model-written email body."""

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanonicalRegistration(StrictInput):
    game_id: UUID


class TemplateVersionCreate(CanonicalRegistration):
    request_id: UUID
    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=998)
    fixed_fragments: list[str] = Field(min_length=5, max_length=5)

    @field_validator("name")
    @classmethod
    def visible_name(cls, value):
        if not value.strip():
            raise ValueError("Give this template version a name.")
        return value.strip()


class TemplateSource(BaseModel):
    kind: Literal["canonical", "user_saved", "game_bound"]
    document_id: str | None = None
    revision: int | None = None
    steam_app_id: str | None = None
    raw_hash: str | None = None
    game_id: UUID | None = None
    game_revision: int | None = None
    game_fingerprint: str | None = None
    sender_name: str | None = None


class TemplateContent(BaseModel):
    name: str
    subject: str
    fixed_fragments: list[str]
    fixed_hash: str
    source_metadata: TemplateSource


class TemplateVersionView(TemplateContent):
    id: UUID
    game_id: UUID
    created_at: datetime


class BuiltinTemplate(TemplateContent):
    key: Literal["liminal-revision-69", "game-outreach-v1"] = "liminal-revision-69"
    requires_explicit_registration: Literal[True] = True


class TemplateCatalog(BaseModel):
    items: list[TemplateVersionView]
    builtin: BuiltinTemplate | None


class DraftSlotValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    firstName: str = Field(max_length=600)
    channelName: str = Field(max_length=600)
    reference: str = Field(max_length=600)
    observation: str = Field(max_length=600)

    @field_validator("*")
    @classmethod
    def plain_filled_text(cls, value):
        if (
            value != value.strip()
            or re.search(r"[\x00-\x1f\x7f<>{}]", value)
            or re.search(
                r"\[(?:first name|channel name|reference game\s*/\s*video|unfilled[^\]]*|specific observation[^\]]*)\]",
                value,
                re.IGNORECASE,
            )
        ):
            raise ValueError("Use filled, single-line plain text for each slot.")
        return value


class SlotValues(DraftSlotValues):
    """Complete generated/sendable values; saving a draft uses DraftSlotValues."""

    @field_validator("*")
    @classmethod
    def filled(cls, value):
        if not value:
            raise ValueError("Fill each slot before sending.")
        return value

    @field_validator("observation")
    @classmethod
    def includes_period(cls, value):
        if not value.endswith("."):
            raise ValueError("The observation slot includes its final period.")
        return value


class CompositionCreate(StrictInput):
    request_id: UUID
    recipient_batch_id: UUID
    template_version_id: UUID


class DraftRevision(StrictInput):
    expected_revision: StrictInt = Field(ge=0)
    context_token: str = Field(pattern=r"^[0-9a-f]{64}$")


class DraftEdit(DraftRevision):
    values: DraftSlotValues


class DraftRefresh(DraftRevision):
    preserve_values: StrictBool = False
    values: DraftSlotValues | None = None

    @model_validator(mode="after")
    def explicit_preserved_values(self):
        if self.preserve_values and self.values is None:
            raise ValueError("Provide all four values when preserving personalization.")
        if not self.preserve_values and "values" in self.model_fields_set:
            raise ValueError("Values require preserve_values=true.")
        return self


class FactMember(DraftRevision):
    draft_id: UUID


class SenderFacts(StrictInput):
    members: list[FactMember] = Field(min_length=1, max_length=600)
    following: StrictBool
    enjoyed: StrictBool
    liked: StrictBool

    @field_validator("members")
    @classmethod
    def unique_members(cls, value):
        if len({member.draft_id for member in value}) != len(value):
            raise ValueError("Choose each draft only once.")
        return value


class DraftView(BaseModel):
    id: UUID
    composition_id: UUID
    recipient_snapshot_id: UUID
    selection_id: UUID
    input_order: int
    revision: int
    context_token: str
    source_changed: bool
    status: Literal["pending", "running", "succeeded", "failed", "needs_repair"]
    error_code: str | None
    input: dict[str, Any]
    values: DraftSlotValues | None
    missing_fields: list[str]
    slot_sources: dict[str, Any]
    rendered: dict[str, str] | None
    sender_facts_valid: bool
    sender_facts: dict[str, Any]
    send_ready: Literal[False] = False


class CompositionView(BaseModel):
    id: UUID
    activity_id: UUID
    recipient_batch_id: UUID
    template_version_id: UUID
    created_at: datetime
    recipient_count: int
    drafts: list[DraftView]
    send_ready: Literal[False] = False


class CompositionPage(BaseModel):
    items: list[CompositionView]
    total: int
    limit: int
    offset: int
