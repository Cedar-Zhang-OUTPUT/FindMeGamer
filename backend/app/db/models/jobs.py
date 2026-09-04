from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    event,
    func,
    select,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.analysis_job_contract import (
    ANALYSIS_JOB_STATUS_SHAPE_SQL,
    PUBLIC_JOB_ERROR_MAPPING_SQL,
)
from app.db.base import Base, TimestampMixin
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType


JOB_CHANGE_ADVISORY_LOCK_ID = 4_604_199_987_260_753_489
analysis_job_change_watermark = Table(
    "analysis_job_change_watermark",
    Base.metadata,
    Column("singleton", Boolean, primary_key=True),
    Column("last_changed_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("singleton", name="singleton_true"),
)


def _next_job_change_statement(*, include_matches: bool):
    sources = (
        "SELECT updated_at FROM analysis_jobs "
        "UNION ALL SELECT updated_at FROM match_tasks"
        if include_matches
        else "SELECT updated_at FROM analysis_jobs"
    )
    return text(
        f"""
    INSERT INTO analysis_job_change_watermark AS watermark (
        singleton,
        last_changed_at
    )
    VALUES (
        true,
        GREATEST(
            clock_timestamp(),
            COALESCE(
                (
                    SELECT max(updated_at) + INTERVAL '1 microsecond'
                    FROM ({sources}) AS changed_jobs
                ),
                '-infinity'::timestamptz
            ),
            COALESCE(CAST(:floor AS timestamptz), '-infinity'::timestamptz)
        )
    )
    ON CONFLICT (singleton) DO UPDATE
    SET last_changed_at = GREATEST(
        clock_timestamp(),
        watermark.last_changed_at + INTERVAL '1 microsecond',
        COALESCE(
            (
                SELECT max(updated_at) + INTERVAL '1 microsecond'
                FROM ({sources}) AS changed_jobs
            ),
            '-infinity'::timestamptz
        ),
        COALESCE(CAST(:floor AS timestamptz), '-infinity'::timestamptz)
    )
    RETURNING last_changed_at
    """
    )


_NEXT_ANALYSIS_CHANGE_TIMESTAMP = _next_job_change_statement(include_matches=False)
_NEXT_UNIFIED_CHANGE_TIMESTAMP = _next_job_change_statement(include_matches=True)


def next_job_change_timestamp(executor, *, floor: datetime | None = None) -> datetime:
    has_match_table = bool(
        executor.scalar(text("SELECT to_regclass('public.match_tasks') IS NOT NULL"))
    )
    statement = (
        _NEXT_UNIFIED_CHANGE_TIMESTAMP
        if has_match_table
        else _NEXT_ANALYSIS_CHANGE_TIMESTAMP
    )
    changed_at = executor.scalar(statement, {"floor": floor})
    if (
        not isinstance(changed_at, datetime)
        or changed_at.tzinfo is None
        or changed_at.utcoffset() is None
    ):
        raise RuntimeError("database clock is unavailable")
    return changed_at


def acquire_job_change_lock(executor) -> None:
    executor.execute(select(func.pg_advisory_xact_lock(JOB_CHANGE_ADVISORY_LOCK_ID)))


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
        CheckConstraint(
            "completed_units >= 0",
            name="ck_analysis_jobs_completed_units_nonnegative",
        ),
        CheckConstraint(
            "total_units >= 0",
            name="ck_analysis_jobs_total_units_nonnegative",
        ),
        CheckConstraint(
            "completed_units <= total_units",
            name="ck_analysis_jobs_completed_not_above_total",
        ),
        CheckConstraint(
            "status = 'failed' OR NOT retryable",
            name="ck_analysis_jobs_retryable_only_failed",
        ),
        CheckConstraint(
            f"status <> 'failed' OR ({PUBLIC_JOB_ERROR_MAPPING_SQL})",
            name="ck_analysis_jobs_error_mapping",
        ),
        CheckConstraint(
            ANALYSIS_JOB_STATUS_SHAPE_SQL,
            name="ck_analysis_jobs_status_shape",
        ),
        Index(
            "uq_analysis_jobs_active_target",
            "target_type",
            "canonical_target_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_analysis_jobs_updated_at_id", "updated_at", "id"),
        Index(
            "ix_analysis_jobs_succeeded_profile_id",
            "profile_id",
            postgresql_where=text("status = 'succeeded'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
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


class CreatorAnalysisNode(TimestampMixin, Base):
    """A validated successful Creator analysis node checkpoint."""

    __tablename__ = "creator_analysis_nodes"
    __table_args__ = (
        CheckConstraint(
            "node_key ~ '^[a-z][a-z0-9_.:-]{0,63}$'",
            name="ck_creator_analysis_nodes_key",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "analysis_jobs.id",
            ondelete="CASCADE",
            name="fk_creator_analysis_nodes_job",
        ),
        primary_key=True,
    )
    node_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


def _serialize_and_timestamp_job_change(_mapper, connection, target) -> None:
    acquire_job_change_lock(connection)
    values = [
        value
        for value in (
            target.created_at,
            target.updated_at,
            target.started_at,
            target.completed_at,
        )
        if isinstance(value, datetime)
    ]
    target.updated_at = next_job_change_timestamp(
        connection, floor=max(values) if values else None
    )


event.listen(AnalysisJob, "before_insert", _serialize_and_timestamp_job_change)
event.listen(AnalysisJob, "before_update", _serialize_and_timestamp_job_change)
