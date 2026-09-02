"""Add the monotonic Analysis Job change watermark.

Revision ID: 20260902_0003
Revises: 20260902_0002
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_0003"
down_revision: str | None = "20260902_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_job_change_watermark",
        sa.Column("singleton", sa.Boolean(), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("singleton", name="singleton_true"),
        sa.PrimaryKeyConstraint("singleton"),
    )
    op.execute(
        """
        INSERT INTO analysis_job_change_watermark (singleton, last_changed_at)
        SELECT
            true,
            GREATEST(
                clock_timestamp(),
                COALESCE(
                    max(updated_at) + INTERVAL '1 microsecond',
                    '-infinity'::timestamptz
                )
            )
        FROM analysis_jobs
        """
    )


def downgrade() -> None:
    op.drop_table("analysis_job_change_watermark")
