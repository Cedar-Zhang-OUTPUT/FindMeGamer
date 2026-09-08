"""Activity/account-scoped manual progress and append-only response provenance."""

from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin
from app.db.models.discovery import counter


class ActivityCollaboration(TimestampMixin, Base):
    __tablename__ = "activity_collaborations"
    selection_id: Mapped[UUID] = mapped_column(
        ForeignKey("activity_selections.id"), primary_key=True
    )
    revision: Mapped[int] = counter()
    follow_up_state: Mapped[str] = mapped_column(
        String(32), default="not_followed_up", server_default="not_followed_up"
    )
    cooperation_state: Mapped[str] = mapped_column(
        String(32), default="not_started", server_default="not_started"
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")


class ActivityResponse(Base):
    __tablename__ = "activity_responses"
    __table_args__ = (
        UniqueConstraint(
            "selection_id", "revision", name="uq_activity_response_revision"
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    selection_id: Mapped[UUID] = mapped_column(
        ForeignKey("activity_collaborations.selection_id"), index=True
    )
    revision: Mapped[int] = counter()
    outcome: Mapped[str] = mapped_column(String(16))
    source_note: Mapped[str] = mapped_column(Text)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
