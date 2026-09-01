from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType


def string_enum(enum_type, name: str, length: int) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=False,
        values_callable=lambda values: [value.value for value in values],
        length=length,
    )


class AnalysisJob(TimestampMixin, Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        CheckConstraint("target_type IN ('game', 'creator')", name="target_type"),
        CheckConstraint("mode IN ('create', 'reanalyze')", name="job_mode"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="job_status",
        ),
        CheckConstraint(
            "stage IS NULL OR stage IN ('fetching_data', 'analyzing', 'finalizing')",
            name="analysis_stage",
        ),
        Index(
            "uq_analysis_jobs_active_target",
            "target_type",
            "canonical_target_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    target_type: Mapped[TargetType] = mapped_column(
        string_enum(TargetType, "target_type", 16), nullable=False
    )
    canonical_target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[JobMode] = mapped_column(
        string_enum(JobMode, "job_mode", 16), nullable=False, default=JobMode.CREATE
    )
    status: Mapped[JobStatus] = mapped_column(
        string_enum(JobStatus, "job_status", 16),
        nullable=False,
        default=JobStatus.QUEUED,
    )
    stage: Mapped[AnalysisStage | None] = mapped_column(
        string_enum(AnalysisStage, "analysis_stage", 32)
    )
    completed_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
