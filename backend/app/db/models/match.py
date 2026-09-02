from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.jobs import (
    acquire_job_change_lock,
    next_job_change_timestamp,
    string_enum,
)


class MatchStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class MatchStage(StrEnum):
    SCREENING = "screening"
    PAIRWISE = "pairwise"
    RANKING = "ranking"


class PairwiseState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MatchResultGroup(StrEnum):
    RECOMMENDED = "recommended"
    OTHER = "other"


class MatchQualitativeLabel(StrEnum):
    STRONG = "Strong Match"
    GOOD = "Good Match"
    LIMITED = "Limited Match"


class MatchTask(TimestampMixin, Base):
    __tablename__ = "match_tasks"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_match_tasks_supersedes_id"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')",
            name="ck_match_tasks_status",
        ),
        CheckConstraint(
            "stage IN ('screening', 'pairwise', 'ranking')",
            name="ck_match_tasks_stage",
        ),
        CheckConstraint(
            "recommended_match_threshold BETWEEN 0 AND 1",
            name="ck_match_tasks_threshold",
        ),
        CheckConstraint(
            "completed_units >= 0",
            name="ck_match_tasks_completed_units_nonnegative",
        ),
        CheckConstraint(
            "total_units >= 0", name="ck_match_tasks_total_units_nonnegative"
        ),
        CheckConstraint(
            "result_count >= 0", name="ck_match_tasks_result_count_nonnegative"
        ),
        CheckConstraint(
            "completed_units <= total_units",
            name="ck_match_tasks_completed_not_above_total",
        ),
        CheckConstraint(
            "result_count <= total_units",
            name="ck_match_tasks_result_not_above_total",
        ),
        CheckConstraint(
            "((error_code IS NULL AND error_message IS NULL) OR "
            "(error_code IS NOT NULL AND error_message IS NOT NULL)) "
            "AND (status IN ('failed', 'superseded') OR error_code IS NULL) "
            "AND (status = 'failed' OR NOT retryable)",
            name="ck_match_tasks_error_shape",
        ),
        CheckConstraint(
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL) "
            "OR (status = 'running' AND started_at IS NOT NULL "
            "AND completed_at IS NULL) "
            "OR (status = 'succeeded' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL) "
            "OR (status = 'failed' AND completed_at IS NOT NULL) "
            "OR (status = 'superseded' AND completed_at IS NOT NULL)",
            name="ck_match_tasks_status_shape",
        ),
        CheckConstraint(
            "updated_at >= created_at "
            "AND input_expires_at >= created_at "
            "AND (started_at IS NULL OR started_at >= created_at) "
            "AND (completed_at IS NULL OR completed_at >= COALESCE(started_at, created_at)) "
            "AND (ranking_enqueued_at IS NULL "
            "OR ranking_enqueued_at >= COALESCE(started_at, created_at))",
            name="ck_match_tasks_timestamp_shape",
        ),
        Index("ix_match_tasks_game_id", "game_id"),
        Index("ix_match_tasks_status", "status"),
        Index("ix_match_tasks_updated_at_id", "updated_at", "id"),
        Index("ix_match_tasks_supersedes_id", "supersedes_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("game_profiles.id", ondelete="RESTRICT", name="fk_match_tasks_game"),
        nullable=False,
    )
    locked_game_brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    shuffle_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recommended_match_threshold: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False
    )
    status: Mapped[MatchStatus] = mapped_column(
        string_enum(MatchStatus, "match_status", 16),
        nullable=False,
        default=MatchStatus.QUEUED,
    )
    stage: Mapped[MatchStage] = mapped_column(
        string_enum(MatchStage, "match_stage", 16),
        nullable=False,
        default=MatchStage.SCREENING,
    )
    completed_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    input_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ranking_enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "match_tasks.id",
            ondelete="RESTRICT",
            name="fk_match_tasks_supersedes",
        )
    )


def _serialize_and_timestamp_match_change(_mapper, connection, target) -> None:
    acquire_job_change_lock(connection)
    values = [
        value
        for value in (
            target.created_at,
            target.updated_at,
            target.started_at,
            target.completed_at,
            target.ranking_enqueued_at,
        )
        if isinstance(value, datetime)
    ]
    target.updated_at = next_job_change_timestamp(
        connection, floor=max(values) if values else None
    )


event.listen(MatchTask, "before_insert", _serialize_and_timestamp_match_change)
event.listen(MatchTask, "before_update", _serialize_and_timestamp_match_change)


