from datetime import datetime, UTC
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.db.models.enums import TargetType, JobStatus
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile


def test_0018_upgrade_preserves_creator_data_and_accepts_x_jobs_without_weakening_youtube(
    migrated_database,
    alembic_config,
    database_engine,
):
    x_id, yt_id, job_id = uuid4(), uuid4(), uuid4()
    try:
        command.downgrade(alembic_config, "20260908_0018")
        with Session(database_engine) as session, session.begin():
            session.add(
                CreatorProfile(
                    id=x_id,
                    platform="x",
                    platform_account_id="123456",
                    canonical_url="https://x.com/i/user/123456",
                    sort_name="Manual X",
                    manual_overrides={
                        "name": "Manual X",
                        "internal_notes": "Keep this",
                    },
                )
            )
            session.add(
                CreatorProfile(
                    id=yt_id,
                    youtube_channel_id="UClegacy123",
                    canonical_url="https://www.youtube.com/channel/UClegacy123",
                    sort_name="Legacy YouTube",
                )
            )
        command.upgrade(alembic_config, "head")
        with Session(database_engine) as session, session.begin():
            assert (
                session.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260909_0021"
            )
            profile = session.get(CreatorProfile, x_id)
            assert profile.manual_overrides == {
                "name": "Manual X",
                "internal_notes": "Keep this",
            }
            predicate = text(
                "SELECT analysis_job_succeeded_profile_is_valid('creator', :id, :target, :url)"
            )
            assert session.scalar(
                predicate,
                {
                    "id": x_id,
                    "target": "x:123456",
                    "url": "https://x.com/i/user/123456",
                },
            )
            assert session.scalar(
                predicate,
                {
                    "id": yt_id,
                    "target": "UClegacy123",
                    "url": "https://www.youtube.com/channel/UClegacy123",
                },
            )
            assert not session.scalar(
                predicate,
                {
                    "id": yt_id,
                    "target": "x:123456",
                    "url": "https://x.com/i/user/123456",
                },
            )
            now = datetime.now(UTC)
            session.add(
                AnalysisJob(
                    id=job_id,
                    target_type=TargetType.CREATOR,
                    canonical_target_id="x:123456",
                    canonical_url="https://x.com/i/user/123456",
                    mode="reanalyze",
                    status=JobStatus.FAILED,
                    error_code="x_unavailable",
                    error_message="Analysis is temporarily unavailable. Please retry.",
                    retryable=True,
                    created_at=now,
                    updated_at=now,
                    completed_at=now,
                )
            )
        with pytest.raises(RuntimeError, match="Back up X Analyze jobs"):
            command.downgrade(alembic_config, "20260908_0018")
        with Session(database_engine) as session:
            assert session.get(AnalysisJob, job_id) is not None
    finally:
        with Session(database_engine) as session, session.begin():
            session.execute(delete(AnalysisJob).where(AnalysisJob.id == job_id))
            session.execute(
                delete(CreatorProfile).where(CreatorProfile.id.in_([x_id, yt_id]))
            )
        command.upgrade(alembic_config, "head")
