"""Persist draft-local overrides independently of refreshed source data."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260913_0023"
down_revision = "20260910_0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "outreach_drafts",
        sa.Column(
            "manual_overrides",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Old rows do not distinguish AI output from human edits. Preserve all existing
    # values rather than risk erasing an editor's work on the first refresh.
    op.execute(
        "UPDATE outreach_drafts SET manual_overrides = values WHERE jsonb_typeof(values) = 'object'"
    )


def downgrade():
    op.drop_column("outreach_drafts", "manual_overrides")
