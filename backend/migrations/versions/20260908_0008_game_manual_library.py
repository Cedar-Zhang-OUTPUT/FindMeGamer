"""Allow unbound games and preserve human edits separately from source facts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260908_0008"
down_revision = "20260904_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "game_profiles", "steam_app_id", existing_type=sa.String(32), nullable=True
    )
    op.add_column(
        "game_profiles",
        sa.Column(
            "manual_overrides",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "game_profiles",
        sa.Column(
            "reference_works",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "game_profiles",
        sa.Column(
            "manual_revision", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )


def downgrade() -> None:
    # A maintenance window does not authorize discarding colleagues' new data.
    exists = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM game_profiles WHERE steam_app_id IS NULL OR manual_overrides <> '{}'::jsonb OR reference_works <> '[]'::jsonb)"
        )
    )
    if exists:
        raise RuntimeError(
            "Cannot downgrade while manual game data exists; restore a pre-migration backup instead."
        )
    op.drop_column("game_profiles", "manual_revision")
    op.drop_column("game_profiles", "reference_works")
    op.drop_column("game_profiles", "manual_overrides")
    op.alter_column(
        "game_profiles", "steam_app_id", existing_type=sa.String(32), nullable=False
    )
