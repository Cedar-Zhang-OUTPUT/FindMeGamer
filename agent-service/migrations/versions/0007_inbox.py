"""Replace invitation buttons with real mailbox replies (maintenance window)."""

from alembic import op
import sqlalchemy as sa

revision = "0007_inbox"
down_revision = "0006_outreach"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_replies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "send_id", sa.String(36), sa.ForeignKey("email_sends.id"), nullable=False
        ),
        sa.Column("message_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("sender", sa.String(254), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("received_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("send_id", "message_key"),
    )
    op.create_index("ix_email_replies_send_id", "email_replies", ["send_id"])
    op.create_table(
        "inbox_cursors",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("uidvalidity", sa.String(40), nullable=False),
        sa.Column("last_uid", sa.Integer(), nullable=False),
        sa.Column("last_success", sa.String(40)),
        sa.Column("error", sa.String(60)),
    )
    with op.batch_alter_table("outreach_recipients") as batch:
        batch.drop_column("response_digest")
        batch.drop_column("response")
        batch.drop_column("responded_at")


def downgrade():
    raise RuntimeError(
        "Restore the pre-migration backup to recover retired invitation-response data."
    )
