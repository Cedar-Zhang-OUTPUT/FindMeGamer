"""Add isolated Activity and durable Discovery tables; preserve existing Library."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260908_0010"
down_revision = "20260908_0009"
branch_labels = None
depends_on = None


def ident():
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True)


def fk(name, target):
    return sa.Column(name, pg.UUID(as_uuid=True), sa.ForeignKey(target), nullable=False)


def json(name):
    return sa.Column(
        name, pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    )


def count(name):
    return sa.Column(name, sa.Integer(), nullable=False, server_default=sa.text("0"))


def times():
    return [
        sa.Column(
            n, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        )
        for n in ("created_at", "updated_at")
    ]


def status(value="queued"):
    return sa.Column("status", sa.String(32), nullable=False, server_default=value)


def upgrade():
    op.create_table(
        "activities",
        ident(),
        fk("game_id", "game_profiles.id"),
        sa.Column("name", sa.String(255), nullable=False),
        json("source_snapshot"),
        *times(),
    )
    op.create_index("ix_activities_game_id", "activities", ["game_id"])
    op.create_table(
        "discovery_queries",
        ident(),
        fk("activity_id", "activities.id"),
        json("conditions"),
        json("source_snapshot"),
        status(),
        sa.Column(
            "stop_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        json("provider_states"),
        count("result_count"),
        count("requests_reserved"),
        count("scanned_reserved"),
        *times(),
    )
    op.create_index(
        "ix_discovery_queries_activity_id", "discovery_queries", ["activity_id"]
    )
    op.create_table(
        "discovery_batches",
        ident(),
        fk("query_id", "discovery_queries.id"),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        status(),
        count("initial_result_count"),
        sa.Column("target_count", sa.Integer(), nullable=False),
        count("requests_reserved"),
        count("scanned_reserved"),
        sa.Column("reason", sa.String(64)),
        *times(),
        sa.UniqueConstraint("query_id", "ordinal", name="uq_discovery_batch_ordinal"),
    )
    op.create_index("ix_discovery_batches_query_id", "discovery_batches", ["query_id"])
    op.create_table(
        "discovery_attempts",
        ident(),
        fk("batch_id", "discovery_batches.id"),
        sa.Column("platform", sa.String(32), nullable=False),
        json("input"),
        status("in_flight"),
        sa.Column("lease_token", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        count("requests_reserved"),
        count("scan_reserved"),
        json("outcome"),
        sa.Column("sequence", sa.Integer(), nullable=False),
        *times(),
        sa.UniqueConstraint(
            "batch_id", "sequence", name="uq_discovery_attempt_sequence"
        ),
    )
    op.create_index(
        "ix_discovery_attempts_batch_id", "discovery_attempts", ["batch_id"]
    )
    op.create_table(
        "discovery_candidates",
        ident(),
        fk("query_id", "discovery_queries.id"),
        fk("creator_id", "creator_profiles.id"),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        count("identity_revision"),
        json("account_snapshot"),
        json("filter_notes"),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "selected", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "query_id", "platform", "account_id", name="uq_discovery_candidate_account"
        ),
        sa.UniqueConstraint(
            "query_id", "ordinal", name="uq_discovery_candidate_ordinal"
        ),
    )
    op.create_index(
        "ix_discovery_candidates_query_id", "discovery_candidates", ["query_id"]
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM activities)")):
        raise RuntimeError(
            "Cannot discard Activity data; restore a pre-migration backup instead."
        )
    for name in (
        "discovery_candidates",
        "discovery_attempts",
        "discovery_batches",
        "discovery_queries",
        "activities",
    ):
        op.drop_table(name)
