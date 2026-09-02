from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    completed_units: int = Field(ge=0)
    total_units: int = Field(ge=0)
    retryable: bool
    error: "AnalysisJobError | None" = None
    correlation_id: str | None = Field(
        pattern=r"^[A-Za-z0-9._-]{1,128}$",
    )
    profile_id: UUID | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @model_validator(mode="after")
    def require_safe_public_state(self) -> "AnalysisJobResponse":
        if self.completed_units > self.total_units:
            raise ValueError("completed_units must not exceed total_units")
        if self.status is not JobStatus.FAILED and self.retryable:
            raise ValueError("retryable is valid only for failed Jobs")
        return self


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
