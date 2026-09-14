from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DiscoverAnalysisBatch(TimestampMixin, Base):
    __tablename__ = "discover_analysis_batches"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('analyze','analyze_and_match')", name="ck_discover_batch_mode"
        ),
        CheckConstraint(
            "status IN ('queued','running','done','partial','failed','blocked')",
            name="ck_discover_batch_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    discover_id: Mapped[UUID] = mapped_column(
        ForeignKey("discover_jobs.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    match_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("match_tasks.id"), unique=True
    )
    error: Mapped[dict | None] = mapped_column(JSONB)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    match_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class DiscoverAnalysisItem(TimestampMixin, Base):
    __tablename__ = "discover_analysis_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_discover_item_status",
        ),
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("discover_analysis_batches.id", ondelete="CASCADE"), primary_key=True
    )
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("discover_candidates.id", ondelete="CASCADE"), primary_key=True
    )
    profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("creator_profiles.id", ondelete="SET NULL")
    )
    reused: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("analysis_jobs.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[dict | None] = mapped_column(JSONB)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
