"""Nullable provider diagnostics; preserve historical receipts and task states."""

from alembic import op
import sqlalchemy as sa

revision = "0009_mail_diagnostics"
down_revision = "0008_send_pacing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_sends", sa.Column("diagnostics", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("email_sends", "diagnostics")
