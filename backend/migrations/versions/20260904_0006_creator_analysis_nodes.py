"""Add successful Creator analysis node checkpoints.

Revision ID: 20260904_0006
Revises: 20260902_0005
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260904_0006"
down_revision: str | None = "20260902_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_analysis_nodes",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(), nullable=False),
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
        sa.CheckConstraint(
            "node_key ~ '^[a-z][a-z0-9_.:-]{0,63}$'",
            name="ck_creator_analysis_nodes_key",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["analysis_jobs.id"],
            name="fk_creator_analysis_nodes_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", "node_key"),
    )


def downgrade() -> None:
    op.drop_table("creator_analysis_nodes")
