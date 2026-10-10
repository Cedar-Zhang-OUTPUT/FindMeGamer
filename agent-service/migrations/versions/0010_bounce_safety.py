"""Structured delivery reports and a durable per-sender sending hold."""

from alembic import op
import sqlalchemy as sa

revision = "0010_bounce_safety"
down_revision = "0009_mail_diagnostics"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_replies", sa.Column("diagnostics", sa.JSON(), nullable=True))
    op.create_table(
        "email_sender_safety",
        sa.Column("sender", sa.String(254), primary_key=True),
        sa.Column("reason", sa.String(60), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    raise RuntimeError(
        "Do not discard sender safety holds; restore a reviewed backup instead."
    )
