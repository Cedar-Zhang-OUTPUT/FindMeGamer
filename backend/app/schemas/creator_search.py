from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel
from app.schemas.activity import StrictModel
from app.schemas.discovery_planning import PlanCreate


class CreatorSearchCreate(PlanCreate):
    mode: Literal["discover"] = "discover"


class CreatorSearchRetry(StrictModel):
    acknowledge_unknown: bool = False


class CreatorSearchEmpty(StrictModel):
    pass


class CreatorSearchAccepted(BaseModel):
    search_id: UUID
    status: str


class CreatorSearchCounts(BaseModel):
    discovered: int = 0
    profile_ready: int = 0
    profile_reused: int = 0
    profile_failed: int = 0
    email_available: int = 0
    email_missing: int = 0
    email_failed: int = 0
    evaluated: int = 0
    matched: int = 0


class CreatorSearchView(BaseModel):
    id: UUID
    activity_id: UUID
    plan_id: UUID
    query_id: UUID | None
    evaluation_id: UUID | None
    parent_search_id: UUID | None
    status: Literal[
        "queued", "running", "stopping", "stopped", "completed", "partial", "failed"
    ]
    stage: Literal[
        "planning",
        "discovery",
        "profiles",
        "emails",
        "screening",
        "deep_match",
        "ranking",
        "complete",
    ]
    counts: CreatorSearchCounts
    stop_requested: bool
    retryable: bool
    outcome_unknown: bool
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class CreatorSearchUnitView(BaseModel):
    candidate_id: UUID
    creator_id: UUID
    platform: str
    profile_status: Literal["pending", "running", "ready", "reused", "failed"]
    email_status: Literal["pending", "running", "available", "missing", "failed"]
    analysis_job_id: UUID | None
    profile_error_code: str | None
    email_error_code: str | None


class CreatorSearchPage(BaseModel):
    items: list[CreatorSearchView]
    total: int
    limit: int
    offset: int


class CreatorSearchUnitPage(BaseModel):
    items: list[CreatorSearchUnitView]
    total: int
    limit: int
    offset: int
