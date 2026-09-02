from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.analysis_job_contract import public_job_failure, valid_analysis_job_state
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.schemas.match import MatchError


AnalysisJobErrorMessage = Literal[
    "Analysis failed unexpectedly. Please retry.",
    "Analysis could not be queued. Please retry.",
    "Analysis is temporarily unavailable. Please retry.",
    "Analysis could not be completed for this target.",
]


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
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-" r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ),
    )
    profile_id: UUID | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @model_validator(mode="after")
    def require_safe_public_state(self) -> "AnalysisJobResponse":
        if self.completed_units > self.total_units:
            raise ValueError("completed_units cannot exceed total_units")
        if self.status is not JobStatus.FAILED and self.retryable:
            raise ValueError("retryable is allowed only for failed Jobs")
        if not valid_analysis_job_state(
            status=self.status,
            stage=self.stage,
            completed_units=self.completed_units,
            total_units=self.total_units,
            error_code=self.error.code if self.error is not None else None,
            error_message=self.error.message if self.error is not None else None,
            retryable=self.retryable,
            profile_id=self.profile_id,
            result_present=self.profile_id is not None,
            created_at=self.created_at,
            updated_at=self.updated_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
        ):
            raise ValueError("invalid Analysis Job state")
        return self


class AnalysisJobError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")
    message: AnalysisJobErrorMessage

    @model_validator(mode="after")
    def require_fixed_public_mapping(self) -> "AnalysisJobError":
        failure = public_job_failure(self.code)
        if failure is None:
            raise ValueError("unsupported public Analysis Job error code")
        if self.message != failure.message:
            raise ValueError("invalid public Analysis Job error mapping")
        return self


class ChangedAnalysisJobResponse(AnalysisJobResponse):
    kind: Literal["analysis"] = "analysis"
    resource_id: UUID


class ChangedMatchJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["match"] = "match"
    resource_id: UUID
    status: Literal["queued", "running", "succeeded", "failed", "superseded"]
    stage: Literal["screening", "pairwise", "ranking"]
    completed_units: int = Field(ge=0)
    total_units: int = Field(ge=0)
    result_count: int = Field(ge=0)
    retryable: bool
    error: MatchError | None
    correlation_id: str | None
    game_id: UUID
    supersedes_id: UUID | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


ChangedJobResponse = Annotated[
    ChangedAnalysisJobResponse | ChangedMatchJobResponse,
    Field(discriminator="kind"),
]


class ChangedJobsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ChangedJobResponse]
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
