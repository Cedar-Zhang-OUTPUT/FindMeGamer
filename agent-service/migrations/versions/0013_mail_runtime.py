"""Start mail dispatch and sending closed until explicit maintenance release."""

from alembic import op
import sqlalchemy as sa

revision = "0013_mail_runtime"
down_revision = "0012_mailbox_identity"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "mail_runtime",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "dispatch_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "send_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.CheckConstraint("id = 1", name="mail_runtime_singleton"),
    )
    op.bulk_insert(table, [{"id": 1, "dispatch_enabled": False, "send_enabled": False}])


def downgrade():
    raise RuntimeError(
        "Do not discard the mail maintenance gate; restore a reviewed backup."
    )
