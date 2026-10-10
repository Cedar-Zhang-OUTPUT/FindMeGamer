"""Shared, durable per-sender send spacing; no changes to historical receipts."""

from alembic import op
import sqlalchemy as sa

revision = "0008_send_pacing"
down_revision = "0007_inbox"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_send_gates",
        sa.Column("sender", sa.String(254), primary_key=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_id", sa.String(36), nullable=True),
    )


def downgrade():
    op.drop_table("email_send_gates")
