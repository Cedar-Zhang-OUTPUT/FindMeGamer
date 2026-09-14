"""Durable native Discover requests and homepage candidates."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260914_native_0011"
down_revision = "20260914_native_0010"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade():
    op.create_table(
        "discover_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "game_id",
            UUID(as_uuid=True),
            sa.ForeignKey("game_profiles.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "game_job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("analysis_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column("steam_url", sa.Text(), nullable=False),
        sa.Column("game_name", sa.String(512), nullable=False),
        sa.Column("game_snapshot", JSONB()),
        sa.Column("conditions", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(32)),
        sa.Column("completed_platforms", JSONB(), nullable=False),
        sa.Column("issues", JSONB(), nullable=False),
        sa.Column("lease_token", UUID(as_uuid=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("game_dispatched_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued','running','done','partial','failed')",
            name="ck_discover_status",
        ),
        *timestamps(),
    )
    op.create_index("ix_discover_jobs_status", "discover_jobs", ["status"])
    op.create_table(
        "discover_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "discover_id",
            UUID(as_uuid=True),
            sa.ForeignKey("discover_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("platform_account_id", sa.String(128), nullable=False),
        sa.Column("metadata_snapshot", JSONB(), nullable=False),
        sa.UniqueConstraint(
            "discover_id",
            "platform",
            "platform_account_id",
            name="uq_discover_candidate_identity",
        ),
        *timestamps(),
    )
    op.create_index(
        "ix_discover_candidates_discover_id", "discover_candidates", ["discover_id"]
    )


def downgrade():
    op.drop_table("discover_candidates")
    op.drop_table("discover_jobs")
