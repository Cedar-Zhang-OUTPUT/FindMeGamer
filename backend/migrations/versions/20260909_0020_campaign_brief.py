"""Activity-local promotion intent; preserve existing source and send snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "20260909_0020"
down_revision = "20260908_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("activities", sa.Column("campaign_brief", sa.Text(), nullable=True))
    op.add_column(
        "activities",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("activities", "revision")
    op.drop_column("activities", "campaign_brief")
