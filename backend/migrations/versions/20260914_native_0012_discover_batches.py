"""Durable selected analysis and one automatic ordinary Match per batch."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260914_native_0012"
down_revision = "20260914_native_0011"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade():
    op.create_table(
        "discover_analysis_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "discover_id",
            UUID(as_uuid=True),
            sa.ForeignKey("discover_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), unique=True, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "match_task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("match_tasks.id"),
            unique=True,
        ),
        sa.Column("error", JSONB()),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("match_dispatched_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "mode IN ('analyze','analyze_and_match')", name="ck_discover_batch_mode"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','done','partial','failed','blocked')",
            name="ck_discover_batch_status",
        ),
        *timestamps(),
    )
    op.create_index(
        "ix_discover_analysis_batches_discover_id",
        "discover_analysis_batches",
        ["discover_id"],
    )
    op.create_index(
        "ix_discover_analysis_batches_status", "discover_analysis_batches", ["status"]
    )
    op.create_table(
        "discover_analysis_items",
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("discover_analysis_batches.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "candidate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("discover_candidates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("creator_profiles.id", ondelete="SET NULL"),
        ),
        sa.Column("reused", sa.Boolean(), nullable=False),
        sa.Column(
            "analysis_job_id", UUID(as_uuid=True), sa.ForeignKey("analysis_jobs.id")
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", JSONB()),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_discover_item_status",
        ),
        *timestamps(),
    )
    op.create_index(
        "ix_discover_analysis_items_analysis_job_id",
        "discover_analysis_items",
        ["analysis_job_id"],
    )


def downgrade():
    op.drop_table("discover_analysis_items")
    op.drop_table("discover_analysis_batches")
