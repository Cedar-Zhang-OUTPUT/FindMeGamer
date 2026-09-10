"""Opt-in persistent one-click discovery, enrichment and matching."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260910_0022"
down_revision = "20260909_0021"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def ref(name, target, nullable=False):
    return sa.Column(
        name, pg.UUID(as_uuid=True), sa.ForeignKey(target), nullable=nullable
    )


def upgrade():
    op.create_table(
        "creator_searches",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        ref("activity_id", "activities.id"),
        ref("plan_id", "discovery_plans.id"),
        ref("query_id", "discovery_queries.id", True),
        ref("batch_id", "discovery_batches.id", True),
        ref("evaluation_id", "discovery_evaluation_runs.id", True),
        ref("parent_search_id", "creator_searches.id", True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="planning"),
        sa.Column(
            "stop_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "scope_frozen", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "acknowledge_unknown",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "excluded_candidate_ids",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error_code", sa.String(64)),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    op.create_index(
        "ix_creator_searches_activity_id", "creator_searches", ["activity_id"]
    )
    op.create_table(
        "creator_search_units",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        ref("search_id", "creator_searches.id"),
        ref("candidate_id", "discovery_candidates.id"),
        ref("creator_id", "creator_profiles.id"),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("identity_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "profile_status", sa.String(32), nullable=False, server_default="pending"
        ),
        sa.Column(
            "email_status", sa.String(32), nullable=False, server_default="pending"
        ),
        ref("analysis_job_id", "analysis_jobs.id", True),
        sa.Column(
            "owns_analysis_job", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("profile_error_code", sa.String(64)),
        sa.Column("email_error_code", sa.String(64)),
        *timestamps(),
        sa.UniqueConstraint(
            "search_id", "candidate_id", name="uq_creator_search_candidate"
        ),
    )
    op.create_index(
        "ix_creator_search_units_search_id", "creator_search_units", ["search_id"]
    )


def downgrade():
    op.drop_table("creator_search_units")
    op.drop_table("creator_searches")
