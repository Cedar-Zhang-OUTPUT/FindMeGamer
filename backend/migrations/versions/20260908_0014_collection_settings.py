"""Cloud-shared administrative collection policy; no acquisition side effects."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260908_0014"
down_revision = "20260908_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "analysis_jobs",
        sa.Column(
            "collection_paused", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "shared_settings",
        sa.Column(
            "collection_enabled",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade():
    # Do not silently undo an explicit administrative restriction on rollback.
    configured = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM shared_settings WHERE collection_enabled <> '{}'::jsonb)"
        )
    )
    if configured:
        raise RuntimeError("Preserve collection settings before downgrading.")
    paused = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM analysis_jobs WHERE collection_paused)")
    )
    if paused:
        raise RuntimeError("Preserve paused Analysis jobs before downgrading.")
    op.drop_column("analysis_jobs", "collection_paused")
    op.drop_column("shared_settings", "collection_enabled")
