"""Activity-owned final sending, separate from legacy Match campaigns."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260908_0017"
down_revision = "20260908_0016"
branch_labels = None
depends_on = None


def times():
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade():
    op.create_table(
        "activity_send_batches",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "activity_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("activities.id"),
            nullable=False,
        ),
        sa.Column(
            "composition_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("outreach_compositions.id"),
            nullable=False,
        ),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("qualification_snapshot", pg.JSONB(), nullable=False),
        *times(),
    )
    op.create_index(
        "ix_activity_send_batches_activity_id", "activity_send_batches", ["activity_id"]
    )
    op.create_table(
        "activity_deliveries",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "send_batch_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("activity_send_batches.id"),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("outreach_drafts.id"),
            nullable=False,
        ),
        sa.Column(
            "recipient_snapshot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("activity_recipient_snapshots.id"),
            nullable=False,
        ),
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        sa.Column("input_order", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        *[
            sa.Column(name, sa.DateTime(timezone=True))
            for name in ("lease_expires_at", "sending_at", "sent_at", "failed_at")
        ],
        sa.Column("error_code", sa.String(64)),
        sa.Column(
            "retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "resolution",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *times(),
        sa.UniqueConstraint(
            "send_batch_id", "draft_id", name="uq_activity_delivery_batch_draft"
        ),
    )
    op.create_index(
        "ix_activity_deliveries_send_batch_id", "activity_deliveries", ["send_batch_id"]
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM activity_send_batches)")
    ):
        raise RuntimeError(
            "Back up Activity sending records before downgrading populated tables."
        )
    op.drop_table("activity_deliveries")
    op.drop_table("activity_send_batches")
