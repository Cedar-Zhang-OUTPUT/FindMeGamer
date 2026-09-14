from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DiscoverJob(TimestampMixin, Base):
    __tablename__ = "discover_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','partial','failed')",
            name="ck_discover_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    game_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("game_profiles.id", ondelete="SET NULL")
    )
    game_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="SET NULL")
    )
    steam_url: Mapped[str] = mapped_column(Text)
    game_name: Mapped[str] = mapped_column(String(512), default="Preparing game")
    game_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    conditions: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    stage: Mapped[str | None] = mapped_column(String(32), default="preparing_game")
    completed_platforms: Mapped[list] = mapped_column(JSONB, default=list)
    issues: Mapped[list] = mapped_column(JSONB, default=list)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    game_dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoverCandidate(TimestampMixin, Base):
    __tablename__ = "discover_candidates"
    __table_args__ = (
        UniqueConstraint(
            "discover_id",
            "platform",
            "platform_account_id",
            name="uq_discover_candidate_identity",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    discover_id: Mapped[UUID] = mapped_column(
        ForeignKey("discover_jobs.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(16))
    platform_account_id: Mapped[str] = mapped_column(String(128))
    metadata_snapshot: Mapped[dict] = mapped_column(JSONB)
