"""Persist named candidate subsets without copying Profile history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260908_0015"
down_revision = "20260908_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saved_candidate_sets",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "query_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("discovery_queries.id"),
            nullable=False,
        ),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("candidate_ids", pg.JSONB(), nullable=False),
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
    )
    op.create_index(
        "ix_saved_candidate_sets_query_id", "saved_candidate_sets", ["query_id"]
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM saved_candidate_sets)")
    ):
        raise RuntimeError(
            "Back up named candidate sets before downgrading populated tables."
        )
    op.drop_table("saved_candidate_sets")
