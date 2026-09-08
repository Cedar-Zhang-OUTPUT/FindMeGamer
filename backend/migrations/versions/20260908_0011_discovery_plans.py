"""Add Activity-linked planning without changing existing profiles/queries."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260908_0011"
down_revision = "20260908_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discovery_plans",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "activity_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("activities.id"),
            nullable=False,
        ),
        sa.Column(
            "source_snapshot",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "conditions",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("output", pg.JSONB()),
        sa.Column("error_code", sa.String(64)),
        sa.Column(
            "retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "query_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("discovery_queries.id"),
            unique=True,
        ),
        *[
            sa.Column(
                n,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
            for n in ("created_at", "updated_at")
        ],
    )
    op.create_index(
        "ix_discovery_plans_activity_id", "discovery_plans", ["activity_id"]
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM discovery_plans)")):
        raise RuntimeError(
            "Back up planning records before downgrading this nonempty table."
        )
    op.drop_table("discovery_plans")
