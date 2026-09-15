"""Persist price snapshots; historical unpriced records remain unknown."""

from alembic import op
import sqlalchemy as sa

revision = "0005_cost"
down_revision = "0004_usage"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("usage_records", sa.Column("cost", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("usage_records", "cost")
