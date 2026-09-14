"""Independent Match screening calls retain successful results across retries."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260914_native_0013"
down_revision = "20260914_native_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "match_screening_checkpoints",
        sa.Column(
            "match_task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("match_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("request_hash", sa.String(64), primary_key=True),
        sa.Column("selections", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade():
    op.drop_table("match_screening_checkpoints")
