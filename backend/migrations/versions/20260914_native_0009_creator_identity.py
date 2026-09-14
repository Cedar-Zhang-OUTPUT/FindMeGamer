"""Add platform-neutral creator identity without rewriting existing records."""

from alembic import op
import sqlalchemy as sa

revision = "20260914_native_0009"
down_revision = "20260914_native_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "creator_profiles", sa.Column("platform", sa.String(16), nullable=True)
    )
    op.add_column(
        "creator_profiles",
        sa.Column("platform_account_id", sa.String(128), nullable=True),
    )
    op.execute(
        "UPDATE creator_profiles SET platform = 'youtube', platform_account_id = youtube_channel_id"
    )
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.alter_column("creator_profiles", "platform", nullable=False)
    op.alter_column("creator_profiles", "platform_account_id", nullable=False)
    op.alter_column("creator_profiles", "youtube_channel_id", nullable=True)
    op.create_unique_constraint(
        "uq_creator_profiles_platform_account",
        "creator_profiles",
        ["platform", "platform_account_id"],
    )


def downgrade():
    # Refuse an incompatible downgrade instead of deleting non-YouTube profiles.
    op.alter_column("creator_profiles", "youtube_channel_id", nullable=False)
    op.drop_constraint(
        "uq_creator_profiles_platform_account", "creator_profiles", type_="unique"
    )
    op.drop_column("creator_profiles", "platform_account_id")
    op.drop_column("creator_profiles", "platform")
