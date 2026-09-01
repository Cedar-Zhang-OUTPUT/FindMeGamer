"""Create the initial Library and Analyze schema.

Revision ID: 20260902_0001
Revises:
Create Date: 2026-09-02
"""

from collections.abc import Sequence
from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260902_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHARED_SETTINGS_ID = UUID("00000000-0000-0000-0000-000000000001")
target_type_enum = sa.Enum(
    "game",
    "creator",
    name="target_type",
    native_enum=False,
    create_constraint=False,
    length=16,
)
job_mode_enum = sa.Enum(
    "create",
    "reanalyze",
    name="job_mode",
    native_enum=False,
    create_constraint=False,
    length=16,
)
job_status_enum = sa.Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    name="job_status",
    native_enum=False,
    create_constraint=False,
    length=16,
)
analysis_stage_enum = sa.Enum(
    "fetching_data",
    "analyzing",
    "finalizing",
    name="analysis_stage",
    native_enum=False,
    create_constraint=False,
    length=32,
)


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def profile_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("sort_name", sa.String(length=255), nullable=False),
        sa.Column("current_facts", postgresql.JSONB(), nullable=False),
        sa.Column("analysis", postgresql.JSONB(), nullable=False),
        sa.Column("brief", postgresql.JSONB(), nullable=False),
        sa.Column("source_status", postgresql.JSONB(), nullable=False),
        sa.Column("model_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("prompt_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("favorite", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_analyzed_at", sa.DateTime(timezone=True)),
        sa.Column("next_analysis_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )


def upgrade() -> None:
    op.create_table(
        "game_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("steam_app_id", sa.String(length=32), nullable=False),
        *profile_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("steam_app_id"),
    )
    op.create_index("ix_game_profiles_sort_name", "game_profiles", ["sort_name"])
    op.create_index(
        "ix_game_profiles_next_analysis_at", "game_profiles", ["next_analysis_at"]
    )

    op.create_table(
        "creator_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("youtube_channel_id", sa.String(length=128), nullable=False),
        sa.Column("manual_notes", sa.Text()),
        *profile_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("youtube_channel_id"),
    )
    op.create_index("ix_creator_profiles_sort_name", "creator_profiles", ["sort_name"])
    op.create_index(
        "ix_creator_profiles_next_analysis_at",
        "creator_profiles",
        ["next_analysis_at"],
    )

    op.create_table(
        "creator_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("is_manual", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "validation_state",
            sa.String(length=32),
            server_default="unverified",
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["creator_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_creator_contacts_creator_id", "creator_contacts", ["creator_id"])

    op.create_table(
        "analysis_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", target_type_enum, nullable=False),
        sa.Column("canonical_target_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("mode", job_mode_enum, server_default="create", nullable=False),
        sa.Column("status", job_status_enum, server_default="queued", nullable=False),
        sa.Column("stage", analysis_stage_enum),
        sa.Column("completed_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128)),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("result_payload", postgresql.JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint("target_type IN ('game', 'creator')", name="target_type"),
        sa.CheckConstraint("mode IN ('create', 'reanalyze')", name="job_mode"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="job_status",
        ),
        sa.CheckConstraint(
            "stage IS NULL OR stage IN ('fetching_data', 'analyzing', 'finalizing')",
            name="analysis_stage",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_analysis_jobs_active_target",
        "analysis_jobs",
        ["target_type", "canonical_target_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "shared_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workspace_name",
            sa.String(length=255),
            server_default="Find Me Gamer",
            nullable=False,
        ),
        sa.Column("creator_interval_days", sa.Integer(), nullable=False),
        sa.Column("game_interval_days", sa.Integer(), nullable=False),
        sa.Column("recommended_match_threshold", sa.Numeric(4, 2), nullable=False),
        sa.Column("smtp_rate_per_minute", sa.Integer(), nullable=False),
        sa.Column("service_connection_state", postgresql.JSONB(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "service_secrets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service", sa.String(length=64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("last_test_succeeded", sa.Boolean()),
        sa.Column("last_test_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service"),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(
        "ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"]
    )

    shared_settings = sa.table(
        "shared_settings",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("workspace_name", sa.String()),
        sa.column("creator_interval_days", sa.Integer()),
        sa.column("game_interval_days", sa.Integer()),
        sa.column("recommended_match_threshold", sa.Numeric()),
        sa.column("smtp_rate_per_minute", sa.Integer()),
        sa.column("service_connection_state", postgresql.JSONB()),
    )
    op.bulk_insert(
        shared_settings,
        [
            {
                "id": SHARED_SETTINGS_ID,
                "workspace_name": "Find Me Gamer",
                "creator_interval_days": 14,
                "game_interval_days": 30,
                "recommended_match_threshold": 0.70,
                "smtp_rate_per_minute": 10,
                "service_connection_state": {},
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_expires_at", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_table("service_secrets")
    op.drop_table("shared_settings")
    op.drop_index("uq_analysis_jobs_active_target", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
    op.drop_index("ix_creator_contacts_creator_id", table_name="creator_contacts")
    op.drop_table("creator_contacts")
    op.drop_index("ix_creator_profiles_next_analysis_at", table_name="creator_profiles")
    op.drop_index("ix_creator_profiles_sort_name", table_name="creator_profiles")
    op.drop_table("creator_profiles")
    op.drop_index("ix_game_profiles_next_analysis_at", table_name="game_profiles")
    op.drop_index("ix_game_profiles_sort_name", table_name="game_profiles")
    op.drop_table("game_profiles")
