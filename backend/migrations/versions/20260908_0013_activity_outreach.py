"""Persist human Activity choices and immutable recipient lists."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260908_0013"
down_revision = "20260908_0012"
branch_labels = None
depends_on = None


def ident():
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True)


def fk(name, target, nullable=False):
    return sa.Column(
        name, pg.UUID(as_uuid=True), sa.ForeignKey(target), nullable=nullable
    )


def times():
    return [
        sa.Column(
            n, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        )
        for n in ("created_at", "updated_at")
    ]


def upgrade():
    op.create_table(
        "activity_selections",
        ident(),
        fk("activity_id", "activities.id"),
        fk("creator_id", "creator_profiles.id"),
        fk("candidate_id", "discovery_candidates.id"),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column(
            "identity_revision", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        fk("contact_id", "creator_contacts.id", True),
        sa.Column("contact_snapshot", pg.JSONB()),
        fk("evaluation_item_id", "discovery_evaluation_items.id", True),
        sa.Column(
            "work_ids",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "name_confirmation",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *times(),
        sa.UniqueConstraint(
            "activity_id", "platform", "account_id", name="uq_activity_selected_account"
        ),
    )
    op.create_index(
        "ix_activity_selections_activity_id", "activity_selections", ["activity_id"]
    )
    op.create_table(
        "activity_recipient_batches",
        ident(),
        fk("activity_id", "activities.id"),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        *times(),
    )
    op.create_index(
        "ix_activity_recipient_batches_activity_id",
        "activity_recipient_batches",
        ["activity_id"],
    )
    op.add_column(
        "activity_recipient_batches",
        sa.Column(
            "source_snapshot",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_table(
        "activity_recipient_snapshots",
        ident(),
        fk("batch_id", "activity_recipient_batches.id"),
        fk("selection_id", "activity_selections.id"),
        sa.Column(
            "snapshot",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("context_token", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "batch_id", "selection_id", name="uq_batch_selected_recipient"
        ),
    )
    op.create_index(
        "ix_activity_recipient_snapshots_batch_id",
        "activity_recipient_snapshots",
        ["batch_id"],
    )
    op.add_column(
        "activity_recipient_snapshots",
        sa.Column("input_order", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM activity_selections) OR EXISTS(SELECT 1 FROM activity_recipient_batches)"
        )
    ):
        raise RuntimeError(
            "Back up Activity preparation before downgrading populated tables."
        )
    op.drop_table("activity_recipient_snapshots")
    op.drop_table("activity_recipient_batches")
    op.drop_table("activity_selections")
