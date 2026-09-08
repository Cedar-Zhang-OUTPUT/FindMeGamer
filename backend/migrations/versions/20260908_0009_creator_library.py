"""Add platform-specific Creator identities and editable contact/work layers."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from uuid import uuid4

revision = "20260908_0009"
down_revision = "20260908_0008"
branch_labels = None
depends_on = None


def _json_column(name):
    return sa.Column(
        name, postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    )


def upgrade() -> None:
    op.alter_column(
        "creator_profiles",
        "youtube_channel_id",
        existing_type=sa.String(128),
        nullable=True,
    )
    op.add_column(
        "creator_profiles",
        sa.Column("platform", sa.String(32), nullable=False, server_default="youtube"),
    )
    op.add_column(
        "creator_profiles",
        sa.Column("platform_account_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "creator_profiles",
        sa.Column(
            "identity_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "creator_profiles",
        sa.Column("identity_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("creator_profiles", _json_column("manual_overrides"))
    op.add_column(
        "creator_profiles",
        sa.Column(
            "manual_revision", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.create_unique_constraint(
        "uq_creator_profiles_platform_account",
        "creator_profiles",
        ["platform", "platform_account_id"],
    )
    op.create_check_constraint(
        "ck_creator_profiles_platform",
        "creator_profiles",
        "platform IN ('youtube', 'x', 'twitch', 'instagram')",
    )
    op.add_column("creator_contacts", _json_column("source_fields"))
    op.add_column(
        "creator_contacts",
        sa.Column(
            "identity_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column("creator_contacts", _json_column("manual_overrides"))
    op.execute(
        """UPDATE creator_contacts SET source_fields=jsonb_build_object(
        'email',email,'purpose',purpose,'source_url',source_url,
        'validation_state',validation_state,'is_active',is_active) WHERE NOT is_manual"""
    )
    op.drop_index("uq_creator_contacts_active_manual", table_name="creator_contacts")
    op.create_index(
        "uq_creator_contacts_active_manual_email",
        "creator_contacts",
        ["creator_id", sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("is_manual AND is_active"),
    )
    op.create_table(
        "creator_works",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "creator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("creator_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("source_content_id", sa.String(255), nullable=True),
        sa.Column(
            "identity_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        _json_column("source_fields"),
        _json_column("manual_overrides"),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("source_collected_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "creator_id",
            "identity_revision",
            "platform",
            "source_content_id",
            name="uq_creator_works_source_identity",
        ),
        sa.CheckConstraint(
            "platform IN ('youtube', 'x', 'twitch', 'instagram')",
            name="ck_creator_works_platform",
        ),
        sa.CheckConstraint(
            "origin IN ('manual', 'source')", name="ck_creator_works_origin"
        ),
    )
    op.create_index("ix_creator_works_creator_id", "creator_works", ["creator_id"])
    op.create_table(
        "creator_identity_bindings",
        sa.Column(
            "creator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("creator_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Backfill after DDL: existing deferred FK triggers must not block ALTER TABLE.
    _replace_succeeded_identity_validator(allow_history=True)
    op.execute("UPDATE creator_profiles SET platform_account_id=youtube_channel_id")
    _backfill_known_works()


def _backfill_known_works() -> None:
    connection = op.get_bind()
    works = sa.table(
        "creator_works",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("creator_id", postgresql.UUID(as_uuid=True)),
        sa.column("platform", sa.String()),
        sa.column("origin", sa.String()),
        sa.column("source_content_id", sa.String()),
        sa.column("source_collected_at", sa.DateTime(timezone=True)),
        sa.column("source_fields", postgresql.JSONB()),
    )
    for row in connection.execute(
        sa.text("SELECT id,current_facts,last_analyzed_at FROM creator_profiles")
    ).mappings():
        facts = row["current_facts"]
        videos = facts.get("representative_videos") if isinstance(facts, dict) else None
        if not isinstance(videos, list):
            continue
        seen = set()
        for video in videos:
            if not isinstance(video, dict):
                continue
            content_id, title = video.get("id"), video.get("title")
            if (
                not isinstance(content_id, str)
                or not content_id.strip()
                or not isinstance(title, str)
                or not title.strip()
                or content_id in seen
            ):
                continue
            seen.add(content_id)
            fields = {
                "content_id": content_id,
                "content_title": title,
                "source_url": f"https://www.youtube.com/watch?v={content_id}",
                "content_type": "unverified",
                "published_at": video.get("published_at"),
                "collected_at": (
                    row["last_analyzed_at"].isoformat()
                    if row["last_analyzed_at"]
                    else None
                ),
                "metrics": [
                    {"name": name, "value": video[key]}
                    for key, name in (
                        ("view_count", "views"),
                        ("like_count", "likes"),
                        ("comment_count", "comments"),
                    )
                    if type(video.get(key)) is int and video[key] >= 0
                ],
            }
            connection.execute(
                works.insert().values(
                    id=uuid4(),
                    creator_id=row["id"],
                    platform="youtube",
                    origin="source",
                    source_content_id=content_id,
                    source_collected_at=row["last_analyzed_at"],
                    source_fields=fields,
                )
            )


def _replace_succeeded_identity_validator(*, allow_history: bool) -> None:
    history = (
        """OR EXISTS (
        SELECT 1 FROM creator_identity_bindings AS binding
        WHERE binding.creator_id = profile.id
          AND binding.revision < profile.identity_revision
          AND binding.platform = 'youtube'
          AND binding.account_id = checked_target_id
          AND binding.canonical_url = checked_canonical_url
    )"""
        if allow_history
        else ""
    )
    # Both existing deferred triggers call this shared predicate. Preserve exact
    # Game validation and canonical YouTube syntax, adding only proven old binds.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION analysis_job_succeeded_profile_is_valid(
            checked_target_type text, checked_profile_id uuid,
            checked_target_id text, checked_canonical_url text
        ) RETURNS boolean LANGUAGE sql STABLE AS $$
            SELECT CASE checked_target_type
                WHEN 'game' THEN
                    CASE WHEN checked_target_id ~ '^[1-9][0-9]{{0,9}}$'
                        THEN checked_target_id::bigint <= 2147483647 ELSE false END
                    AND checked_canonical_url = 'https://store.steampowered.com/app/' || checked_target_id
                    AND EXISTS (
                        SELECT 1 FROM game_profiles AS profile
                        WHERE profile.id = checked_profile_id
                          AND profile.steam_app_id = checked_target_id
                          AND profile.canonical_url = checked_canonical_url
                    )
                WHEN 'creator' THEN
                    checked_target_id ~ '^UC[A-Za-z0-9_-]{{6,126}}$'
                    AND checked_canonical_url = 'https://www.youtube.com/channel/' || checked_target_id
                    AND EXISTS (
                        SELECT 1 FROM creator_profiles AS profile
                        WHERE profile.id = checked_profile_id
                          AND ((profile.youtube_channel_id = checked_target_id
                              AND profile.canonical_url = checked_canonical_url)
                              {history})
                    )
                ELSE false
            END
        $$
    """
    )