class MatchScreeningRecord(TimestampMixin, Base):
    __tablename__ = "match_screening_records"
    __table_args__ = (
        UniqueConstraint(
            "match_task_id",
            "creator_id",
            name="uq_match_screening_records_task_creator",
        ),
        UniqueConstraint(
            "match_task_id",
            "screening_order",
            name="uq_match_screening_records_task_order",
        ),
        CheckConstraint(
            "screening_order >= 0",
            name="ck_match_screening_records_order_nonnegative",
        ),
        CheckConstraint(
            "expires_at >= created_at", name="ck_match_screening_records_expiry"
        ),
        Index("ix_match_screening_records_creator_id", "creator_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    match_task_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "match_tasks.id",
            ondelete="CASCADE",
            name="fk_match_screening_records_task",
        ),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "creator_profiles.id",
            ondelete="RESTRICT",
            name="fk_match_screening_records_creator",
        ),
        nullable=False,
    )
    screening_order: Mapped[int] = mapped_column(Integer, nullable=False)
    locked_creator_brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    screening_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MatchCandidateInput(TimestampMixin, Base):
    __tablename__ = "match_candidate_inputs"
    __table_args__ = (
        UniqueConstraint(
            "match_task_id",
            "creator_id",
            name="uq_match_candidate_inputs_task_creator",
        ),
        ForeignKeyConstraint(
            ["match_task_id", "creator_id"],
            [
                "match_screening_records.match_task_id",
                "match_screening_records.creator_id",
            ],
            name="fk_match_candidate_inputs_screening_pair",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "expires_at >= created_at", name="ck_match_candidate_inputs_expiry"
        ),
        Index("ix_match_candidate_inputs_creator_id", "creator_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    match_task_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "match_tasks.id",
            ondelete="CASCADE",
            name="fk_match_candidate_inputs_task",
        ),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "creator_profiles.id",
            ondelete="RESTRICT",
            name="fk_match_candidate_inputs_creator",
        ),
        nullable=False,
    )
    locked_creator_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    input_model_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    input_prompt_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MatchPairwiseRecord(TimestampMixin, Base):
    __tablename__ = "match_pairwise_records"
    __table_args__ = (
        UniqueConstraint(
            "match_task_id",
            "creator_id",
            name="uq_match_pairwise_records_task_creator",
        ),
        ForeignKeyConstraint(
            ["match_task_id", "creator_id"],
            [
                "match_candidate_inputs.match_task_id",
                "match_candidate_inputs.creator_id",
            ],
            name="fk_match_pairwise_records_candidate_pair",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_match_pairwise_records_state",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_match_pairwise_records_attempt_count"
        ),
        CheckConstraint(
            "((error_code IS NULL AND error_message IS NULL) OR "
            "(error_code IS NOT NULL AND error_message IS NOT NULL)) "
            "AND (state = 'failed' OR (error_code IS NULL AND NOT retryable))",
            name="ck_match_pairwise_records_error_shape",
        ),
        CheckConstraint(
            "(state = 'queued' AND attempt_count = 0 AND match_brief IS NULL "
            "AND started_at IS NULL AND completed_at IS NULL) "
            "OR (state = 'running' AND attempt_count > 0 AND match_brief IS NULL "
            "AND started_at IS NOT NULL AND completed_at IS NULL) "
            "OR (state = 'succeeded' AND attempt_count > 0 "
            "AND match_brief IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL) "
            "OR (state = 'failed' AND attempt_count > 0 AND match_brief IS NULL "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_match_pairwise_records_state_shape",
        ),
        CheckConstraint(
            "updated_at >= created_at "
            "AND (started_at IS NULL OR started_at >= created_at) "
            "AND (completed_at IS NULL OR completed_at >= COALESCE(started_at, created_at))",
            name="ck_match_pairwise_records_timestamp_shape",
        ),
        Index("ix_match_pairwise_records_creator_id", "creator_id"),
        Index("ix_match_pairwise_records_state", "state"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    match_task_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "match_tasks.id",
            ondelete="CASCADE",
            name="fk_match_pairwise_records_task",
        ),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "creator_profiles.id",
            ondelete="RESTRICT",
            name="fk_match_pairwise_records_creator",
        ),
        nullable=False,
    )
    state: Mapped[PairwiseState] = mapped_column(
        string_enum(PairwiseState, "match_pairwise_state", 16),
        nullable=False,
        default=PairwiseState.QUEUED,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    match_brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MatchResultItem(TimestampMixin, Base):
    __tablename__ = "match_result_items"
    __table_args__ = (
        UniqueConstraint(
            "match_task_id",
            "creator_id",
            name="uq_match_result_items_task_creator",
        ),
        UniqueConstraint(
            "match_task_id",
            "backend_order",
            name="uq_match_result_items_task_backend_order",
        ),
        ForeignKeyConstraint(
            ["match_task_id", "creator_id"],
            [
                "match_pairwise_records.match_task_id",
                "match_pairwise_records.creator_id",
            ],
            name="fk_match_result_items_pairwise_pair",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "backend_order >= 0", name="ck_match_result_items_backend_order"
        ),
        CheckConstraint(
            "total_score BETWEEN 0 AND 1",
            name="ck_match_result_items_total_score",
        ),
        CheckConstraint(
            "result_group IN ('recommended', 'other')",
            name="ck_match_result_items_group",
        ),
        CheckConstraint(
            "qualitative_label IN ('Strong Match', 'Good Match', 'Limited Match')",
            name="ck_match_result_items_label",
        ),
        Index("ix_match_result_items_creator_id", "creator_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    match_task_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "match_tasks.id",
            ondelete="CASCADE",
            name="fk_match_result_items_task",
        ),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "creator_profiles.id",
            ondelete="RESTRICT",
            name="fk_match_result_items_creator",
        ),
        nullable=False,
    )
    backend_order: Mapped[int] = mapped_column(Integer, nullable=False)
    match_brief: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dimension_outcomes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    match_reasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    result_group: Mapped[MatchResultGroup] = mapped_column(
        string_enum(MatchResultGroup, "match_result_group", 16), nullable=False
    )
    qualitative_label: Mapped[MatchQualitativeLabel] = mapped_column(
        string_enum(MatchQualitativeLabel, "match_qualitative_label", 16),
        nullable=False,
    )
