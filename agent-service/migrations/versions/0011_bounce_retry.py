"""Durable one-shot bounce retries, with a rollout cutoff for historical mail."""

from alembic import op
import sqlalchemy as sa

revision = "0011_bounce_retry"
down_revision = "0010_bounce_safety"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "email_sender_safety",
        sa.Column(
            "retry_enabled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    safety = sa.table(
        "email_sender_safety", sa.column("retry_enabled_at", sa.DateTime(timezone=True))
    )
    op.execute(safety.update().values(retry_enabled_at=sa.func.now()))
    with op.batch_alter_table("email_sender_safety") as batch:
        batch.alter_column(
            "retry_enabled_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
    op.create_table(
        "email_bounce_retries",
        sa.Column(
            "original_send_id",
            sa.String(36),
            sa.ForeignKey("email_sends.id"),
            primary_key=True,
        ),
        sa.Column(
            "preview_id",
            sa.String(36),
            sa.ForeignKey("email_previews.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(100), nullable=True),
    )


def downgrade():
    raise RuntimeError(
        "Do not discard retry history; restore a reviewed backup instead."
    )
