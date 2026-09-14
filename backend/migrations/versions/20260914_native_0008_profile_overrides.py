"""Native branch: source-preserving Profile edits and frozen Match context."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260914_native_0008"
down_revision = "20260904_0007"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("game_profiles", "creator_profiles"):
        op.add_column(
            table,
            sa.Column(
                "manual_overrides",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "profile_revision", sa.Integer(), nullable=False, server_default="0"
            ),
        )
    op.add_column(
        "match_tasks",
        sa.Column(
            "locked_game_context",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "match_screening_records",
        sa.Column(
            "locked_manual_context",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade():
    op.drop_column("match_screening_records", "locked_manual_context")
    op.drop_column("match_tasks", "locked_game_context")
    for table in ("game_profiles", "creator_profiles"):
        op.drop_column(table, "profile_revision")
        op.drop_column(table, "manual_overrides")
