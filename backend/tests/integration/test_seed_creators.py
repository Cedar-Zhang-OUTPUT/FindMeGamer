from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Lock, Thread
from uuid import UUID

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.enums import JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorContact, CreatorProfile
from tests.integration.test_creator_analysis_commit import _pipeline


CHANNEL_ID = "UCcreator123"
CHANNEL_URL = f"https://www.youtube.com/channel/{CHANNEL_ID}"


@pytest.fixture
def committed_factory(
    migrated_database: None, database_engine: Engine
) -> Iterator[sessionmaker[Session]]:
    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(delete(AnalysisJob))
        session.execute(delete(CreatorContact))
        session.execute(delete(CreatorProfile))
    yield factory
    with factory.begin() as session:
        session.execute(delete(AnalysisJob))
        session.execute(delete(CreatorContact))
        session.execute(delete(CreatorProfile))


class Resolver:
    def resolve_channel(self, target) -> str:
        return CHANNEL_ID


class Dispatcher:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self.calls: list[UUID] = []
        self.fail_first = False
        self._failed = False

    def dispatch(self, job_id: UUID) -> None:
        with self._factory() as session:
            job = session.get(AnalysisJob, job_id)
            assert job is not None and job.status is JobStatus.QUEUED
            profile = session.scalar(
                select(CreatorProfile).where(
                    CreatorProfile.youtube_channel_id == job.canonical_target_id
                )
            )
            assert profile is not None
            assert profile.manual_notes == "Warm lead"
            assert (
                session.scalar(
                    select(CreatorContact).where(
                        CreatorContact.creator_id == profile.id,
                        CreatorContact.is_manual.is_(True),
                        CreatorContact.is_active.is_(True),
                    )
                )
                is not None
            )
        self.calls.append(job_id)
        if self.fail_first and not self._failed:
            self._failed = True
            raise RuntimeError("broker unavailable")


def write_seed(tmp_path: Path, *, name: str = "creators.csv") -> Path:
    path = tmp_path / name
    path.write_text(
        "youtube_url,contact_email,notes\n"
        f"{CHANNEL_URL},TEAM@EXAMPLE.COM,Warm lead\n",
        encoding="utf-8",
    )
    return path


def build_service(seed_module, factory, dispatcher):
    return seed_module.CreatorSeedService(
        store=seed_module.PostgresCreatorSeedStore(session_factory=factory),
        resolver=Resolver(),
        dispatcher=dispatcher,
    )


def test_seed_commits_manual_data_before_dispatch_and_placeholder_is_empty(
    committed_factory, tmp_path
) -> None:
    from app.cli import seed_creators

    dispatcher = Dispatcher(committed_factory)
    result = build_service(seed_creators, committed_factory, dispatcher).run(
        write_seed(tmp_path), tmp_path / "report.json"
    )

    assert result.counts == {"queued": 1, "duplicate": 0, "failed": 0}
    assert dispatcher.calls == [result.rows[0].job_id]
    with committed_factory() as session:
        profile = session.get(CreatorProfile, result.rows[0].profile_id)
        assert profile is not None
        assert profile.last_analyzed_at is None
        assert profile.next_analysis_at is None
        assert profile.current_facts == {}
        assert profile.analysis == {}
        assert profile.brief == {}
        assert profile.model_metadata == {}
        assert profile.prompt_metadata == {}
        assert profile.source_status == {"seed": "incomplete"}
        assert profile.sort_name == CHANNEL_ID
        assert profile.manual_notes == "Warm lead"
        contact = session.scalar(
            select(CreatorContact).where(CreatorContact.creator_id == profile.id)
        )
        assert contact is not None
        assert contact.email == "TEAM@example.com"
        assert contact.source_type == "manual"
        assert contact.is_manual is True
        assert contact.is_active is True


def test_seeded_placeholder_finalizes_through_normal_creator_pipeline_without_loss(
    committed_factory, tmp_path
) -> None:
    from app.cli import seed_creators

    dispatcher = Dispatcher(committed_factory)
    result = build_service(seed_creators, committed_factory, dispatcher).run(
        write_seed(tmp_path), tmp_path / "report.json"
    )
    row = result.rows[0]

    # Seed jobs use the live database clock, so the worker must not use a
    # historical fixed timestamp that predates the newly created job.
    assert (
        _pipeline(committed_factory, clock=lambda: datetime.now(UTC)).run(row.job_id)
        == row.profile_id
    )

    with committed_factory() as session:
        profile = session.get(CreatorProfile, row.profile_id)
        job = session.get(AnalysisJob, row.job_id)
        assert profile is not None and job is not None
        assert profile.manual_notes == "Warm lead"
        assert profile.current_facts["title"] == "Example Creator"
        assert "seed" not in profile.source_status
        assert profile.last_analyzed_at is not None
        manual = session.scalar(
            select(CreatorContact).where(
                CreatorContact.creator_id == profile.id,
                CreatorContact.is_manual.is_(True),
                CreatorContact.is_active.is_(True),
            )
        )
        assert manual is not None and manual.email == "TEAM@example.com"
        assert job.status is JobStatus.SUCCEEDED
        assert job.mode is JobMode.CREATE


