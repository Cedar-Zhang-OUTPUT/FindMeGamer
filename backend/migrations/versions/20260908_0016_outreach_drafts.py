"""Immutable game-bound outreach template versions and draft inputs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260908_0016"
down_revision = "20260908_0015"
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
        "outreach_template_versions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "game_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("game_profiles.id"),
            nullable=False,
        ),
        sa.Column("builtin_key", sa.String(64)),
        sa.Column("request_id", pg.UUID(as_uuid=True), unique=True),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(998), nullable=False),
        sa.Column("fixed_fragments", pg.JSONB(), nullable=False),
        sa.Column("fixed_hash", sa.String(64), nullable=False),
        sa.Column("source_metadata", pg.JSONB(), nullable=False),
        *times(),
        sa.UniqueConstraint(
            "game_id", "builtin_key", name="uq_outreach_game_builtin_template"
        ),
    )
    op.create_index(
        "ix_outreach_template_versions_game_id",
        "outreach_template_versions",
        ["game_id"],
    )
    op.create_table(
        "outreach_compositions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "activity_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("activities.id"),
            nullable=False,
        ),
        sa.Column(
            "recipient_batch_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("activity_recipient_batches.id"),
            nullable=False,
        ),
        sa.Column(
            "template_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("outreach_template_versions.id"),
            nullable=False,
        ),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        *times(),
    )
    op.create_index(
        "ix_outreach_compositions_activity_id", "outreach_compositions", ["activity_id"]
    )
    op.create_table(
        "outreach_drafts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "composition_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("outreach_compositions.id"),
            nullable=False,
        ),
        sa.Column(
            "recipient_snapshot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("activity_recipient_snapshots.id"),
            nullable=False,
        ),
        sa.Column("input_order", sa.Integer(), nullable=False),
        sa.Column("input_data", pg.JSONB(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("values", pg.JSONB()),
        sa.Column("error_code", sa.String(64)),
        sa.Column(
            "sender_facts",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        *times(),
        sa.UniqueConstraint(
            "composition_id",
            "recipient_snapshot_id",
            name="uq_composition_recipient_draft",
        ),
    )
    op.create_index(
        "ix_outreach_drafts_composition_id", "outreach_drafts", ["composition_id"]
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM outreach_template_versions)")
    ):
        raise RuntimeError(
            "Back up outreach templates and drafts before downgrading populated tables."
        )
    op.drop_table("outreach_drafts")
    op.drop_table("outreach_compositions")
    op.drop_table("outreach_template_versions")
