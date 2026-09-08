"""Immutable template versions; new outreach never mutates legacy templates."""

from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin


class OutreachTemplateVersion(TimestampMixin, Base):
    __tablename__ = "outreach_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "game_id", "builtin_key", name="uq_outreach_game_builtin_template"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    game_id: Mapped[UUID] = mapped_column(ForeignKey("game_profiles.id"), index=True)
    builtin_key: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), unique=True)
    request_hash: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(998))
    fixed_fragments: Mapped[list[str]] = mapped_column(JSONB)
    fixed_hash: Mapped[str] = mapped_column(String(64))
    source_metadata: Mapped[dict] = mapped_column(JSONB)


class OutreachComposition(TimestampMixin, Base):
    __tablename__ = "outreach_compositions"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"), index=True)
    recipient_batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("activity_recipient_batches.id")
    )
    template_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("outreach_template_versions.id")
    )
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))


class OutreachDraft(TimestampMixin, Base):
    __tablename__ = "outreach_drafts"
    __table_args__ = (
        UniqueConstraint(
            "composition_id",
            "recipient_snapshot_id",
            name="uq_composition_recipient_draft",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    composition_id: Mapped[UUID] = mapped_column(
        ForeignKey("outreach_compositions.id"), index=True
    )
    recipient_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("activity_recipient_snapshots.id")
    )
    input_order: Mapped[int] = mapped_column(Integer)
    input_data: Mapped[dict] = mapped_column(JSONB)
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(32))
    values: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    sender_facts: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
