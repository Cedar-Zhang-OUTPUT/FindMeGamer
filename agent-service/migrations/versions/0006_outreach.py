"""Durable approved outreach tasks and isolated recipient responses."""
from alembic import op
import sqlalchemy as sa

revision = "0006_outreach"
down_revision = "0005_cost"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("outreach_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_id", sa.String(36), sa.ForeignKey("access_tokens.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("run_id", sa.String(100), nullable=False),
        sa.Column("template", sa.JSON(), nullable=False),
        sa.UniqueConstraint("token_id", "idempotency_key"))
    op.create_table("outreach_recipients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("outreach_tasks.id"), nullable=False),
        sa.Column("creator_id", sa.String(300), nullable=False),
        sa.Column("preview_id", sa.String(36), sa.ForeignKey("email_previews.id"), unique=True, nullable=False),
        sa.Column("response_digest", sa.String(64), unique=True, nullable=False),
        sa.Column("response", sa.String(3), nullable=True),
        sa.Column("responded_at", sa.String(40), nullable=True))
    op.create_index("ix_outreach_recipients_task_id", "outreach_recipients", ["task_id"])


def downgrade():
    op.drop_table("outreach_recipients")
    op.drop_table("outreach_tasks")
