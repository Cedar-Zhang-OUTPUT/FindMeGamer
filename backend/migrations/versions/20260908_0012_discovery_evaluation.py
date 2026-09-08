"""Add candidate evaluation checkpoints without changing v1 Match or Profiles."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260908_0012"
down_revision = "20260908_0011"
branch_labels = None
depends_on = None


def ident():
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True)


def fk(name, target):
    return sa.Column(name, pg.UUID(as_uuid=True), sa.ForeignKey(target), nullable=False)


def obj(name):
    return sa.Column(
        name, pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
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
        "discovery_evaluation_runs",
        ident(),
        fk("query_id", "discovery_queries.id"),
        obj("source_snapshot"),
        obj("conditions"),
        obj("game_brief"),
        sa.Column("game_fingerprint", sa.String(64), nullable=False),
        sa.Column("method_version", sa.String(64), nullable=False),
        obj("models"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="screening"),
        *times(),
    )
    op.create_index(
        "ix_discovery_evaluation_runs_query_id",
        "discovery_evaluation_runs",
        ["query_id"],
    )
    op.create_table(
        "discovery_evaluation_items",
        ident(),
        fk("run_id", "discovery_evaluation_runs.id"),
        fk("candidate_id", "discovery_candidates.id"),
        fk("creator_id", "creator_profiles.id"),
        sa.Column("input_order", sa.Integer(), nullable=False),
        obj("snapshot"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "identity_changed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("screening_selected", sa.Boolean()),
        sa.Column("match_brief", pg.JSONB()),
        sa.Column("score", sa.Integer()),
        sa.UniqueConstraint("run_id", "candidate_id", name="uq_evaluation_candidate"),
    )
    op.create_index(
        "ix_discovery_evaluation_items_run_id", "discovery_evaluation_items", ["run_id"]
    )
    op.create_table(
        "discovery_evaluation_steps",
        ident(),
        fk("run_id", "discovery_evaluation_runs.id"),
        sa.Column("step_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("item_ids", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("output", pg.JSONB()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        *times(),
        sa.UniqueConstraint("run_id", "step_key", name="uq_evaluation_step"),
    )
    op.create_index(
        "ix_discovery_evaluation_steps_run_id", "discovery_evaluation_steps", ["run_id"]
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM discovery_evaluation_runs)")
    ):
        raise RuntimeError(
            "Back up evaluation records before downgrading nonempty tables."
        )
    op.drop_table("discovery_evaluation_steps")
    op.drop_table("discovery_evaluation_items")
    op.drop_table("discovery_evaluation_runs")
