"""Human choices and frozen recipient lists, never SMTP deliveries."""

from uuid import UUID, uuid4
from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin
from app.db.models.discovery import counter, json_object


class ActivitySelection(TimestampMixin, Base):
    __tablename__ = "activity_selections"
    __table_args__ = (
        UniqueConstraint(
            "activity_id", "platform", "account_id", name="uq_activity_selected_account"
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"), index=True)
    creator_id: Mapped[UUID] = mapped_column(ForeignKey("creator_profiles.id"))
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("discovery_candidates.id"))
    platform: Mapped[str] = mapped_column(String(32))
    account_id: Mapped[str] = mapped_column(String(128))
    identity_revision: Mapped[int] = counter()
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    revision: Mapped[int] = counter()
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("creator_contacts.id"))
    contact_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    evaluation_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("discovery_evaluation_items.id")
    )
    work_ids: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    name_confirmation: Mapped[dict] = json_object()


class RecipientBatch(TimestampMixin, Base):
    __tablename__ = "activity_recipient_batches"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"), index=True)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    source_snapshot: Mapped[dict] = json_object()


class RecipientSnapshot(Base):
    __tablename__ = "activity_recipient_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "selection_id", name="uq_batch_selected_recipient"
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("activity_recipient_batches.id"), index=True
    )
    selection_id: Mapped[UUID] = mapped_column(ForeignKey("activity_selections.id"))
    snapshot: Mapped[dict] = json_object()
    context_token: Mapped[str] = mapped_column(String(64))
    input_order: Mapped[int] = counter()
