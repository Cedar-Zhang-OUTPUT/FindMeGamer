"""Immutable previews and unique send reservations."""

from alembic import op
import sqlalchemy as sa

revision = "0003_email_sends"
down_revision = "0002_email_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_previews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "token_id", sa.String(36), sa.ForeignKey("access_tokens.id"), nullable=False
        ),
        sa.Column("template_id", sa.String(100), nullable=False),
        sa.Column("template_version", sa.String(40), nullable=False),
        sa.Column("message", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "email_sends",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "token_id", sa.String(36), sa.ForeignKey("access_tokens.id"), nullable=False
        ),
        sa.Column(
            "preview_id",
            sa.String(36),
            sa.ForeignKey("email_previews.id"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_id", "idempotency_key"),
        sa.UniqueConstraint("preview_id"),
    )


def downgrade():
    op.drop_table("email_sends")
    op.drop_table("email_previews")
