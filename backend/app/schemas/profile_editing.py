"""Typed public contract for source-preserving Profile edits."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr

type EditValue = StrictStr | list[StrictStr]


class ProfileEditField(BaseModel):
    key: str
    section: Literal["facts", "analysis", "brief"]
    label: str
    kind: Literal["text", "multiline", "list"]
    required: bool
    value: EditValue
    source_value: EditValue | None
    is_overridden: bool


class ProfileEditDocument(BaseModel):
    profile_type: Literal["game", "creator"]
    profile_id: UUID
    revision: int
    fields: list[ProfileEditField]


class ProfileEditPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    changes: dict[str, EditValue]
    reset_fields: list[StrictStr]
