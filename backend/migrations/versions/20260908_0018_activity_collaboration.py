"""Manual Activity collaboration and sourced response history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260908_0018"
down_revision = "20260908_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activity_collaborations",
        sa.Column(
            "selection_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("activity_selections.id"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "follow_up_state",
            sa.String(32),
            nullable=False,
            server_default="not_followed_up",
        ),
        sa.Column(
            "cooperation_state",
            sa.String(32),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        *[
            sa.Column(
                name,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
            for name in ("created_at", "updated_at")
        ],
    )
    op.create_table(
        "activity_responses",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "selection_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("activity_collaborations.selection_id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "selection_id", "revision", name="uq_activity_response_revision"
        ),
    )
    op.create_index(
        "ix_activity_responses_selection_id", "activity_responses", ["selection_id"]
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM activity_collaborations)")
    ):
        raise RuntimeError(
            "Back up Activity collaboration records before downgrading populated tables."
        )
    op.drop_table("activity_responses")
    op.drop_table("activity_collaborations")
