"""Durable per-run usage reservations and email job attribution."""

from alembic import op
import sqlalchemy as sa

revision = "0004_usage"
down_revision = "0003_email_sends"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_jobs", sa.Column("run_id", sa.String(100), nullable=True))
    op.create_table(
        "usage_records",
        sa.Column("request_id", sa.String(100), primary_key=True),
        sa.Column(
            "token_id", sa.String(36), sa.ForeignKey("access_tokens.id"), nullable=False
        ),
        sa.Column("run_id", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("operation", sa.String(200), nullable=False),
        sa.Column("status", sa.String(100), nullable=False),
        sa.Column("resource_counts", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_records_token_id", "usage_records", ["token_id"])
    op.create_index("ix_usage_records_run_id", "usage_records", ["run_id"])


def downgrade():
    op.drop_table("usage_records")
    op.drop_column("email_jobs", "run_id")