def test_existing_analyzed_profile_and_active_job_are_not_mutated_or_published(
    committed_factory, tmp_path
) -> None:
    from app.cli import seed_creators

    with committed_factory.begin() as session:
        analyzed = CreatorProfile(
            youtube_channel_id=CHANNEL_ID,
            canonical_url=CHANNEL_URL,
            sort_name="Analyzed Creator",
            current_facts={"title": "Keep"},
            analysis={"summary": "Keep"},
            brief={"primary_games": ["Keep"]},
            source_status={"youtube": "available"},
            model_metadata={"model": "keep"},
            prompt_metadata={"prompt": "keep"},
            manual_notes="Existing note",
            last_analyzed_at=func.clock_timestamp(),
        )
        session.add(analyzed)
    dispatcher = Dispatcher(committed_factory)
    result = build_service(seed_creators, committed_factory, dispatcher).run(
        write_seed(tmp_path), tmp_path / "analyzed.json"
    )

    assert result.rows[0].status == "duplicate"
    assert dispatcher.calls == []
    with committed_factory() as session:
        profile = session.scalar(select(CreatorProfile))
        assert profile is not None
        assert profile.manual_notes == "Existing note"
        assert profile.current_facts == {"title": "Keep"}
        assert session.scalar(select(func.count()).select_from(CreatorContact)) == 0

    with committed_factory.begin() as session:
        session.execute(delete(CreatorProfile))
        session.add(
            AnalysisJob(
                target_type=TargetType.CREATOR,
                canonical_target_id=CHANNEL_ID,
                canonical_url=CHANNEL_URL,
                mode=JobMode.CREATE,
                status=JobStatus.QUEUED,
            )
        )
    second = build_service(seed_creators, committed_factory, dispatcher).run(
        write_seed(tmp_path, name="active.csv"), tmp_path / "active.json"
    )
    assert second.rows[0].status == "duplicate"
    assert dispatcher.calls == []
    with committed_factory() as session:
        assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 0


def test_broker_failure_marks_failed_and_resume_reuses_incomplete_profile(
    committed_factory, tmp_path
) -> None:
    from app.cli import seed_creators

    dispatcher = Dispatcher(committed_factory)
    dispatcher.fail_first = True
    csv_path = write_seed(tmp_path)
    report_path = tmp_path / "report.json"
    first = build_service(seed_creators, committed_factory, dispatcher).run(
        csv_path, report_path
    )

    assert first.rows[0].status == "failed"
    failed_job_id = first.rows[0].job_id
    profile_id = first.rows[0].profile_id
    with committed_factory() as session:
        failed_job = session.get(AnalysisJob, failed_job_id)
        profile = session.get(CreatorProfile, profile_id)
        assert failed_job is not None and profile is not None
        assert failed_job.status is JobStatus.FAILED
        assert failed_job.error_code == "analysis_queue_unavailable"
        assert failed_job.retryable is True
        assert profile.manual_notes == "Warm lead"

    resumed = build_service(seed_creators, committed_factory, dispatcher).run(
        csv_path, report_path
    )

    assert resumed.rows[0].status == "queued"
    assert resumed.rows[0].profile_id == profile_id
    assert resumed.rows[0].job_id != failed_job_id
    with committed_factory() as session:
        assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 1
        assert session.scalar(select(func.count()).select_from(CreatorContact)) == 1
        jobs = session.scalars(
            select(AnalysisJob).order_by(AnalysisJob.created_at)
        ).all()
        assert [job.status for job in jobs] == [JobStatus.FAILED, JobStatus.QUEUED]


def test_analysis_completed_between_failed_report_and_resume_becomes_duplicate(
    committed_factory, tmp_path
) -> None:
    from app.cli import seed_creators

    dispatcher = Dispatcher(committed_factory)
    dispatcher.fail_first = True
    csv_path = write_seed(tmp_path)
    report_path = tmp_path / "report.json"
    first = build_service(seed_creators, committed_factory, dispatcher).run(
        csv_path, report_path
    )
    with committed_factory.begin() as session:
        profile = session.get(CreatorProfile, first.rows[0].profile_id)
        assert profile is not None
        profile.last_analyzed_at = func.clock_timestamp()
        profile.current_facts = {"title": "Completed elsewhere"}

    resumed = build_service(seed_creators, committed_factory, dispatcher).run(
        csv_path, report_path
    )

    assert resumed.rows[0].status == "duplicate"
    assert len(dispatcher.calls) == 1
    with committed_factory() as session:
        profile = session.get(CreatorProfile, first.rows[0].profile_id)
        assert profile is not None
        assert profile.current_facts == {"title": "Completed elsewhere"}
        assert profile.manual_notes == "Warm lead"


def test_concurrent_seeders_create_and_publish_at_most_one_job_and_profile(
    committed_factory, tmp_path
) -> None:
    from app.cli import seed_creators

    csv_path = write_seed(tmp_path)
    barrier = Barrier(2)
    calls: list[UUID] = []
    lock = Lock()
    results = []
    errors: list[BaseException] = []

    class ConcurrentDispatcher:
        def dispatch(self, job_id: UUID) -> None:
            with lock:
                calls.append(job_id)

    def run(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            result = build_service(
                seed_creators,
                committed_factory,
                ConcurrentDispatcher(),
            ).run(csv_path, tmp_path / f"report-{index}.json")
            with lock:
                results.append(result.rows[0].status)
        except BaseException as error:
            with lock:
                errors.append(error)

    workers = [Thread(target=run, args=(index,)) for index in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert not any(worker.is_alive() for worker in workers)
    assert errors == []
    assert sorted(results) == ["duplicate", "queued"]
    assert len(calls) == 1
    with committed_factory() as session:
        assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 1
        assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1
        assert session.scalar(select(func.count()).select_from(CreatorContact)) == 1