def downgrade() -> None:
    has_new_data = op.get_bind().scalar(
        sa.text(
            """SELECT
        EXISTS (SELECT 1 FROM creator_profiles WHERE platform <> 'youtube' OR youtube_channel_id IS NULL
            OR identity_revision > 0 OR manual_overrides <> '{}'::jsonb OR (platform_account_id IS NOT NULL AND platform_account_id <> youtube_channel_id))
        OR EXISTS (SELECT 1 FROM creator_works)
        OR EXISTS (SELECT 1 FROM creator_identity_bindings)
        OR EXISTS (SELECT 1 FROM creator_contacts WHERE identity_revision > 0 OR manual_overrides <> '{}'::jsonb)
        OR EXISTS (SELECT 1 FROM creator_contacts WHERE is_manual AND is_active GROUP BY creator_id HAVING count(*) > 1)
    """
        )
    )
    if has_new_data:
        raise RuntimeError(
            "Cannot downgrade while creator library data exists; restore a pre-migration backup instead."
        )
    _replace_succeeded_identity_validator(allow_history=False)
    op.drop_table("creator_works")
    op.drop_table("creator_identity_bindings")
    op.drop_index(
        "uq_creator_contacts_active_manual_email", table_name="creator_contacts"
    )
    op.create_index(
        "uq_creator_contacts_active_manual",
        "creator_contacts",
        ["creator_id"],
        unique=True,
        postgresql_where=sa.text("is_manual AND is_active"),
    )
    op.drop_column("creator_contacts", "manual_overrides")
    op.drop_column("creator_contacts", "source_fields")
    op.drop_column("creator_contacts", "identity_revision")
    op.drop_constraint(
        "ck_creator_profiles_platform", "creator_profiles", type_="check"
    )
    op.drop_constraint(
        "uq_creator_profiles_platform_account", "creator_profiles", type_="unique"
    )
    for name in (
        "manual_revision",
        "manual_overrides",
        "identity_revision",
        "identity_changed_at",
        "platform_account_id",
        "platform",
    ):
        op.drop_column("creator_profiles", name)
    op.alter_column(
        "creator_profiles",
        "youtube_channel_id",
        existing_type=sa.String(128),
        nullable=False,
    )
