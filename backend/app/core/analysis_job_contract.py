from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping
from uuid import UUID


if TYPE_CHECKING:
    from app.db.models.enums import AnalysisStage, JobStatus


TEMPORARY_FAILURE_MESSAGE = "Analysis is temporarily unavailable. Please retry."
PERMANENT_FAILURE_MESSAGE = "Analysis could not be completed for this target."
INTERNAL_FAILURE_MESSAGE = "Analysis failed unexpectedly. Please retry."
QUEUE_FAILURE_MESSAGE = "Analysis could not be queued. Please retry."

INTEGRATION_ERROR_CODES = frozenset(
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
        "x_account_id_invalid",
        "x_account_not_found",
        "x_request_rejected",
        "x_response_invalid",
        "x_source_identity_mismatch",
        "x_unavailable",
    }
)
RETRYABLE_INTEGRATION_ERROR_CODES = frozenset(
    {
        "deepseek_model_contacts_invalid",
        "deepseek_model_evidence_invalid",
        "deepseek_model_output_invalid",
        "deepseek_unavailable",
        "public_page_unavailable",
        "s3_unavailable",
        "steam_unavailable",
        "youtube_quota_unavailable",
        "youtube_unavailable",
        "x_unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class PublicJobFailure:
    message: str
    retryable: bool


_FAILURES = {
    code: PublicJobFailure(
        message=(
            TEMPORARY_FAILURE_MESSAGE
            if code in RETRYABLE_INTEGRATION_ERROR_CODES
            else PERMANENT_FAILURE_MESSAGE
        ),
        retryable=code in RETRYABLE_INTEGRATION_ERROR_CODES,
    )
    for code in INTEGRATION_ERROR_CODES
}
_FAILURES.update(
    {
        "analysis_internal_error": PublicJobFailure(
            message=INTERNAL_FAILURE_MESSAGE,
            retryable=True,
        ),
        "analysis_queue_unavailable": PublicJobFailure(
            message=QUEUE_FAILURE_MESSAGE,
            retryable=True,
        ),
    }
)
PUBLIC_JOB_FAILURES: Mapping[str, PublicJobFailure] = MappingProxyType(_FAILURES)


def _sql_list(values: set[str] | frozenset[str]) -> str:
    return ", ".join(f"'{value}'" for value in sorted(values))


PUBLIC_JOB_ERROR_MAPPING_SQL = f"""
(
    error_code IN ({_sql_list(INTEGRATION_ERROR_CODES - RETRYABLE_INTEGRATION_ERROR_CODES)})
    AND error_message = '{PERMANENT_FAILURE_MESSAGE}'
    AND NOT retryable
)
OR (
    error_code IN ({_sql_list(RETRYABLE_INTEGRATION_ERROR_CODES)})
    AND error_message = '{TEMPORARY_FAILURE_MESSAGE}'
    AND retryable
)
OR (
    error_code = 'analysis_internal_error'
    AND error_message = '{INTERNAL_FAILURE_MESSAGE}'
    AND retryable
)
OR (
    error_code = 'analysis_queue_unavailable'
    AND error_message = '{QUEUE_FAILURE_MESSAGE}'
    AND retryable
)
"""

ANALYSIS_JOB_STATUS_SHAPE_SQL = """
updated_at >= created_at
AND (
status NOT IN ('queued', 'running', 'succeeded', 'failed')
OR (
(
    status = 'queued'
    AND stage IS NULL
    AND completed_units = 0 AND total_units = 0
    AND error_code IS NULL AND error_message IS NULL AND NOT retryable
    AND profile_id IS NULL
    AND (result_payload IS NULL OR result_payload = 'null'::jsonb)
    AND started_at IS NULL AND completed_at IS NULL
)
OR (
    status = 'running'
    AND stage IS NOT NULL
    AND total_units > 0 AND completed_units < total_units
    AND error_code IS NULL AND error_message IS NULL AND NOT retryable
    AND profile_id IS NULL
    AND (result_payload IS NULL OR result_payload = 'null'::jsonb)
    AND started_at IS NOT NULL AND started_at >= created_at
    AND completed_at IS NULL
)
OR (
    status = 'succeeded'
    AND stage = 'finalizing'
    AND total_units > 0 AND completed_units = total_units
    AND error_code IS NULL AND error_message IS NULL AND NOT retryable
    AND profile_id IS NOT NULL
    AND result_payload = jsonb_build_object('profile_id', profile_id::text)
    AND started_at IS NOT NULL AND started_at >= created_at
    AND completed_at IS NOT NULL AND completed_at >= started_at
)
OR (
    status = 'failed'
    AND error_code IS NOT NULL AND error_message IS NOT NULL
    AND profile_id IS NULL
    AND (result_payload IS NULL OR result_payload = 'null'::jsonb)
    AND completed_at IS NOT NULL AND completed_at >= created_at
    AND (
        (
            stage IS NULL
            AND completed_units = 0 AND total_units = 0
            AND started_at IS NULL
        )
        OR (
            stage IS NOT NULL
            AND total_units > 0 AND completed_units < total_units
            AND started_at IS NOT NULL AND started_at >= created_at
            AND completed_at >= started_at
        )
    )
)
)
)
"""


def public_job_failure(code: object) -> PublicJobFailure | None:
    if not isinstance(code, str):
        return None
    return PUBLIC_JOB_FAILURES.get(code)


def _aware(value: object) -> bool:
    return bool(
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def valid_analysis_job_state(
    *,
    status: JobStatus,
    stage: AnalysisStage | None,
    completed_units: object,
    total_units: object,
    error_code: object,
    error_message: object,
    retryable: object,
    profile_id: UUID | None,
    result_present: bool,
    created_at: object,
    updated_at: object,
    started_at: object,
    completed_at: object,
) -> bool:
    # Keep this dependency local: the ORM model imports the SQL constants above,
    # while Python imports a package's ``__init__`` before its enum submodule.
    from app.db.models.enums import AnalysisStage, JobStatus

    if (
        type(completed_units) is not int
        or type(total_units) is not int
        or type(retryable) is not bool
        or completed_units < 0
        or total_units < 0
        or completed_units > total_units
        or not _aware(created_at)
        or not _aware(updated_at)
        or updated_at < created_at
    ):
        return False
    if started_at is not None:
        if not _aware(started_at) or started_at < created_at:
            return False
    if completed_at is not None:
        if not _aware(completed_at) or completed_at < created_at:
            return False
        if started_at is not None and completed_at < started_at:
            return False

    failure = public_job_failure(error_code)
    has_failure = error_code is not None or error_message is not None
    if status is JobStatus.FAILED:
        if (
            failure is None
            or error_message != failure.message
            or retryable is not failure.retryable
            or completed_at is None
            or profile_id is not None
            or result_present
        ):
            return False
        if stage is None:
            return bool(
                started_at is None and completed_units == 0 and total_units == 0
            )
        return bool(
            started_at is not None and total_units > 0 and completed_units < total_units
        )

    if has_failure or retryable or error_code is not None or error_message is not None:
        return False
    if status is JobStatus.QUEUED:
        return bool(
            stage is None
            and completed_units == 0
            and total_units == 0
            and profile_id is None
            and not result_present
            and started_at is None
            and completed_at is None
        )
    if status is JobStatus.RUNNING:
        return bool(
            stage is not None
            and completed_units < total_units
            and total_units > 0
            and profile_id is None
            and not result_present
            and started_at is not None
            and completed_at is None
        )
    if status is JobStatus.SUCCEEDED:
        return bool(
            stage is AnalysisStage.FINALIZING
            and completed_units == total_units
            and total_units > 0
            and profile_id is not None
            and result_present
            and started_at is not None
            and completed_at is not None
        )
    return False
