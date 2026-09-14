from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DiscoverBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_ids: list[UUID] = Field(min_length=1, max_length=100)
    mode: Literal["analyze", "analyze_and_match"]

    @field_validator("candidate_ids")
    @classmethod
    def normalize_selection(cls, values):
        return sorted(set(values))


class DiscoverBatchError(BaseModel):
    code: str
    message: str


class DiscoverBatchItemDetail(BaseModel):
    candidate_id: UUID
    reused: bool = False
    profile_id: UUID | None = None
    analysis_job_id: UUID | None = None
    status: Literal["queued", "running", "succeeded", "failed"]
    error: DiscoverBatchError | None = None


class DiscoverBatchDetail(BaseModel):
    id: UUID
    discover_id: UUID
    mode: Literal["analyze", "analyze_and_match"]
    status: Literal["queued", "running", "done", "partial", "failed", "blocked"]
    items: list[DiscoverBatchItemDetail]
    match_task_id: UUID | None = None
    error: DiscoverBatchError | None = None
    created_at: datetime
    updated_at: datetime


class DiscoverBatchHistory(BaseModel):
    items: list[DiscoverBatchDetail]
