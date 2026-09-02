from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType


ANALYSIS_JOB_INTEGRATION_ERROR_CODES = frozenset(
    {
        "analysis_clock_invalid",
        "analysis_cleanup_failed",
        "analysis_configuration_invalid",
        "analysis_job_identity_changed",
        "analysis_job_not_found",
        "analysis_job_result_invalid",
        "analysis_job_stage_invalid",
        "analysis_job_state_invalid",
        "analysis_job_target_invalid",
        "artifact_job_id_invalid",
        "artifact_name_invalid",
        "artifact_payload_invalid",
        "artifact_payload_too_large",
        "creator_interval_invalid",
        "deepseek_configuration_invalid",
        "deepseek_input_invalid",
        "deepseek_model_contacts_invalid",
        "deepseek_model_evidence_invalid",
        "deepseek_model_output_invalid",
        "deepseek_request_rejected",
        "deepseek_response_invalid",
        "deepseek_response_too_large",
        "deepseek_unavailable",
        "game_interval_invalid",
        "public_page_address_rejected",
        "public_page_content_type_invalid",
        "public_page_redirect_invalid",
        "public_page_redirect_limit",
        "public_page_request_rejected",
        "public_page_response_invalid",
        "public_page_too_large",
        "public_page_unavailable",
        "public_page_url_invalid",
        "s3_configuration_invalid",
        "s3_request_rejected",
        "s3_unavailable",
        "shared_settings_missing",
        "steam_app_id_invalid",
        "steam_game_not_found",
        "steam_request_rejected",
        "steam_response_invalid",
        "steam_response_too_large",
        "steam_source_identity_mismatch",
        "steam_unavailable",
        "youtube_channel_id_invalid",
        "youtube_channel_not_found",
        "youtube_configuration_invalid",
        "youtube_quota_unavailable",
        "youtube_request_rejected",
        "youtube_response_invalid",
        "youtube_response_too_large",
        "youtube_source_identity_mismatch",
        "youtube_target_invalid",
        "youtube_unavailable",
        "youtube_video_limit_invalid",
    }
)
ANALYSIS_JOB_GENERIC_FAILURE_MESSAGE = "Analysis failed unexpectedly. Please retry."
ANALYSIS_JOB_QUEUE_FAILURE_MESSAGE = "Analysis could not be queued. Please retry."
ANALYSIS_JOB_TEMPORARY_FAILURE_MESSAGE = (
    "Analysis is temporarily unavailable. Please retry."
)
ANALYSIS_JOB_PERMANENT_FAILURE_MESSAGE = (
    "Analysis could not be completed for this target."
)
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
            raise ValueError("completed_units must not exceed total_units")
        if self.status is not JobStatus.FAILED and self.retryable:
            raise ValueError("retryable is valid only for failed Jobs")
        return self


class AnalysisJobError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")
    message: AnalysisJobErrorMessage

    @model_validator(mode="after")
    def require_fixed_public_mapping(self) -> "AnalysisJobError":
        if self.code == "analysis_internal_error":
            valid_messages = {ANALYSIS_JOB_GENERIC_FAILURE_MESSAGE}
        elif self.code == "analysis_queue_unavailable":
            valid_messages = {ANALYSIS_JOB_QUEUE_FAILURE_MESSAGE}
        elif self.code in ANALYSIS_JOB_INTEGRATION_ERROR_CODES:
            valid_messages = {
                ANALYSIS_JOB_TEMPORARY_FAILURE_MESSAGE,
                ANALYSIS_JOB_PERMANENT_FAILURE_MESSAGE,
            }
        else:
            raise ValueError("unsupported public Analysis Job error code")
        if self.message not in valid_messages:
            raise ValueError("invalid public Analysis Job error mapping")
        return self


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
