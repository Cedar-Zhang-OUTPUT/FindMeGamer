"""Actual Activity provenance and immutable final email snapshots."""

from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin


class ActivitySendBatch(TimestampMixin, Base):
    __tablename__ = "activity_send_batches"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"), index=True)
    composition_id: Mapped[UUID] = mapped_column(ForeignKey("outreach_compositions.id"))
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    qualification_snapshot: Mapped[dict] = mapped_column(JSONB)


class ActivityDelivery(TimestampMixin, Base):
    __tablename__ = "activity_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "send_batch_id", "draft_id", name="uq_activity_delivery_batch_draft"
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    send_batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("activity_send_batches.id"), index=True
    )
    draft_id: Mapped[UUID] = mapped_column(ForeignKey("outreach_drafts.id"))
    recipient_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("activity_recipient_snapshots.id")
    )
    snapshot: Mapped[dict] = mapped_column(JSONB)
    input_order: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued"
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    retryable: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    resolution: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
