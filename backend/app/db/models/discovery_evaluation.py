"""Evaluation-specific checkpoints; unrelated to v1 Match or sending selections."""

from datetime import datetime
from uuid import UUID, uuid4

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
from app.db.models.discovery import json_object


class EvaluationRun(TimestampMixin, Base):
    __tablename__ = "discovery_evaluation_runs"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    query_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_queries.id"), nullable=False, index=True
    )
    source_snapshot: Mapped[dict] = json_object()
    conditions: Mapped[dict] = json_object()
    game_brief: Mapped[dict] = json_object()
    game_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    models: Mapped[dict] = json_object()
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default="screening", server_default="screening"
    )


class EvaluationItem(Base):
    __tablename__ = "discovery_evaluation_items"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_id", name="uq_evaluation_candidate"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_evaluation_runs.id"), nullable=False, index=True
    )
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_candidates.id"), nullable=False
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey("creator_profiles.id"), nullable=False
    )
    input_order: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = json_object()
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_changed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    screening_selected: Mapped[bool | None] = mapped_column(Boolean)
    match_brief: Mapped[dict | None] = mapped_column(JSONB)
    score: Mapped[int | None] = mapped_column(Integer)


class EvaluationStep(TimestampMixin, Base):
    __tablename__ = "discovery_evaluation_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_evaluation_step"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_evaluation_runs.id"), nullable=False, index=True
    )
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    item_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    output: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
