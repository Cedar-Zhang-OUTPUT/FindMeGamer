"""Constrain public Analysis Job state and index change polling.

Revision ID: 20260902_0004
Revises: 20260902_0003
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260902_0004"
down_revision: str | None = "20260902_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PERMANENT_CODES = (
    "analysis_cleanup_failed",
    "analysis_clock_invalid",
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
    "deepseek_request_rejected",
    "deepseek_response_invalid",
    "deepseek_response_too_large",
    "game_interval_invalid",
    "public_page_address_rejected",
    "public_page_content_type_invalid",
    "public_page_redirect_invalid",
    "public_page_redirect_limit",
    "public_page_request_rejected",
    "public_page_response_invalid",
    "public_page_too_large",
    "public_page_url_invalid",
    "s3_configuration_invalid",
    "s3_request_rejected",
    "shared_settings_missing",
    "steam_app_id_invalid",
    "steam_game_not_found",
    "steam_request_rejected",
    "steam_response_invalid",
    "steam_response_too_large",
    "steam_source_identity_mismatch",
    "youtube_channel_id_invalid",
    "youtube_channel_not_found",
    "youtube_configuration_invalid",
    "youtube_request_rejected",
    "youtube_response_invalid",
    "youtube_response_too_large",
    "youtube_source_identity_mismatch",
    "youtube_target_invalid",
    "youtube_video_limit_invalid",
)
_RETRYABLE_CODES = (
    "deepseek_model_contacts_invalid",
    "deepseek_model_evidence_invalid",
    "deepseek_model_output_invalid",
    "deepseek_unavailable",
    "public_page_unavailable",
    "s3_unavailable",
    "steam_unavailable",
    "youtube_quota_unavailable",
    "youtube_unavailable",
)


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_ERROR_MAPPING_CHECK = f"""
(
    error_code IN ({_sql_list(_PERMANENT_CODES)})
    AND error_message = 'Analysis could not be completed for this target.'
    AND NOT retryable
)
OR (
    error_code IN ({_sql_list(_RETRYABLE_CODES)})
    AND error_message = 'Analysis is temporarily unavailable. Please retry.'
    AND retryable
)
OR (
    error_code = 'analysis_internal_error'
    AND error_message = 'Analysis failed unexpectedly. Please retry.'
    AND retryable
)
OR (
    error_code = 'analysis_queue_unavailable'
    AND error_message = 'Analysis could not be queued. Please retry.'
    AND retryable
)
"""

_STATUS_SHAPE_CHECK = """
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
    AND result_payload IS NOT NULL AND jsonb_typeof(result_payload) = 'object'
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


