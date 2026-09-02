"""Add the Match and Outreach persistence schema.

Revision ID: 20260902_0005
Revises: 20260902_0004
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260902_0005"
down_revision: str | None = "20260902_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


match_status_enum = sa.Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    "superseded",
    name="match_status",
    native_enum=False,
    create_constraint=False,
    length=16,
)
match_stage_enum = sa.Enum(
    "screening",
    "pairwise",
    "ranking",
    name="match_stage",
    native_enum=False,
    create_constraint=False,
    length=16,
)
pairwise_state_enum = sa.Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    name="match_pairwise_state",
    native_enum=False,
    create_constraint=False,
    length=16,
)
result_group_enum = sa.Enum(
    "recommended",
    "other",
    name="match_result_group",
    native_enum=False,
    create_constraint=False,
    length=16,
)
qualitative_label_enum = sa.Enum(
    "Strong Match",
    "Good Match",
    "Limited Match",
    name="match_qualitative_label",
    native_enum=False,
    create_constraint=False,
    length=16,
)
send_batch_state_enum = sa.Enum(
    "queued",
    "sending",
    "sent",
    "partially_failed",
    "failed",
    name="send_batch_state",
    native_enum=False,
    create_constraint=False,
    length=20,
)
delivery_send_state_enum = sa.Enum(
    "queued",
    "sending",
    "sent",
    "failed",
    name="delivery_send_state",
    native_enum=False,
    create_constraint=False,
    length=16,
)
delivery_response_state_enum = sa.Enum(
    "no_response",
    "accepted",
    "declined",
    name="delivery_response_state",
    native_enum=False,
    create_constraint=False,
    length=16,
)
campaign_response_state_enum = sa.Enum(
    "no_response",
    "accepted",
    "declined",
    name="campaign_response_state",
    native_enum=False,
    create_constraint=False,
    length=16,
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


def upgrade() -> None:
    op.create_check_constraint(
        "ck_shared_settings_recommended_match_threshold",
        "shared_settings",
        "recommended_match_threshold BETWEEN 0 AND 1",
    )
    op.create_check_constraint(
        "ck_shared_settings_smtp_rate_per_minute",
        "shared_settings",
        "smtp_rate_per_minute BETWEEN 1 AND 60",
    )

    op.create_table(
        "match_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("locked_game_brief", postgresql.JSONB()),
        sa.Column("shuffle_seed", sa.BigInteger(), nullable=False),
        sa.Column(
            "recommended_match_threshold",
            sa.Numeric(precision=5, scale=4),
            nullable=False,
        ),
        sa.Column("status", match_status_enum, server_default="queued", nullable=False),
        sa.Column(
            "stage", match_stage_enum, server_default="screening", nullable=False
        ),
        sa.Column("completed_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128)),
        sa.Column("input_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ranking_enqueued_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True)),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')",
            name="ck_match_tasks_status",
        ),
        sa.CheckConstraint(
            "stage IN ('screening', 'pairwise', 'ranking')",
            name="ck_match_tasks_stage",
        ),
        sa.CheckConstraint(
            "recommended_match_threshold BETWEEN 0 AND 1",
            name="ck_match_tasks_threshold",
        ),
        sa.CheckConstraint(
            "completed_units >= 0",
            name="ck_match_tasks_completed_units_nonnegative",
        ),
        sa.CheckConstraint(
            "total_units >= 0", name="ck_match_tasks_total_units_nonnegative"
        ),
        sa.CheckConstraint(
            "result_count >= 0", name="ck_match_tasks_result_count_nonnegative"
        ),
        sa.CheckConstraint(
            "completed_units <= total_units",
            name="ck_match_tasks_completed_not_above_total",
        ),
        sa.CheckConstraint(
            "result_count <= total_units",
            name="ck_match_tasks_result_not_above_total",
        ),
        sa.CheckConstraint(
            "((error_code IS NULL AND error_message IS NULL) OR "
            "(error_code IS NOT NULL AND error_message IS NOT NULL)) "
            "AND (status IN ('failed', 'superseded') OR error_code IS NULL) "
            "AND (status = 'failed' OR NOT retryable)",
            name="ck_match_tasks_error_shape",
        ),
        sa.CheckConstraint(
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL) "
            "OR (status = 'running' AND started_at IS NOT NULL "
            "AND completed_at IS NULL) "
            "OR (status = 'succeeded' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL) "
            "OR (status = 'failed' AND completed_at IS NOT NULL) "
            "OR (status = 'superseded' AND completed_at IS NOT NULL)",
            name="ck_match_tasks_status_shape",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at "
            "AND input_expires_at >= created_at "
            "AND (started_at IS NULL OR started_at >= created_at) "
            "AND (completed_at IS NULL OR completed_at >= COALESCE(started_at, created_at)) "
            "AND (ranking_enqueued_at IS NULL "
            "OR ranking_enqueued_at >= COALESCE(started_at, created_at))",
            name="ck_match_tasks_timestamp_shape",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["game_profiles.id"],
            name="fk_match_tasks_game",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["match_tasks.id"],
            name="fk_match_tasks_supersedes",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supersedes_id", name="uq_match_tasks_supersedes_id"),
    )
    op.create_index("ix_match_tasks_game_id", "match_tasks", ["game_id"])
    op.create_index("ix_match_tasks_status", "match_tasks", ["status"])
    op.create_index("ix_match_tasks_updated_at_id", "match_tasks", ["updated_at", "id"])
    op.create_index("ix_match_tasks_supersedes_id", "match_tasks", ["supersedes_id"])

    op.create_table(
        "match_screening_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("screening_order", sa.Integer(), nullable=False),
        sa.Column("locked_creator_brief", postgresql.JSONB()),
        sa.Column("selected", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("screening_reason", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "screening_order >= 0",
            name="ck_match_screening_records_order_nonnegative",
        ),
        sa.CheckConstraint(
            "expires_at >= created_at", name="ck_match_screening_records_expiry"
        ),
        sa.ForeignKeyConstraint(
            ["match_task_id"],
            ["match_tasks.id"],
            name="fk_match_screening_records_task",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creator_profiles.id"],
            name="fk_match_screening_records_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_task_id",
            "creator_id",
            name="uq_match_screening_records_task_creator",
        ),
        sa.UniqueConstraint(
            "match_task_id",
            "screening_order",
            name="uq_match_screening_records_task_order",
        ),
    )
    op.create_index(
        "ix_match_screening_records_creator_id",
        "match_screening_records",
        ["creator_id"],
    )

    op.create_table(
        "match_candidate_inputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("locked_creator_profile", postgresql.JSONB()),
        sa.Column("input_model_metadata", postgresql.JSONB()),
        sa.Column("input_prompt_metadata", postgresql.JSONB()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "expires_at >= created_at", name="ck_match_candidate_inputs_expiry"
        ),
        sa.ForeignKeyConstraint(
            ["match_task_id"],
            ["match_tasks.id"],
            name="fk_match_candidate_inputs_task",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creator_profiles.id"],
            name="fk_match_candidate_inputs_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["match_task_id", "creator_id"],
            [
                "match_screening_records.match_task_id",
                "match_screening_records.creator_id",
            ],
            name="fk_match_candidate_inputs_screening_pair",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_task_id",
            "creator_id",
            name="uq_match_candidate_inputs_task_creator",
        ),
    )
    op.create_index(
        "ix_match_candidate_inputs_creator_id",
        "match_candidate_inputs",
        ["creator_id"],
    )

    op.create_table(
        "match_pairwise_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "state", pairwise_state_enum, server_default="queued", nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("match_brief", postgresql.JSONB()),
        sa.Column("error_code", sa.String(length=128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_match_pairwise_records_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_match_pairwise_records_attempt_count"
        ),
        sa.CheckConstraint(
            "((error_code IS NULL AND error_message IS NULL) OR "
            "(error_code IS NOT NULL AND error_message IS NOT NULL)) "
            "AND (state = 'failed' OR (error_code IS NULL AND NOT retryable))",
            name="ck_match_pairwise_records_error_shape",
        ),
        sa.CheckConstraint(
            "(state = 'queued' AND attempt_count = 0 AND match_brief IS NULL "
            "AND started_at IS NULL AND completed_at IS NULL) "
            "OR (state = 'running' AND attempt_count > 0 AND match_brief IS NULL "
            "AND started_at IS NOT NULL AND completed_at IS NULL) "
            "OR (state = 'succeeded' AND attempt_count > 0 "
            "AND match_brief IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL) "
            "OR (state = 'failed' AND attempt_count > 0 AND match_brief IS NULL "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_match_pairwise_records_state_shape",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at "
            "AND (started_at IS NULL OR started_at >= created_at) "
            "AND (completed_at IS NULL OR completed_at >= COALESCE(started_at, created_at))",
            name="ck_match_pairwise_records_timestamp_shape",
        ),
        sa.ForeignKeyConstraint(
            ["match_task_id"],
            ["match_tasks.id"],
            name="fk_match_pairwise_records_task",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creator_profiles.id"],
            name="fk_match_pairwise_records_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["match_task_id", "creator_id"],
            [
                "match_candidate_inputs.match_task_id",
                "match_candidate_inputs.creator_id",
            ],
            name="fk_match_pairwise_records_candidate_pair",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_task_id",
            "creator_id",
            name="uq_match_pairwise_records_task_creator",
        ),
    )
    op.create_index(
        "ix_match_pairwise_records_creator_id",
        "match_pairwise_records",
        ["creator_id"],
    )
    op.create_index(
        "ix_match_pairwise_records_state", "match_pairwise_records", ["state"]
    )

    op.create_table(
        "match_result_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("backend_order", sa.Integer(), nullable=False),
        sa.Column("match_brief", postgresql.JSONB(), nullable=False),
        sa.Column("total_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("dimension_scores", postgresql.JSONB(), nullable=False),
        sa.Column("dimension_outcomes", postgresql.JSONB(), nullable=False),
        sa.Column("match_reasons", postgresql.JSONB(), nullable=False),
        sa.Column("result_group", result_group_enum, nullable=False),
        sa.Column("qualitative_label", qualitative_label_enum, nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "backend_order >= 0", name="ck_match_result_items_backend_order"
        ),
        sa.CheckConstraint(
            "total_score BETWEEN 0 AND 1",
            name="ck_match_result_items_total_score",
        ),
        sa.CheckConstraint(
            "result_group IN ('recommended', 'other')",
            name="ck_match_result_items_group",
        ),
        sa.CheckConstraint(
            "qualitative_label IN ('Strong Match', 'Good Match', 'Limited Match')",
            name="ck_match_result_items_label",
        ),
        sa.ForeignKeyConstraint(
            ["match_task_id"],
            ["match_tasks.id"],
            name="fk_match_result_items_task",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creator_profiles.id"],
            name="fk_match_result_items_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["match_task_id", "creator_id"],
            [
                "match_pairwise_records.match_task_id",
                "match_pairwise_records.creator_id",
            ],
            name="fk_match_result_items_pairwise_pair",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_task_id",
            "creator_id",
            name="uq_match_result_items_task_creator",
        ),
        sa.UniqueConstraint(
            "match_task_id",
            "backend_order",
            name="uq_match_result_items_task_backend_order",
        ),
    )
    op.create_index(
        "ix_match_result_items_creator_id", "match_result_items", ["creator_id"]
    )

    op.create_table(
        "outreach_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["match_task_id"],
            ["match_tasks.id"],
            name="fk_outreach_campaigns_match_task",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_task_id", name="uq_outreach_campaigns_match_task"),
    )

    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("accepted_label", sa.String(length=255), nullable=False),
        sa.Column("declined_label", sa.String(length=255), nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        *timestamps(),
        sa.CheckConstraint("version > 0", name="ck_templates_version"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_templates_name_version"),
    )
    op.create_index(
        "uq_templates_default",
        "templates",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "send_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True)),
        sa.Column("requested_creator_ids", postgresql.JSONB(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "state", send_batch_state_enum, server_default="queued", nullable=False
        ),
        *timestamps(),
        sa.CheckConstraint(
            "state IN ('queued', 'sending', 'sent', 'partially_failed', 'failed')",
            name="ck_send_batches_state",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(requested_creator_ids) = 'array'",
            name="ck_send_batches_requested_creator_ids_array",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["outreach_campaigns.id"],
            name="fk_send_batches_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            name="fk_send_batches_template",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "campaign_id", name="uq_send_batches_id_campaign"),
    )
    op.create_index("ix_send_batches_campaign_id", "send_batches", ["campaign_id"])
    op.create_index("ix_send_batches_template_id", "send_batches", ["template_id"])

    op.create_table(
        "deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("send_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resends_delivery_id", postgresql.UUID(as_uuid=True)),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("rendered_subject", sa.Text(), nullable=False),
        sa.Column("rendered_markdown", sa.Text(), nullable=False),
        sa.Column("rendered_html", sa.Text(), nullable=False),
        sa.Column("template_name", sa.String(length=255), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("accepted_label", sa.String(length=255), nullable=False),
        sa.Column("declined_label", sa.String(length=255), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=False),
        sa.Column("sender_address", sa.String(length=320), nullable=False),
        sa.Column("reply_to", sa.String(length=320), nullable=False),
        sa.Column(
            "send_state",
            delivery_send_state_enum,
            server_default="queued",
            nullable=False,
        ),
        sa.Column(
            "response_state",
            delivery_response_state_enum,
            server_default="no_response",
            nullable=False,
        ),
        sa.Column("smtp_error_code", sa.String(length=128)),
        sa.Column("smtp_error_message", sa.Text()),
        sa.Column(
            "smtp_retryable", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("response_token_digest", sa.String(length=64), nullable=False),
        sa.Column("sending_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint(
            "template_version > 0", name="ck_deliveries_template_version"
        ),
        sa.CheckConstraint(
            "send_state IN ('queued', 'sending', 'sent', 'failed')",
            name="ck_deliveries_send_state",
        ),
        sa.CheckConstraint(
            "response_state IN ('no_response', 'accepted', 'declined')",
            name="ck_deliveries_response_state",
        ),
        sa.CheckConstraint(
            "response_token_digest ~ '^[0-9a-f]{64}$'",
            name="ck_deliveries_response_token_digest",
        ),
        sa.CheckConstraint(
            "((smtp_error_code IS NULL AND smtp_error_message IS NULL) OR "
            "(smtp_error_code IS NOT NULL AND smtp_error_message IS NOT NULL)) "
            "AND (send_state = 'failed' OR "
            "(smtp_error_code IS NULL AND NOT smtp_retryable))",
            name="ck_deliveries_smtp_error_shape",
        ),
        sa.CheckConstraint(
            "(send_state = 'queued' AND sending_at IS NULL "
            "AND sent_at IS NULL AND failed_at IS NULL) "
            "OR (send_state = 'sending' AND sending_at IS NOT NULL "
            "AND sent_at IS NULL AND failed_at IS NULL) "
            "OR (send_state = 'sent' AND sending_at IS NOT NULL "
            "AND sent_at IS NOT NULL AND failed_at IS NULL) "
            "OR (send_state = 'failed' AND sending_at IS NOT NULL "
            "AND sent_at IS NULL AND failed_at IS NOT NULL)",
            name="ck_deliveries_send_state_shape",
        ),
        sa.CheckConstraint(
            "(response_state = 'no_response' AND responded_at IS NULL) "
            "OR (response_state IN ('accepted', 'declined') "
            "AND responded_at IS NOT NULL)",
            name="ck_deliveries_response_state_shape",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at "
            "AND (sending_at IS NULL OR sending_at >= created_at) "
            "AND (sent_at IS NULL OR sent_at >= sending_at) "
            "AND (failed_at IS NULL OR failed_at >= sending_at) "
            "AND (responded_at IS NULL OR responded_at >= created_at) "
            "AND (superseded_at IS NULL OR "
            "(superseded_at >= created_at AND response_state = 'no_response'))",
            name="ck_deliveries_timestamp_shape",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["outreach_campaigns.id"],
            name="fk_deliveries_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["send_batch_id", "campaign_id"],
            ["send_batches.id", "send_batches.campaign_id"],
            name="fk_deliveries_batch_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creator_profiles.id"],
            name="fk_deliveries_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resends_delivery_id"],
            ["deliveries.id"],
            name="fk_deliveries_resends_delivery",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "campaign_id",
            "creator_id",
            name="uq_deliveries_id_campaign_creator",
        ),
        sa.UniqueConstraint(
            "send_batch_id",
            "creator_id",
            name="uq_deliveries_batch_creator",
        ),
        sa.UniqueConstraint(
            "response_token_digest",
            name="uq_deliveries_response_token_digest",
        ),
    )
    op.create_index("ix_deliveries_campaign_id", "deliveries", ["campaign_id"])
    op.create_index("ix_deliveries_creator_id", "deliveries", ["creator_id"])
    op.create_index(
        "ix_deliveries_resends_delivery_id", "deliveries", ["resends_delivery_id"]
    )
    op.create_index(
        "uq_deliveries_current_campaign_creator",
        "deliveries",
        ["campaign_id", "creator_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "campaign_creator_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "state",
            campaign_response_state_enum,
            server_default="no_response",
            nullable=False,
        ),
        sa.Column("final_delivery_id", postgresql.UUID(as_uuid=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint(
            "state IN ('no_response', 'accepted', 'declined')",
            name="ck_campaign_creator_responses_state",
        ),
        sa.CheckConstraint(
            "(state = 'no_response' AND final_delivery_id IS NULL "
            "AND responded_at IS NULL) "
            "OR (state IN ('accepted', 'declined') "
            "AND final_delivery_id IS NOT NULL AND responded_at IS NOT NULL)",
            name="ck_campaign_creator_responses_state_shape",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["outreach_campaigns.id"],
            name="fk_campaign_creator_responses_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creator_profiles.id"],
            name="fk_campaign_creator_responses_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["final_delivery_id", "campaign_id", "creator_id"],
            ["deliveries.id", "deliveries.campaign_id", "deliveries.creator_id"],
            name="fk_campaign_creator_responses_final_delivery",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "creator_id",
            name="uq_campaign_creator_responses_campaign_creator",
        ),
    )
    op.create_index(
        "ix_campaign_creator_responses_creator_id",
        "campaign_creator_responses",
        ["creator_id"],
    )
    op.create_index(
        "ix_campaign_creator_responses_final_delivery_id",
        "campaign_creator_responses",
        ["final_delivery_id"],
    )


def downgrade() -> None:
    op.drop_table("campaign_creator_responses")
    op.drop_table("deliveries")
    op.drop_table("send_batches")
    op.drop_table("templates")
    op.drop_table("outreach_campaigns")
    op.drop_table("match_result_items")
    op.drop_table("match_pairwise_records")
    op.drop_table("match_candidate_inputs")
    op.drop_table("match_screening_records")
    op.drop_table("match_tasks")
    op.drop_constraint(
        "ck_shared_settings_smtp_rate_per_minute",
        "shared_settings",
        type_="check",
    )
    op.drop_constraint(
        "ck_shared_settings_recommended_match_threshold",
        "shared_settings",
        type_="check",
    )
