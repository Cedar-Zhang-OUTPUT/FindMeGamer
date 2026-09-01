from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, StrictBool, StrictStr


JSONStructure = dict[str, Any]


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


class GameProfileCard(BaseModel):
    type: Literal["game"] = "game"
    id: UUID
    name: str
    steam_app_id: str
    canonical_url: str
    favorite: bool
    current_facts: JSONStructure
    brief: JSONStructure
    source_status: JSONStructure
    last_analyzed_at: datetime | None
    next_analysis_at: datetime | None


class CreatorProfileCard(BaseModel):
    type: Literal["creator"] = "creator"
    id: UUID
    name: str
    youtube_channel_id: str
    canonical_url: str
    favorite: bool
    current_facts: JSONStructure
    brief: JSONStructure
    source_status: JSONStructure
    last_analyzed_at: datetime | None
    next_analysis_at: datetime | None
    contact: CreatorContactResponse | None


class GameProfileDetail(GameProfileCard):
    analysis: JSONStructure
    model_metadata: JSONStructure
    prompt_metadata: JSONStructure


class CreatorProfileDetail(CreatorProfileCard):
    analysis: JSONStructure
    model_metadata: JSONStructure
    prompt_metadata: JSONStructure
    manual_notes: str | None
