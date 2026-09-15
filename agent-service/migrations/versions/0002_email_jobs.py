"""Independent durable email jobs."""

from alembic import op
import sqlalchemy as sa

revision = "0002_email_jobs"
down_revision = "0001_tokens"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "token_id", sa.String(36), sa.ForeignKey("access_tokens.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("checkpoints", sa.JSON(), nullable=False),
        sa.Column("emails", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("lease", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_id", "idempotency_key"),
    )
    op.create_index("ix_email_jobs_state", "email_jobs", ["state"])


def downgrade():
    op.drop_index("ix_email_jobs_state", table_name="email_jobs")
    op.drop_table("email_jobs")
