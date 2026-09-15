"""Initial access tokens, independent of the old application schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001_tokens"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "access_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("access_tokens")
