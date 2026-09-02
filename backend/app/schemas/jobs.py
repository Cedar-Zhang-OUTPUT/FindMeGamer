from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType


class AnalysisJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: TargetType
    url: str = Field(min_length=1, max_length=2048)
    mode: JobMode = JobMode.CREATE


class AnalysisJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["job"] = "job"
    id: UUID
    target_type: TargetType
    canonical_target_id: str
    canonical_url: str
    mode: JobMode
    status: JobStatus
    stage: AnalysisStage | None
    completed_units: int
    total_units: int
    retryable: bool
    error: "AnalysisJobError | None" = None
    correlation_id: str | None
    profile_id: UUID | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AnalysisJobError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ChangedJobsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AnalysisJobResponse]
    cursor: str
    has_more: bool
    affected_profile_ids: list[UUID]


class ExistingProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["existing_profile"] = "existing_profile"
    existing_profile_id: UUID
    target_type: TargetType
    canonical_target_id: str
    canonical_url: str


AnalysisJobOutcome = Annotated[
    AnalysisJobResponse | ExistingProfileResponse,
    Field(discriminator="outcome"),
]


class RetryAnalysisJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
