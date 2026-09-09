from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StrictStr, model_validator

from app.schemas.activity import DiscoveryOptions
from app.schemas.discovery_plan_output import SearchPlanOutput
from app.schemas.discovery import Platform


class PlanCreate(DiscoveryOptions):
    mode: Literal["preview", "discover"]
    platforms: list[Platform] = Field(min_length=1, max_length=4)
    keywords: list[Annotated[StrictStr, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def unique_platforms(self):
        if len(set(self.platforms)) != len(self.platforms):
            raise ValueError("Choose each platform once.")
        if any(
            not word.strip() or any(ord(c) < 32 for c in word) for word in self.keywords
        ):
            raise ValueError("Keywords must be nonblank text without controls.")
        return self


class PlanAccepted(BaseModel):
    plan_id: UUID
    status: str


class PublishedPlanOutput(SearchPlanOutput):
    provider_queries: dict[Platform, str]


class PlanView(BaseModel):
    id: UUID
    activity_id: UUID
    status: Literal["queued", "running", "ready", "failed"]
    conditions: PlanCreate
    source_snapshot: dict[str, Any]
    output: PublishedPlanOutput | None
    error_code: str | None
    retryable: bool
    attempt: int
    model: str
    query_id: UUID | None
    created_at: datetime


class PlanPage(BaseModel):
    items: list[PlanView]
    total: int
    limit: int
    offset: int
