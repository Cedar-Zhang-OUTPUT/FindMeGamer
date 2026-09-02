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


def upgrade() -> None:
    op.execute("SELECT pg_advisory_xact_lock(4604199987260753489)")
    op.execute(
        """
        WITH repair_timestamp AS (
            UPDATE analysis_job_change_watermark AS watermark
            SET last_changed_at = GREATEST(
                clock_timestamp(),
                watermark.last_changed_at + INTERVAL '1 microsecond',
                COALESCE(
                    (
                        SELECT max(updated_at) + INTERVAL '1 microsecond'
                        FROM analysis_jobs
                    ),
                    '-infinity'::timestamptz
                )
            )
            WHERE singleton
              AND EXISTS (
                  SELECT 1
                  FROM analysis_jobs
                  WHERE completed_units < 0
                     OR total_units < 0
                     OR completed_units > total_units
                     OR (status <> 'failed' AND retryable)
              )
            RETURNING last_changed_at
        )
        UPDATE analysis_jobs
        SET completed_units = LEAST(
                GREATEST(completed_units, 0),
                GREATEST(total_units, 0)
            ),
            total_units = GREATEST(total_units, 0),
            retryable = CASE
                WHEN status = 'failed' THEN retryable
                ELSE false
            END,
            updated_at = (SELECT last_changed_at FROM repair_timestamp)
        WHERE completed_units < 0
           OR total_units < 0
           OR completed_units > total_units
           OR (status <> 'failed' AND retryable)
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
    op.create_index(
        "ix_analysis_jobs_updated_at_id",
        "analysis_jobs",
        ["updated_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_jobs_updated_at_id", table_name="analysis_jobs")
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
