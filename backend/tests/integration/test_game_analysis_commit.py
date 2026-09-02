from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta, tzinfo
from threading import Barrier, Event, Lock, Thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.game_pipeline import GameAnalysisPipeline
from app.analysis.service import GameAnalysisPublication, GameAnalysisService
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import GameProfile
from app.db.models.settings import SharedSettings
from app.integrations.errors import (
    InvalidModelOutput,
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.schemas.ai_game import GameExtraction, GameSynthesis

from tests.unit.analysis.test_ai_schemas import (
    game_extraction_payload,
    game_synthesis_payload,
)
from tests.unit.analysis.test_prompts import sample_game_source


NOW = datetime(2026, 9, 4, 8, 30, tzinfo=UTC)


@pytest.fixture
def committed_factory(
    migrated_database: None, database_engine: Engine
) -> Iterator[sessionmaker[Session]]:
    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(delete(AnalysisJob))
        session.execute(delete(GameProfile))
        settings = session.scalar(select(SharedSettings).with_for_update())
        assert settings is not None
        settings.game_interval_days = 30
    yield factory
    with factory.begin() as session:
        session.execute(delete(AnalysisJob))
        session.execute(delete(GameProfile))
        settings = session.scalar(select(SharedSettings).with_for_update())
        assert settings is not None
        settings.game_interval_days = 30


def _job(
    factory: sessionmaker[Session],
    *,
    target_type: TargetType = TargetType.GAME,
    status: JobStatus = JobStatus.QUEUED,
    app_id: str = "1245620",
    profile_id: UUID | None = None,
) -> UUID:
    job_id = uuid4()
    effective_profile_id = (
        profile_id or uuid4() if status is JobStatus.SUCCEEDED else None
    )
    with factory.begin() as session:
        session.add(
            AnalysisJob(
                id=job_id,
                target_type=target_type,
                canonical_target_id=app_id,
                canonical_url=f"https://store.steampowered.com/app/{app_id}",
                mode=JobMode.CREATE,
                status=status,
                stage=(
                    AnalysisStage.FINALIZING
                    if status is JobStatus.SUCCEEDED
                    else (
                        AnalysisStage.FETCHING_DATA
                        if status is JobStatus.RUNNING
                        else None
                    )
                ),
                completed_units=5 if status is JobStatus.SUCCEEDED else 0,
                total_units=(
                    5 if status in (JobStatus.RUNNING, JobStatus.SUCCEEDED) else 0
                ),
                error_code=(
                    "analysis_internal_error" if status is JobStatus.FAILED else None
                ),
                error_message=(
                    "Analysis failed unexpectedly. Please retry."
                    if status is JobStatus.FAILED
                    else None
                ),
                retryable=status is JobStatus.FAILED,
                profile_id=effective_profile_id,
                result_payload=(
                    {"profile_id": str(effective_profile_id)}
                    if effective_profile_id is not None
                    else None
                ),
                started_at=(
                    NOW if status in (JobStatus.RUNNING, JobStatus.SUCCEEDED) else None
                ),
                completed_at=(
                    NOW if status in (JobStatus.FAILED, JobStatus.SUCCEEDED) else None
                ),
            )
        )
    return job_id


def _profile(factory: sessionmaker[Session], *, favorite: bool = True) -> UUID:
    profile_id = uuid4()
    with factory.begin() as session:
        session.add(
            GameProfile(
                id=profile_id,
                steam_app_id="1245620",
                canonical_url="https://store.steampowered.com/app/1245620",
                sort_name="Old Name",
                current_facts={"name": "Old Name", "marker": "keep"},
                analysis={"old": "analysis"},
                brief={"old": "brief"},
                source_status={"steam": "available", "old": True},
                model_metadata={"old": "model"},
                prompt_metadata={"old": "prompt"},
                favorite=favorite,
                last_analyzed_at=NOW - timedelta(days=60),
                next_analysis_at=NOW - timedelta(days=30),
            )
        )
    return profile_id


class Steam:
    def __init__(self, *, failure: Exception | None = None, source=None) -> None:
        self.failure = failure
        self.source = source or sample_game_source()

    def fetch_game(self, app_id: str):
        if self.failure:
            raise self.failure
        return self.source


class Artifacts:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.keys: list[str] = []

    def put_json(self, job_id: UUID, name: str, payload: object) -> str:
        if self.failure:
            raise self.failure
        key = f"acquisition/{job_id}/{name}"
        self.keys.append(key)
        return key


class AI:
    def __init__(
        self,
        *,
        structured: list[object] | None = None,
        extraction_failure: Exception | None = None,
        synthesis_failure: Exception | None = None,
    ) -> None:
        self.structured = list(structured or [])
        self.extraction_failure = extraction_failure
        self.synthesis_failure = synthesis_failure

    def complete_structured(self, model: str, messages: list, schema: type):
        if schema is GameExtraction and self.extraction_failure:
            raise self.extraction_failure
        if schema is GameSynthesis and self.synthesis_failure:
            raise self.synthesis_failure
        if self.structured:
            return self.structured.pop(0)
        if schema is GameExtraction:
            return GameExtraction.model_validate(game_extraction_payload())
        return GameSynthesis.model_validate(game_synthesis_payload())

    def complete_vision(self, model: str, prompt: str, image_urls: list, schema: type):
        raise PermanentIntegrationError("vision_optional_failure")


def _pipeline(
    factory: sessionmaker[Session],
    *,
    steam: Steam | None = None,
    artifacts: Artifacts | None = None,
    ai: AI | None = None,
) -> GameAnalysisPipeline:
    return GameAnalysisPipeline(
        service=GameAnalysisService(session_factory=factory, clock=lambda: NOW),
        steam=steam or Steam(),
        artifacts=artifacts or Artifacts(),
        deepseek=ai or AI(),
    )


def _snapshot(factory: sessionmaker[Session], profile_id: UUID) -> dict[str, object]:
    with factory() as session:
        profile = session.get(GameProfile, profile_id)
        assert profile is not None
        return {
            "current_facts": deepcopy(profile.current_facts),
            "analysis": deepcopy(profile.analysis),
            "brief": deepcopy(profile.brief),
            "source_status": deepcopy(profile.source_status),
            "model_metadata": deepcopy(profile.model_metadata),
            "prompt_metadata": deepcopy(profile.prompt_metadata),
            "favorite": profile.favorite,
            "last_analyzed_at": profile.last_analyzed_at,
            "next_analysis_at": profile.next_analysis_at,
        }


@pytest.mark.parametrize(
    ("target_type", "status", "code"),
    [
        (TargetType.CREATOR, JobStatus.QUEUED, "analysis_job_target_invalid"),
        (TargetType.GAME, JobStatus.FAILED, "analysis_job_state_invalid"),
    ],
)
def test_invalid_job_is_rejected_without_resurrection(
    committed_factory, target_type, status, code
) -> None:
    job_id = _job(committed_factory, target_type=target_type, status=status)

    with pytest.raises(PermanentIntegrationError, match=code):
        _pipeline(committed_factory).run(job_id)

    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is status


def test_missing_job_is_rejected_safely(committed_factory) -> None:
    with pytest.raises(PermanentIntegrationError, match="analysis_job_not_found"):
        _pipeline(committed_factory).run(uuid4())


def test_running_job_preserves_first_started_at_and_monotonic_progress(
    committed_factory,
) -> None:
    first_started = NOW - timedelta(minutes=30)
    job_id = _job(committed_factory, status=JobStatus.RUNNING)
    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.started_at = first_started
        job.stage = AnalysisStage.FINALIZING
        job.completed_units = 6
        job.total_units = 7

    GameAnalysisService(session_factory=committed_factory, clock=lambda: NOW).start(
        job_id
    )

    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.started_at == first_started
        assert job.status is JobStatus.RUNNING
        assert job.stage is AnalysisStage.FINALIZING
        assert job.completed_units == 6
        assert job.total_units == 7


@pytest.mark.parametrize(
    ("stage", "completed_units"),
    [
        (AnalysisStage.ANALYZING, 2),
        (AnalysisStage.FINALIZING, 4),
    ],
)
def test_running_resume_preserves_stage_progress_and_first_started_at(
    committed_factory,
    stage: AnalysisStage,
    completed_units: int,
) -> None:
    first_started = NOW - timedelta(minutes=20)
    job_id = _job(committed_factory, status=JobStatus.RUNNING)
    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.started_at = first_started
        job.stage = stage
        job.completed_units = completed_units
        job.total_units = 5

    GameAnalysisService(session_factory=committed_factory, clock=lambda: NOW).start(
        job_id
    )

    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.RUNNING
        assert job.stage is stage
        assert job.completed_units == completed_units
        assert job.total_units == 5
        assert job.started_at == first_started


def test_advance_never_regresses_finalizing_stage_or_progress(
    committed_factory,
) -> None:
    job_id = _job(committed_factory, status=JobStatus.RUNNING)
    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.stage = AnalysisStage.FINALIZING
        job.completed_units = 4
        job.total_units = 5

    GameAnalysisService(session_factory=committed_factory, clock=lambda: NOW).advance(
        job_id, completed_units=2
    )

    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.RUNNING
        assert job.stage is AnalysisStage.FINALIZING
        assert job.completed_units == 4
        assert job.total_units == 5


def test_advance_keeps_nondefault_running_progress_below_total(
    committed_factory,
) -> None:
    job_id = _job(committed_factory, status=JobStatus.RUNNING)
    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.completed_units = 0
        job.total_units = 1

    GameAnalysisService(session_factory=committed_factory, clock=lambda: NOW).advance(
        job_id, completed_units=2
    )

    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.RUNNING
        assert job.stage is AnalysisStage.ANALYZING
        assert (job.completed_units, job.total_units) == (0, 1)


def test_advance_after_success_converges_without_mutation(committed_factory) -> None:
    profile_id = _profile(committed_factory)
    job_id = _job(
        committed_factory,
        status=JobStatus.SUCCEEDED,
        profile_id=profile_id,
    )
    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.stage = AnalysisStage.FINALIZING
        job.completed_units = 5
        job.total_units = 5
    before = _snapshot(committed_factory, profile_id)

    GameAnalysisService(session_factory=committed_factory, clock=lambda: NOW).advance(
        job_id, completed_units=2
    )

    assert _snapshot(committed_factory, profile_id) == before
    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.SUCCEEDED
        assert job.stage is AnalysisStage.FINALIZING
        assert job.completed_units == job.total_units == 5
        assert job.profile_id == profile_id


def test_clock_must_be_aware_utc_before_work_starts(committed_factory) -> None:
    job_id = _job(committed_factory)
    service = GameAnalysisService(
        session_factory=committed_factory,
        clock=lambda: datetime(2026, 9, 2, 8, 30),
    )

    with pytest.raises(PermanentIntegrationError, match="analysis_clock_invalid"):
        service.start(job_id)

    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.QUEUED
        assert job.started_at is None


def test_clock_rejects_tzinfo_with_indeterminate_utc_offset(
    committed_factory,
) -> None:
    class IndeterminateTimezone(tzinfo):
        def utcoffset(self, value):
            return None

        def dst(self, value):
            return None

    job_id = _job(committed_factory)
    service = GameAnalysisService(
        session_factory=committed_factory,
        clock=lambda: datetime(2026, 9, 2, 8, 30, tzinfo=IndeterminateTimezone()),
    )

    with pytest.raises(PermanentIntegrationError, match="analysis_clock_invalid"):
        service.start(job_id)

    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.QUEUED
        assert job.started_at is None


def test_succeeded_job_requires_matching_profile_and_is_idempotent(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    job_id = _job(committed_factory, status=JobStatus.SUCCEEDED, profile_id=profile_id)
    steam = Steam(failure=AssertionError("external call must not happen"))

    assert _pipeline(committed_factory, steam=steam).run(job_id) == profile_id

    with pytest.raises(IntegrityError):
        with committed_factory.begin() as session:
            job = session.get(AnalysisJob, job_id)
            assert job is not None
            job.canonical_target_id = "999"
    assert _pipeline(committed_factory, steam=steam).run(job_id) == profile_id


def test_create_publishes_profile_and_job_atomically_with_current_interval(
    committed_factory,
) -> None:
    with committed_factory.begin() as session:
        settings = session.scalar(select(SharedSettings).with_for_update())
        assert settings is not None
        settings.game_interval_days = 17
    job_id = _job(committed_factory)
    artifacts = Artifacts()

    profile_id = _pipeline(committed_factory, artifacts=artifacts).run(job_id)

    with committed_factory() as session:
        profile = session.get(GameProfile, profile_id)
        job = session.get(AnalysisJob, job_id)
        assert profile is not None and job is not None
        assert profile.steam_app_id == "1245620"
        assert profile.current_facts["name"] == "ELDEN RING"
        assert "raw" not in profile.current_facts
        assert profile.brief == game_synthesis_payload()["game_brief"]
        assert "game_brief" not in profile.analysis
        assert "english_language_check" not in profile.analysis
        assert profile.last_analyzed_at == NOW
        assert profile.next_analysis_at == NOW + timedelta(days=17)
        assert profile.source_status == {
            "steam": "available",
            "visual_analysis": "unavailable",
        }
        assert profile.model_metadata == {
            "extraction_model": "deepseek-v4-flash",
            "vision_model": "deepseek-v4-flash-vision-exp",
            "synthesis_model": "deepseek-v4-pro",
            "vision_available": False,
        }
        assert job.status is JobStatus.SUCCEEDED
        assert job.stage is AnalysisStage.FINALIZING
        assert job.completed_units == job.total_units == 5
        assert job.profile_id == profile_id
        assert job.result_payload == {"profile_id": str(profile_id)}
        assert job.completed_at == NOW
        assert artifacts.keys == [f"acquisition/{job_id}/steam-source.json"]


def test_external_calls_observe_committed_stages_and_no_open_session(
    committed_factory,
) -> None:
    active_sessions = 0
    observed: list[tuple[str, AnalysisStage]] = []

    @contextmanager
    def tracked_factory():
        nonlocal active_sessions
        with committed_factory() as session:
            active_sessions += 1
            try:
                yield session
            finally:
                active_sessions -= 1

    def observe(label: str) -> None:
        assert active_sessions == 0
        with committed_factory() as session:
            job = session.get(AnalysisJob, job_id)
            assert job is not None and job.stage is not None
            observed.append((label, job.stage))

    class ObservingSteam(Steam):
        def fetch_game(self, app_id: str):
            observe("steam")
            return super().fetch_game(app_id)

    class ObservingArtifacts(Artifacts):
        def put_json(self, job_id: UUID, name: str, payload: object) -> str:
            observe("artifact")
            return super().put_json(job_id, name, payload)

    class ObservingAI(AI):
        def complete_structured(self, model: str, messages: list, schema: type):
            observe(schema.__name__)
            return super().complete_structured(model, messages, schema)

        def complete_vision(
            self, model: str, prompt: str, image_urls: list, schema: type
        ):
            observe("vision")
            return super().complete_vision(model, prompt, image_urls, schema)

    job_id = _job(committed_factory)
    pipeline = GameAnalysisPipeline(
        service=GameAnalysisService(session_factory=tracked_factory, clock=lambda: NOW),
        steam=ObservingSteam(),
        artifacts=ObservingArtifacts(),
        deepseek=ObservingAI(),
    )

    pipeline.run(job_id)

    assert active_sessions == 0
    assert observed == [
        ("steam", AnalysisStage.FETCHING_DATA),
        ("artifact", AnalysisStage.FETCHING_DATA),
        ("GameExtraction", AnalysisStage.ANALYZING),
        ("vision", AnalysisStage.ANALYZING),
        ("vision", AnalysisStage.ANALYZING),
        ("GameSynthesis", AnalysisStage.ANALYZING),
    ]


def test_successful_reanalysis_replaces_every_current_field_but_favorite(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory, favorite=True)
    job_id = _job(committed_factory)

    assert _pipeline(committed_factory).run(job_id) == profile_id

    after = _snapshot(committed_factory, profile_id)
    assert after["favorite"] is True
    assert after["analysis"] != {"old": "analysis"}
    assert after["brief"] != {"old": "brief"}
    assert after["source_status"] != {"steam": "available", "old": True}


def test_sort_name_is_nonblank_bounded_while_full_name_is_retained(
    committed_factory,
) -> None:
    full_name = "名" * 300
    source = sample_game_source().model_copy(update={"name": full_name})
    job_id = _job(committed_factory)

    profile_id = _pipeline(committed_factory, steam=Steam(source=source)).run(job_id)

    with committed_factory() as session:
        profile = session.get(GameProfile, profile_id)
        assert profile is not None
        assert profile.sort_name == full_name[:255]
        assert profile.sort_name.strip()
        assert profile.current_facts["name"] == full_name


@pytest.mark.parametrize(
    "failure_stage", ["steam", "artifact", "extraction", "synthesis"]
)
def test_external_failure_preserves_entire_prior_profile(
    committed_factory, failure_stage
) -> None:
    profile_id = _profile(committed_factory)
    job_id = _job(committed_factory)
    before = _snapshot(committed_factory, profile_id)
    failure = TransientIntegrationError(f"{failure_stage}_safe_failure")
    steam = Steam(failure=failure if failure_stage == "steam" else None)
    artifacts = Artifacts(failure=failure if failure_stage == "artifact" else None)
    ai = AI(
        extraction_failure=failure if failure_stage == "extraction" else None,
        synthesis_failure=failure if failure_stage == "synthesis" else None,
    )

    with pytest.raises(
        TransientIntegrationError, match=f"{failure_stage}_safe_failure"
    ):
        _pipeline(committed_factory, steam=steam, artifacts=artifacts, ai=ai).run(
            job_id
        )

    assert _snapshot(committed_factory, profile_id) == before
    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.RUNNING
        assert job.error_message is None
        assert job.error_code is None


def test_semantic_binder_failure_preserves_prior_profile(committed_factory) -> None:
    profile_id = _profile(committed_factory)
    job_id = _job(committed_factory)
    before = _snapshot(committed_factory, profile_id)
    invalid = game_extraction_payload()
    invalid["short_summary"]["evidence"][0]["reference"] = "steam:unknown"
    bad = GameExtraction.model_validate(invalid)

    with pytest.raises(InvalidModelOutput):
        _pipeline(committed_factory, ai=AI(structured=[bad, bad])).run(job_id)

    assert _snapshot(committed_factory, profile_id) == before


def test_final_transaction_exception_rolls_back_profile_and_job(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    job_id = _job(committed_factory)
    before = _snapshot(committed_factory, profile_id)

    def fail_publication(session: Session, flush_context, instances) -> None:
        if any(
            isinstance(item, GameProfile) and item.analysis != {"old": "analysis"}
            for item in session.dirty
        ):
            raise RuntimeError("rollback-injection-private-detail")

    event.listen(Session, "before_flush", fail_publication)
    try:
        with pytest.raises(RuntimeError, match="rollback-injection-private-detail"):
            _pipeline(committed_factory).run(job_id)
    finally:
        event.remove(Session, "before_flush", fail_publication)

    assert _snapshot(committed_factory, profile_id) == before
    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.RUNNING
        assert job.stage is AnalysisStage.FINALIZING
        assert job.profile_id is None


def test_invalid_current_game_interval_rolls_back_publication(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    job_id = _job(committed_factory)
    before = _snapshot(committed_factory, profile_id)
    # Bypass the database constraint only inside the transaction by corrupting the
    # loaded value after SELECT; the service must independently validate it.
    original = GameAnalysisService._read_game_interval
    GameAnalysisService._read_game_interval = staticmethod(lambda settings: 0)
    try:
        with pytest.raises(PermanentIntegrationError, match="game_interval_invalid"):
            _pipeline(committed_factory).run(job_id)
    finally:
        GameAnalysisService._read_game_interval = staticmethod(original)
    assert _snapshot(committed_factory, profile_id) == before


def test_public_json_columns_do_not_leak_raw_artifact_or_secret_material(
    committed_factory,
) -> None:
    job_id = _job(committed_factory)

    profile_id = _pipeline(committed_factory).run(job_id)

    with committed_factory() as session:
        profile = session.get(GameProfile, profile_id)
        assert profile is not None
        public = {
            "current_facts": profile.current_facts,
            "analysis": profile.analysis,
            "brief": profile.brief,
            "source_status": profile.source_status,
            "model_metadata": profile.model_metadata,
            "prompt_metadata": profile.prompt_metadata,
        }
        rendered = str(public).casefold()
        assert "raw-secret-canary" not in rendered
        assert "never-serialize" not in rendered
        assert "acquisition/" not in rendered
        assert "authorization" not in rendered
        assert "credential" not in rendered


def test_duplicate_and_concurrent_finalization_converges_without_rewrite(
    committed_factory,
) -> None:
    job_id = _job(committed_factory)
    service = GameAnalysisService(session_factory=committed_factory, clock=lambda: NOW)
    lease = service.start(job_id)
    service.advance(job_id, completed_units=2)
    service.advance(job_id, completed_units=4)
    source = sample_game_source().model_copy(
        update={
            "cover_image_url": None,
            "header_image_url": None,
            "screenshots": (),
            "movies": (),
        }
    )
    from app.analysis.game_pipeline import unavailable_visual_analysis

    publication = GameAnalysisPublication(
        source=source,
        synthesis=GameSynthesis.model_validate(game_synthesis_payload()),
        visual=unavailable_visual_analysis(
            "No usable public static game images were supplied."
        ),
    )
    barrier = Barrier(2)
    results: list[UUID] = []
    errors: list[BaseException] = []

    def finish() -> None:
        try:
            barrier.wait()
            results.append(service.finalize(lease, publication))
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    threads = [Thread(target=finish), Thread(target=finish)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(results) == 2 and results[0] == results[1]
    assert service.finalize(lease, publication) == results[0]
    with committed_factory() as session:
        assert session.scalar(select(GameProfile).where(GameProfile.id == results[0]))
        assert session.query(GameProfile).count() == 1


def test_overlapping_full_runs_converge_on_one_profile_publication(
    committed_factory,
) -> None:
    job_id = _job(committed_factory)
    second_fetch_started = Event()
    release_second_fetch = Event()
    publication_lock = Lock()
    publication_flushes = 0
    results: list[UUID] = []
    errors: list[BaseException] = []

    class BlockingSteam(Steam):
        def fetch_game(self, app_id: str):
            second_fetch_started.set()
            if not release_second_fetch.wait(timeout=10):
                raise AssertionError("concurrent test did not release Steam fetch")
            return super().fetch_game(app_id)

    def count_profile_publication(session: Session, flush_context) -> None:
        nonlocal publication_flushes
        if any(isinstance(item, GameProfile) for item in session.new | session.dirty):
            with publication_lock:
                publication_flushes += 1

    second_pipeline = _pipeline(committed_factory, steam=BlockingSteam())

    def run_second() -> None:
        try:
            results.append(second_pipeline.run(job_id))
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    thread = Thread(target=run_second)
    publication_listener_registered = False
    try:
        thread.start()
        assert second_fetch_started.wait(timeout=10)
        event.listen(Session, "after_flush", count_profile_publication)
        publication_listener_registered = True
        first_profile_id = _pipeline(committed_factory).run(job_id)
        release_second_fetch.set()
        thread.join(timeout=10)
    finally:
        release_second_fetch.set()
        thread.join(timeout=10)
        if publication_listener_registered:
            event.remove(Session, "after_flush", count_profile_publication)

    assert not thread.is_alive()
    assert errors == []
    assert results == [first_profile_id]
    assert publication_flushes == 1
    with committed_factory() as session:
        assert session.query(GameProfile).count() == 1
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.SUCCEEDED
        assert job.profile_id == first_profile_id
