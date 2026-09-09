"""Initialize default selections once; preserve all existing user choices."""

from alembic import op
import sqlalchemy as sa

revision = "20260909_0021"
down_revision = "20260909_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "activities",
        sa.Column(
            "initial_selection_initialized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column(
        "activities", "initial_selection_initialized", server_default=sa.false()
    )


def downgrade():
    op.drop_column("activities", "initial_selection_initialized")
