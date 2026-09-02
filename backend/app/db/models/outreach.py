from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    func,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.jobs import string_enum


class SendBatchState(StrEnum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class DeliverySendState(StrEnum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class ResponseState(StrEnum):
    NO_RESPONSE = "no_response"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class OutreachCampaign(TimestampMixin, Base):
    __tablename__ = "outreach_campaigns"
    __table_args__ = (
        UniqueConstraint("match_task_id", name="uq_outreach_campaigns_match_task"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    match_task_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "match_tasks.id",
            ondelete="CASCADE",
            name="fk_outreach_campaigns_match_task",
        ),
        nullable=False,
    )


class Template(TimestampMixin, Base):
    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_templates_name_version"),
        CheckConstraint("version > 0", name="ck_templates_version"),
        Index(
            "uq_templates_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_label: Mapped[str] = mapped_column(String(255), nullable=False)
    declined_label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SendBatch(TimestampMixin, Base):
    __tablename__ = "send_batches"
    __table_args__ = (
        UniqueConstraint("id", "campaign_id", name="uq_send_batches_id_campaign"),
        CheckConstraint(
            "state IN ('queued', 'sending', 'sent', 'partially_failed', 'failed')",
            name="ck_send_batches_state",
        ),
        CheckConstraint(
            "jsonb_typeof(requested_creator_ids) = 'array'",
            name="ck_send_batches_requested_creator_ids_array",
        ),
        Index("ix_send_batches_campaign_id", "campaign_id"),
        Index("ix_send_batches_template_id", "template_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "outreach_campaigns.id",
            ondelete="CASCADE",
            name="fk_send_batches_campaign",
        ),
        nullable=False,
    )
    template_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL", name="fk_send_batches_template")
    )
    requested_creator_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    state: Mapped[SendBatchState] = mapped_column(
        string_enum(SendBatchState, "send_batch_state", 20),
        nullable=False,
        default=SendBatchState.QUEUED,
    )


class Delivery(TimestampMixin, Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "campaign_id",
            "creator_id",
            name="uq_deliveries_id_campaign_creator",
        ),
        UniqueConstraint(
            "send_batch_id",
            "creator_id",
            name="uq_deliveries_batch_creator",
        ),
        UniqueConstraint(
            "response_token_digest",
            name="uq_deliveries_response_token_digest",
        ),
        ForeignKeyConstraint(
            ["send_batch_id", "campaign_id"],
            ["send_batches.id", "send_batches.campaign_id"],
            name="fk_deliveries_batch_campaign",
            ondelete="CASCADE",
        ),
        CheckConstraint("template_version > 0", name="ck_deliveries_template_version"),
        CheckConstraint(
            "send_state IN ('queued', 'sending', 'sent', 'failed')",
            name="ck_deliveries_send_state",
        ),
        CheckConstraint(
            "response_state IN ('no_response', 'accepted', 'declined')",
            name="ck_deliveries_response_state",
        ),
        CheckConstraint(
            "response_token_digest ~ '^[0-9a-f]{64}$'",
            name="ck_deliveries_response_token_digest",
        ),
        CheckConstraint(
            "((smtp_error_code IS NULL AND smtp_error_message IS NULL) OR "
            "(smtp_error_code IS NOT NULL AND smtp_error_message IS NOT NULL)) "
            "AND (send_state = 'failed' OR "
            "(smtp_error_code IS NULL AND NOT smtp_retryable))",
            name="ck_deliveries_smtp_error_shape",
        ),
        CheckConstraint(
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
        CheckConstraint(
            "(response_state = 'no_response' AND responded_at IS NULL) "
            "OR (response_state IN ('accepted', 'declined') "
            "AND responded_at IS NOT NULL)",
            name="ck_deliveries_response_state_shape",
        ),
        CheckConstraint(
            "updated_at >= created_at "
            "AND (sending_at IS NULL OR sending_at >= created_at) "
            "AND (sent_at IS NULL OR sent_at >= sending_at) "
            "AND (failed_at IS NULL OR failed_at >= sending_at) "
            "AND (responded_at IS NULL OR responded_at >= created_at) "
            "AND (superseded_at IS NULL OR "
            "(superseded_at >= created_at AND response_state = 'no_response'))",
            name="ck_deliveries_timestamp_shape",
        ),
        Index("ix_deliveries_campaign_id", "campaign_id"),
        Index("ix_deliveries_creator_id", "creator_id"),
        Index("ix_deliveries_resends_delivery_id", "resends_delivery_id"),
        Index(
            "uq_deliveries_current_campaign_creator",
            "campaign_id",
            "creator_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "outreach_campaigns.id",
            ondelete="CASCADE",
            name="fk_deliveries_campaign",
        ),
        nullable=False,
    )
    send_batch_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "creator_profiles.id",
            ondelete="RESTRICT",
            name="fk_deliveries_creator",
        ),
        nullable=False,
    )
    resends_delivery_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "deliveries.id",
            ondelete="RESTRICT",
            name="fk_deliveries_resends_delivery",
        )
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    rendered_subject: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_html: Mapped[str] = mapped_column(Text, nullable=False)
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_label: Mapped[str] = mapped_column(String(255), nullable=False)
    declined_label: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_address: Mapped[str] = mapped_column(String(320), nullable=False)
    reply_to: Mapped[str] = mapped_column(String(320), nullable=False)
    send_state: Mapped[DeliverySendState] = mapped_column(
        string_enum(DeliverySendState, "delivery_send_state", 16),
        nullable=False,
        default=DeliverySendState.QUEUED,
    )
    response_state: Mapped[ResponseState] = mapped_column(
        string_enum(ResponseState, "delivery_response_state", 16),
        nullable=False,
        default=ResponseState.NO_RESPONSE,
    )
    smtp_error_code: Mapped[str | None] = mapped_column(String(128))
    smtp_error_message: Mapped[str | None] = mapped_column(Text)
    smtp_retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    sending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignCreatorResponse(TimestampMixin, Base):
    __tablename__ = "campaign_creator_responses"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "creator_id",
            name="uq_campaign_creator_responses_campaign_creator",
        ),
        ForeignKeyConstraint(
            ["final_delivery_id", "campaign_id", "creator_id"],
            ["deliveries.id", "deliveries.campaign_id", "deliveries.creator_id"],
            name="fk_campaign_creator_responses_final_delivery",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('no_response', 'accepted', 'declined')",
            name="ck_campaign_creator_responses_state",
        ),
        CheckConstraint(
            "(state = 'no_response' AND final_delivery_id IS NULL "
            "AND responded_at IS NULL) "
            "OR (state IN ('accepted', 'declined') "
            "AND final_delivery_id IS NOT NULL AND responded_at IS NOT NULL)",
            name="ck_campaign_creator_responses_state_shape",
        ),
        Index("ix_campaign_creator_responses_creator_id", "creator_id"),
        Index("ix_campaign_creator_responses_final_delivery_id", "final_delivery_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "outreach_campaigns.id",
            ondelete="CASCADE",
            name="fk_campaign_creator_responses_campaign",
        ),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "creator_profiles.id",
            ondelete="RESTRICT",
            name="fk_campaign_creator_responses_creator",
        ),
        nullable=False,
    )
    state: Mapped[ResponseState] = mapped_column(
        string_enum(ResponseState, "campaign_response_state", 16),
        nullable=False,
        default=ResponseState.NO_RESPONSE,
    )
    final_delivery_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
