"""Add stable mailbox references without modifying frozen historical data."""

from alembic import op
import sqlalchemy as sa

revision = "0012_mailbox_identity"
down_revision = "0011_bounce_retry"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mailbox_identities",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("sender", sa.String(254), nullable=False, unique=True),
    )
    for table in ("email_previews", "outreach_tasks"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("mailbox_id", sa.String(40), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_mailbox", "mailbox_identities", ["mailbox_id"], ["id"]
            )


def downgrade():
    raise RuntimeError(
        "Do not discard mailbox identity history; restore a reviewed backup instead."
    )
