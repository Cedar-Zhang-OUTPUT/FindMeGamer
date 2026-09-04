from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.analysis.creator_checkpoints import CreatorAnalysisCheckpointStore
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob, CreatorAnalysisNode
from app.integrations.errors import PermanentIntegrationError


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


class CheckpointPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str


@contextmanager
def _session_factory(session: Session):
    nested = Session(bind=session.get_bind(), join_transaction_mode="create_savepoint")
    try:
        yield nested
    finally:
        nested.close()


def _creator_job(session: Session, *, status: JobStatus = JobStatus.RUNNING):
    channel_id = f"UC{uuid4().hex}"
    job = AnalysisJob(
        target_type=TargetType.CREATOR,
        canonical_target_id=channel_id,
        canonical_url=f"https://www.youtube.com/channel/{channel_id}",
        mode=JobMode.CREATE,
        status=status,
        stage=AnalysisStage.ANALYZING,
        completed_units=2,
        total_units=5,
        retryable=status is JobStatus.FAILED,
        started_at=NOW,
        completed_at=NOW if status is JobStatus.FAILED else None,
        error_code="deepseek_unavailable" if status is JobStatus.FAILED else None,
        error_message=(
            "Analysis is temporarily unavailable. Please retry."
            if status is JobStatus.FAILED
            else None
        ),
        created_at=NOW,
    )
    session.add(job)
    session.flush()
    return job


def test_checkpoint_first_valid_success_wins_without_overwrite(
    session: Session,
) -> None:
    job = _creator_job(session)
    store = CreatorAnalysisCheckpointStore(
        session_factory=lambda: _session_factory(session)
    )

    first = store.save_success(job.id, "batch:v1:00", CheckpointPayload(value="first"))
    second = store.save_success(
        job.id, "batch:v1:00", CheckpointPayload(value="different-late-result")
    )

    assert first == CheckpointPayload(value="first")
    assert second == first
    assert store.load(job.id, "batch:v1:00", CheckpointPayload) == first
    assert (
        session.query(CreatorAnalysisNode)
        .filter(CreatorAnalysisNode.job_id == job.id)
        .count()
        == 1
    )


def test_checkpoint_rejects_invalid_keys_and_wrong_schema(session: Session) -> None:
    job = _creator_job(session)
    store = CreatorAnalysisCheckpointStore(
        session_factory=lambda: _session_factory(session)
    )
    store.save_success(job.id, "source:v1", CheckpointPayload(value="valid"))

    class DifferentPayload(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)

        count: int

    with pytest.raises(PermanentIntegrationError, match="analysis_job_state_invalid"):
        store.load(job.id, "source:v1", DifferentPayload)
    with pytest.raises(ValueError, match="node key"):
        store.load(job.id, "../source", CheckpointPayload)


def test_checkpoint_rejects_late_write_after_parent_failure(session: Session) -> None:
    job = _creator_job(session, status=JobStatus.FAILED)
    store = CreatorAnalysisCheckpointStore(
        session_factory=lambda: _session_factory(session)
    )

    with pytest.raises(PermanentIntegrationError, match="analysis_job_state_invalid"):
        store.save_success(job.id, "source:v1", CheckpointPayload(value="late"))
    assert session.get(CreatorAnalysisNode, (job.id, "source:v1")) is None


def test_checkpoint_rejects_non_creator_parent(session: Session) -> None:
    job = _creator_job(session)
    job.target_type = TargetType.GAME
    session.flush()
    store = CreatorAnalysisCheckpointStore(
        session_factory=lambda: _session_factory(session)
    )

    with pytest.raises(PermanentIntegrationError, match="analysis_job_state_invalid"):
        store.save_success(job.id, "source:v1", CheckpointPayload(value="wrong"))


def test_checkpoint_table_has_expected_database_guards(database_engine) -> None:
    inspector = inspect(database_engine)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("creator_analysis_nodes")
    }
    assert set(columns) == {
        "job_id",
        "node_key",
        "output_payload",
        "created_at",
        "updated_at",
    }
    assert inspector.get_pk_constraint("creator_analysis_nodes")[
        "constrained_columns"
    ] == ["job_id", "node_key"]
    foreign_keys = inspector.get_foreign_keys("creator_analysis_nodes")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["referred_table"] == "analysis_jobs"
    assert foreign_keys[0]["options"] == {"ondelete": "CASCADE"}
    constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("creator_analysis_nodes")
    }
    assert "ck_creator_analysis_nodes_key" in constraints