def upgrade() -> None:
    # The released 0003 writer locks a Job row before its mapper hook takes the
    # advisory fence. Taking that fence here would create row -> advisory and
    # advisory -> row edges during rolling deployment. A table lock alone waits
    # for both old and current mutations without participating in that cycle.
    # NOWAIT is an executable deployment gate: if an old/new writer or poller
    # is active, abort this transactional migration before joining PostgreSQL's
    # table-lock queue. The operator can retry after in-flight work drains.
    op.execute("LOCK TABLE analysis_jobs IN ACCESS EXCLUSIVE MODE NOWAIT")
    op.execute(
        """
        UPDATE analysis_jobs
        SET status = 'failed',
            stage = NULL,
            completed_units = 0,
            total_units = 0,
            error_code = 'analysis_job_result_invalid',
            error_message = 'Analysis could not be completed for this target.',
            retryable = false,
            profile_id = NULL,
            result_payload = NULL,
            started_at = NULL,
            completed_at = GREATEST(created_at, COALESCE(completed_at, created_at))
        WHERE status = 'succeeded'
          AND (
              profile_id IS NULL
              OR result_payload IS NULL
              OR jsonb_typeof(result_payload) <> 'object'
          )
        """
    )
    op.execute(
        """
        UPDATE analysis_jobs
        SET stage = NULL,
            completed_units = 0,
            total_units = 0,
            error_code = NULL,
            error_message = NULL,
            retryable = false,
            profile_id = NULL,
            result_payload = NULL,
            started_at = NULL,
            completed_at = NULL
        WHERE status = 'queued'
        """
    )
    op.execute(
        """
        UPDATE analysis_jobs
        SET stage = COALESCE(stage, 'fetching_data'),
            completed_units = CASE
                WHEN total_units > 0
                  AND completed_units >= 0
                  AND completed_units < total_units
                    THEN completed_units
                ELSE LEAST(GREATEST(completed_units, 0), 4)
            END,
            total_units = CASE
                WHEN total_units > 0
                  AND completed_units >= 0
                  AND completed_units < total_units
                    THEN total_units
                ELSE 5
            END,
            error_code = NULL,
            error_message = NULL,
            retryable = false,
            profile_id = NULL,
            result_payload = NULL,
            started_at = GREATEST(created_at, COALESCE(started_at, created_at)),
            completed_at = NULL
        WHERE status = 'running'
        """
    )
    op.execute(
        """
        UPDATE analysis_jobs
        SET stage = 'finalizing',
            completed_units = CASE WHEN total_units > 0 THEN total_units ELSE 5 END,
            total_units = CASE WHEN total_units > 0 THEN total_units ELSE 5 END,
            error_code = NULL,
            error_message = NULL,
            retryable = false,
            started_at = GREATEST(created_at, COALESCE(started_at, created_at)),
            completed_at = GREATEST(
                created_at,
                COALESCE(started_at, created_at),
                COALESCE(completed_at, created_at)
            )
        WHERE status = 'succeeded'
        """
    )
    op.execute(
        f"""
        UPDATE analysis_jobs
        SET stage = CASE
                WHEN stage IS NULL THEN NULL
                ELSE stage
            END,
            completed_units = CASE
                WHEN stage IS NULL THEN 0
                WHEN total_units > 0
                  AND completed_units >= 0
                  AND completed_units < total_units
                    THEN completed_units
                ELSE LEAST(GREATEST(completed_units, 0), 4)
            END,
            total_units = CASE
                WHEN stage IS NULL THEN 0
                WHEN total_units > 0
                  AND completed_units >= 0
                  AND completed_units < total_units
                    THEN total_units
                ELSE 5
            END,
            error_code = CASE
                WHEN error_code IN ({_sql_list(_PERMANENT_CODES)})
                  OR error_code IN ({_sql_list(_RETRYABLE_CODES)})
                  OR error_code IN ('analysis_internal_error', 'analysis_queue_unavailable')
                    THEN error_code
                ELSE 'analysis_internal_error'
            END,
            error_message = CASE
                WHEN error_code IN ({_sql_list(_PERMANENT_CODES)})
                    THEN 'Analysis could not be completed for this target.'
                WHEN error_code IN ({_sql_list(_RETRYABLE_CODES)})
                    THEN 'Analysis is temporarily unavailable. Please retry.'
                WHEN error_code = 'analysis_queue_unavailable'
                    THEN 'Analysis could not be queued. Please retry.'
                ELSE 'Analysis failed unexpectedly. Please retry.'
            END,
            retryable = error_code IN (
                {_sql_list(_RETRYABLE_CODES)},
                'analysis_internal_error',
                'analysis_queue_unavailable'
            ),
            profile_id = NULL,
            result_payload = NULL,
            started_at = CASE
                WHEN stage IS NULL THEN NULL
                ELSE GREATEST(created_at, COALESCE(started_at, created_at))
            END,
            completed_at = GREATEST(
                created_at,
                CASE
                    WHEN stage IS NULL THEN created_at
                    ELSE GREATEST(created_at, COALESCE(started_at, created_at))
                END,
                COALESCE(completed_at, created_at)
            )
        WHERE status = 'failed'
        """
    )
    op.execute(
        """
        WITH repair_timestamp AS (
            UPDATE analysis_job_change_watermark AS watermark
            SET last_changed_at = GREATEST(
                clock_timestamp(),
                watermark.last_changed_at + INTERVAL '1 microsecond',
                COALESCE(
                    (
                        SELECT max(GREATEST(updated_at, created_at))
                               + INTERVAL '1 microsecond'
                        FROM analysis_jobs
                    ),
                    '-infinity'::timestamptz
                )
            )
            WHERE singleton
              AND EXISTS (SELECT 1 FROM analysis_jobs)
            RETURNING last_changed_at
        )
        UPDATE analysis_jobs
        SET updated_at = (SELECT last_changed_at FROM repair_timestamp)
        """
    )
    op.create_check_constraint(
        "ck_analysis_jobs_completed_units_nonnegative",
        "analysis_jobs",
        "completed_units >= 0",
    )
    op.create_check_constraint(
        "ck_analysis_jobs_total_units_nonnegative",
        "analysis_jobs",
        "total_units >= 0",
    )
    op.create_check_constraint(
        "ck_analysis_jobs_completed_not_above_total",
        "analysis_jobs",
        "completed_units <= total_units",
    )
    op.create_check_constraint(
        "ck_analysis_jobs_retryable_only_failed",
        "analysis_jobs",
        "status = 'failed' OR NOT retryable",
    )
    op.create_check_constraint(
        "ck_analysis_jobs_error_mapping",
        "analysis_jobs",
        f"status <> 'failed' OR ({_ERROR_MAPPING_CHECK})",
    )
    op.create_check_constraint(
        "ck_analysis_jobs_status_shape",
        "analysis_jobs",
        _STATUS_SHAPE_CHECK,
    )
    op.create_index(
        "ix_analysis_jobs_updated_at_id",
        "analysis_jobs",
        ["updated_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_jobs_updated_at_id", table_name="analysis_jobs")
    op.drop_constraint(
        "ck_analysis_jobs_status_shape",
        "analysis_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_analysis_jobs_error_mapping",
        "analysis_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_analysis_jobs_retryable_only_failed",
        "analysis_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_analysis_jobs_completed_not_above_total",
        "analysis_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_analysis_jobs_total_units_nonnegative",
        "analysis_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_analysis_jobs_completed_units_nonnegative",
        "analysis_jobs",
        type_="check",
    )
