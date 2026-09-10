"""Explicit one-click campaigns; old discovery records are never auto-enrolled."""

from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin


class CreatorSearch(TimestampMixin, Base):
    __tablename__ = "creator_searches"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"), index=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("discovery_plans.id"))
    query_id: Mapped[UUID | None] = mapped_column(ForeignKey("discovery_queries.id"))
    batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("discovery_batches.id"))
    evaluation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("discovery_evaluation_runs.id")
    )
    parent_search_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("creator_searches.id")
    )
    status: Mapped[str] = mapped_column(
        String(32), default="queued", server_default="queued"
    )
    stage: Mapped[str] = mapped_column(
        String(32), default="planning", server_default="planning"
    )
    stop_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    scope_frozen: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    acknowledge_unknown: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    excluded_candidate_ids: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreatorSearchUnit(TimestampMixin, Base):
    __tablename__ = "creator_search_units"
    __table_args__ = (
        UniqueConstraint(
            "search_id", "candidate_id", name="uq_creator_search_candidate"
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    search_id: Mapped[UUID] = mapped_column(
        ForeignKey("creator_searches.id"), index=True
    )
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("discovery_candidates.id"))
    creator_id: Mapped[UUID] = mapped_column(ForeignKey("creator_profiles.id"))
    platform: Mapped[str] = mapped_column(String(32))
    account_id: Mapped[str] = mapped_column(String(128))
    identity_revision: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    profile_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )
    email_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )
    analysis_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("analysis_jobs.id"))
    owns_analysis_job: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    profile_error_code: Mapped[str | None] = mapped_column(String(64))
    email_error_code: Mapped[str | None] = mapped_column(String(64))
