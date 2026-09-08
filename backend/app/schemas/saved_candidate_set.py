from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.activity import StrictModel


class SavedSetCreate(StrictModel):
    request_id: UUID
    name: str = Field(min_length=1, max_length=255)
    candidate_ids: list[UUID] = Field(min_length=1, max_length=600)

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Give this candidate set a name.")
        return value

    @field_validator("candidate_ids")
    @classmethod
    def unique_members(cls, value):
        return list(dict.fromkeys(value))


class SavedSetView(BaseModel):
    id: UUID
    query_id: UUID
    activity_id: UUID
    name: str
    candidate_ids: list[UUID]
    count: int
    created_at: datetime


class SavedSetPage(BaseModel):
    items: list[SavedSetView]
    total: int
    limit: int
    offset: int
