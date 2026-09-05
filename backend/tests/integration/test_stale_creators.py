from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock, Thread
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from app.db.models.enums import JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.repositories.profiles import ProfilesRepository
from app.schemas.settings import ReanalysisSettingsUpdate


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
OLD_UPDATED_AT = datetime(2000, 1, 1, tzinfo=UTC)


@contextmanager
def _session_factory(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


@pytest.fixture
def committed_factory(
    migrated_database: None, database_engine: Engine
) -> Iterator[Callable[[], Iterator[Session]]]:
    def cleanup() -> None:
        with Session(database_engine) as session, session.begin():
            session.execute(delete(AnalysisJob))
            session.execute(delete(CreatorContact))
            session.execute(delete(CreatorProfile))
            session.execute(delete(GameProfile))

    cleanup()
    yield lambda: _session_factory(database_engine)
    cleanup()


def _creator(
    session: Session,
    *,
    index: int,
    last_analyzed_at: datetime | None,
    next_analysis_at: datetime | None,
    source_status: dict[str, object] | None = None,
) -> CreatorProfile:
    channel_id = f"UC{index:032x}"
    profile = CreatorProfile(
        youtube_channel_id=channel_id,
        canonical_url=f"https://www.youtube.com/channel/{channel_id}",
        sort_name=f"Creator {index:03d}",
        current_facts={"subscriber_count": index * 1000},
        analysis={"content_style": "expired analysis"},
        brief={"summary": "expired brief"},
        source_status=source_status
        or {
            "youtube": "available",
            "freshness": "current",
            "visual_analysis": "available",
            "custom_marker": "preserved",
        },
        model_metadata={"model": "creator-model"},
        prompt_metadata={"prompt": "creator-v1"},
        favorite=True,
        manual_notes="Keep this note",
        last_analyzed_at=last_analyzed_at,
        next_analysis_at=next_analysis_at,
    )
    session.add(profile)
    session.flush()
    return profile


def _game(
    session: Session, *, index: int, next_analysis_at: datetime | None
) -> GameProfile:
    app_id = str(2_000_000_000 + index)
    profile = GameProfile(
        steam_app_id=app_id,
        canonical_url=f"https://store.steampowered.com/app/{app_id}",
        sort_name=f"Game {index:03d}",
        current_facts={"name": f"Game {index:03d}"},
        analysis={"fit": "current"},
        brief={"summary": "current game brief"},
        source_status={"steam": "available"},
        model_metadata={"model": "game-model"},
        prompt_metadata={"prompt": "game-v1"},
        last_analyzed_at=NOW - timedelta(days=10),
        next_analysis_at=next_analysis_at,
    )
    session.add(profile)
    session.flush()
    return profile


class ObservingDispatcher:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.calls: list[UUID] = []
        self.fail_for_target: set[str] = set()
        self.committed_observations: list[tuple[str, JobStatus]] = []
        self._lock = Lock()

    def dispatch(self, job_id: UUID) -> None:
        with Session(self._engine) as session:
            job = session.get(AnalysisJob, job_id)
            assert job is not None
            observation = (job.canonical_target_id, job.status)
        with self._lock:
            self.calls.append(job_id)
            self.committed_observations.append(observation)
        if observation[0] in self.fail_for_target:
            raise RuntimeError("redis://secret@broker")


def _service(factory, dispatcher: ObservingDispatcher):
    from app.workers.schedules import ScheduledReanalysisService

    return ScheduledReanalysisService(
        session_factory=factory,
        dispatcher=dispatcher,
        clock=lambda: NOW,
    )


def test_due_scheduler_uses_global_order_staggers_and_skips_active_future_null(
    committed_factory, database_engine: Engine
) -> None:
    due: list[tuple[datetime, str, UUID, str]] = []
    with committed_factory() as session:
        for index in range(12):
            when = NOW - timedelta(hours=4) + timedelta(minutes=index)
            creator = _creator(
                session,
                index=index + 1,
                last_analyzed_at=NOW - timedelta(days=10),
                next_analysis_at=when,
            )
            due.append(
                (when, TargetType.CREATOR.value, creator.id, creator.youtube_channel_id)
            )
        for index in range(11):
            when = NOW - timedelta(hours=4) + timedelta(minutes=index)
            game = _game(session, index=index + 1, next_analysis_at=when)
            due.append((when, TargetType.GAME.value, game.id, game.steam_app_id))
        _creator(
            session,
            index=100,
            last_analyzed_at=NOW - timedelta(days=10),
            next_analysis_at=NOW + timedelta(seconds=1),
        )
        _game(session, index=100, next_analysis_at=None)
        active_target = min(due)[3]
        active_due = next(item for item in due if item[3] == active_target)
        active_job = AnalysisJob(
            target_type=TargetType(active_due[1]),
            canonical_target_id=active_due[3],
            canonical_url=(
                f"https://www.youtube.com/channel/{active_due[3]}"
                if active_due[1] == "creator"
                else f"https://store.steampowered.com/app/{active_due[3]}"
            ),
            mode=JobMode.REANALYZE,
            status=JobStatus.RUNNING,
            stage="fetching_data",
            total_units=5,
            started_at=NOW - timedelta(minutes=1),
            created_at=OLD_UPDATED_AT,
        )
        session.add(active_job)
        session.commit()

    expected = [item[3] for item in sorted(due) if item[3] != active_target][:20]
    dispatcher = ObservingDispatcher(database_engine)
    service = _service(committed_factory, dispatcher)

    assert service.run() == 20

    with committed_factory() as session:
        jobs = session.scalars(
            select(AnalysisJob).where(AnalysisJob.id.in_(dispatcher.calls))
        ).all()
        by_id = {job.id: job for job in jobs}
        actual = [by_id[job_id].canonical_target_id for job_id in dispatcher.calls]
        assert actual == expected
        assert all(job.mode is JobMode.REANALYZE for job in jobs)
        assert all(job.status is JobStatus.QUEUED for job in jobs)
        correlation_ids = [UUID(job.correlation_id) for job in jobs]
        assert all(value.version == 4 for value in correlation_ids)
        assert {str(value) for value in correlation_ids} == {
            job.correlation_id for job in jobs
        }
        assert (
            session.scalar(select(AnalysisJob).where(AnalysisJob.id == active_job.id))
            is not None
        )
    assert dispatcher.committed_observations == [
        (target_id, JobStatus.QUEUED) for target_id in expected
    ]

    assert service.run(batch_size=100) == 2


def test_overlapping_scheduler_calls_create_and_publish_only_one_active_job(
    committed_factory, database_engine: Engine
) -> None:
    with committed_factory() as session:
        creator = _creator(
            session,
            index=300,
            last_analyzed_at=NOW - timedelta(days=10),
            next_analysis_at=NOW - timedelta(minutes=1),
        )
        session.commit()
    dispatcher = ObservingDispatcher(database_engine)
    barrier = Barrier(3)
    results: list[int] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait()
            results.append(_service(committed_factory, dispatcher).run())
        except BaseException as error:
            errors.append(error)

    threads = [Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert sorted(results) == [0, 1]
    assert len(dispatcher.calls) == 1
    with committed_factory() as session:
        assert (
            session.scalar(
                select(AnalysisJob)
                .where(
                    AnalysisJob.target_type == TargetType.CREATOR,
                    AnalysisJob.canonical_target_id == creator.youtube_channel_id,
                    AnalysisJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                )
                .with_only_columns(AnalysisJob.id)
            )
            is not None
        )


def test_publish_failure_converges_safely_continues_and_retries_next_cycle(
    committed_factory, database_engine: Engine
) -> None:
    from app.workers.schedules import ScheduledReanalysisService

    with committed_factory() as session:
        first = _game(session, index=401, next_analysis_at=NOW - timedelta(minutes=2))
        second = _creator(
            session,
            index=402,
            last_analyzed_at=NOW - timedelta(days=10),
            next_analysis_at=NOW - timedelta(minutes=1),
        )
        original_game_facts = dict(first.current_facts)
        original_due = first.next_analysis_at
        session.commit()
    dispatcher = ObservingDispatcher(database_engine)
    dispatcher.fail_for_target.add(first.steam_app_id)
    # The scheduling cutoff precedes job creation. A failed dispatch needs a
    # fresh completion timestamp, as it does with the production clock.
    service = ScheduledReanalysisService(
        session_factory=committed_factory,
        dispatcher=dispatcher,
        clock=lambda: datetime.now(UTC),
    )

    assert service.run(batch_size=2) == 1

    with committed_factory() as session:
        failed = session.scalar(
            select(AnalysisJob).where(
                AnalysisJob.canonical_target_id == first.steam_app_id
            )
        )
        refreshed_first = session.get(GameProfile, first.id)
        assert failed is not None
        assert failed.status is JobStatus.FAILED
        assert failed.error_code == "analysis_queue_unavailable"
        assert failed.retryable is True
        assert failed.completed_at >= failed.created_at
        assert refreshed_first is not None
        assert refreshed_first.current_facts == original_game_facts
        assert refreshed_first.next_analysis_at == original_due
        assert (
            session.scalar(
                select(AnalysisJob).where(
                    AnalysisJob.canonical_target_id == second.youtube_channel_id,
                    AnalysisJob.status == JobStatus.QUEUED,
                )
            )
            is not None
        )

    dispatcher.fail_for_target.clear()
    dispatcher.calls.clear()
    dispatcher.committed_observations.clear()
    assert service.run(batch_size=2) == 1
    with committed_factory() as session:
        retry_jobs = session.scalars(
            select(AnalysisJob)
            .where(AnalysisJob.canonical_target_id == first.steam_app_id)
            .order_by(AnalysisJob.created_at, AnalysisJob.id)
        ).all()
        assert [job.status for job in retry_jobs] == [
            JobStatus.FAILED,
            JobStatus.QUEUED,
        ]
        assert session.get(GameProfile, first.id).next_analysis_at == original_due
    assert len(dispatcher.calls) == 1


def test_mark_stale_creators_uses_strict_boundary_and_is_idempotent(
    session: Session,
) -> None:
    older = _creator(
        session,
        index=501,
        last_analyzed_at=NOW - timedelta(days=30, microseconds=1),
        next_analysis_at=NOW - timedelta(days=1),
    )
    exact = _creator(
        session,
        index=502,
        last_analyzed_at=NOW - timedelta(days=30),
        next_analysis_at=NOW - timedelta(days=1),
    )
    current = _creator(
        session,
        index=503,
        last_analyzed_at=NOW - timedelta(days=29),
        next_analysis_at=NOW + timedelta(days=1),
    )
    never = _creator(
        session,
        index=504,
        last_analyzed_at=None,
        next_analysis_at=None,
    )
    already = _creator(
        session,
        index=505,
        last_analyzed_at=NOW - timedelta(days=40),
        next_analysis_at=NOW - timedelta(days=2),
        source_status={"youtube": "stale", "freshness": "stale", "keep": True},
    )
    session.execute(
        update(CreatorProfile)
        .where(
            CreatorProfile.id.in_(
                [older.id, exact.id, current.id, never.id, already.id]
            )
        )
        .values(updated_at=OLD_UPDATED_AT)
    )
    session.flush()

    repository = ProfilesRepository(session)
    assert repository.mark_stale_creators(NOW) == 1
    session.expire_all()
    saved_older = session.get(CreatorProfile, older.id)
    saved_already = session.get(CreatorProfile, already.id)
    assert saved_older.source_status == {
        "youtube": "stale",
        "freshness": "stale",
        "visual_analysis": "available",
        "custom_marker": "preserved",
    }
    assert saved_older.next_analysis_at == NOW - timedelta(days=1)
    first_updated_at = saved_older.updated_at
    assert session.get(CreatorProfile, exact.id).source_status["freshness"] == "current"
    assert (
        session.get(CreatorProfile, current.id).source_status["freshness"] == "current"
    )
    assert session.get(CreatorProfile, never.id).source_status["freshness"] == "current"
    assert saved_already.updated_at == OLD_UPDATED_AT

    assert repository.mark_stale_creators(NOW) == 0
    session.expire(saved_older)
    assert session.get(CreatorProfile, older.id).updated_at == first_updated_at


def test_public_mark_stale_seam_commits_the_shared_cloud_state(
    committed_factory,
) -> None:
    from app.workers.schedules import mark_stale_creators

    with committed_factory() as session:
        creator = _creator(
            session,
            index=550,
            last_analyzed_at=NOW - timedelta(days=31),
            next_analysis_at=NOW - timedelta(days=17),
        )
        session.commit()

    assert mark_stale_creators(NOW, session_factory=committed_factory) == 1

    with committed_factory() as session:
        saved = session.get(CreatorProfile, creator.id)
        assert saved is not None
        assert saved.source_status["youtube"] == "stale"
        assert saved.source_status["freshness"] == "stale"


def test_stale_creator_card_and_detail_hide_expired_content_and_discovered_contact(
    auth_client: TestClient, session: Session
) -> None:
    creator = _creator(
        session,
        index=601,
        last_analyzed_at=NOW - timedelta(days=31),
        next_analysis_at=NOW - timedelta(days=17),
        source_status={
            "youtube": "stale",
            "freshness": "stale",
            "visual_analysis": "available",
        },
    )
    creator.contacts.extend(
        [
            CreatorContact(
                email="discovered@example.com",
                source_type="linked_public_page",
                source_url="https://creator.example/about",
                is_manual=False,
                validation_state="valid",
                priority=10,
                is_active=True,
            ),
            CreatorContact(
                email="manual@example.com",
                source_type="manual",
                is_manual=True,
                validation_state="unverified",
                priority=0,
                is_active=True,
            ),
        ]
    )
    discovered_only = _creator(
        session,
        index=602,
        last_analyzed_at=NOW - timedelta(days=31),
        next_analysis_at=NOW - timedelta(days=17),
        source_status={"youtube": "stale", "freshness": "stale"},
    )
    discovered_only.contacts.append(
        CreatorContact(
            email="hidden@example.com",
            source_type="channel_description",
            source_url=discovered_only.canonical_url,
            is_manual=False,
            validation_state="valid",
            priority=10,
            is_active=True,
        )
    )
    session.flush()

    listed = auth_client.get("/api/v1/profiles/creators").json()["items"]
    cards = {item["id"]: item for item in listed}
    card = cards[str(creator.id)]
    detail = auth_client.get(f"/api/v1/profiles/creators/{creator.id}").json()
    discovered_detail = auth_client.get(
        f"/api/v1/profiles/creators/{discovered_only.id}"
    ).json()

    assert card["current_facts"] == {}
    assert card["brief"] == {}
    assert card["contact"] == {
        "email": "manual@example.com",
        "purpose": None,
        "source": "manual",
        "source_url": None,
        "validation_state": "unverified",
    }
    assert detail["analysis"] == {}
    assert detail["brief"] == {}
    assert detail["manual_notes"] == "Keep this note"
    assert detail["favorite"] is True
    assert detail["model_metadata"] == {"model": "creator-model"}
    assert detail["prompt_metadata"] == {"prompt": "creator-v1"}
    assert detail["last_analyzed_at"] == "2026-08-04T12:00:00Z"
    assert detail["next_analysis_at"] == "2026-08-18T12:00:00Z"
    assert discovered_detail["contact"] is None


def test_reanalysis_settings_have_no_disable_field_and_keep_required_bounds() -> None:
    assert set(ReanalysisSettingsUpdate.model_fields) == {
        "creator_interval_days",
        "game_interval_days",
    }
    for payload in (
        {"creator_interval_days": 0, "game_interval_days": 30},
        {"creator_interval_days": 31, "game_interval_days": 30},
        {"creator_interval_days": 14, "game_interval_days": 0},
        {"creator_interval_days": 14, "game_interval_days": 91},
        {"creator_interval_days": None, "game_interval_days": 30},
        {"creator_interval_days": 14, "game_interval_days": None},
    ):
        with pytest.raises(ValueError):
            ReanalysisSettingsUpdate.model_validate(payload)
