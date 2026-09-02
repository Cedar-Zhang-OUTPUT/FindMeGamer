from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from celery.exceptions import Retry
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile, GameProfile
from app.integrations.errors import (
    InvalidModelOutput,
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.workers.analysis_tasks import (
    ANALYSIS_TASK_NAME,
    AnalysisJobExecutor,
    RetryPolicy,
    TerminalFailure,
    get_retry_policy,
    run_analysis_job,
    write_terminal_failure,
)
from app.workers.celery_app import celery_app


NOW = datetime(2026, 9, 2, 8, 30, tzinfo=UTC)


class FakePipeline:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[UUID] = []

    def run(self, job_id: UUID) -> UUID:
        self.calls.append(job_id)
        if self.error is not None:
            raise self.error
        return uuid4()


class PipelineFactory:
    def __init__(self, pipelines: dict[TargetType, FakePipeline]) -> None:
        self.pipelines = pipelines
        self.opened: list[TargetType] = []
        self.closed: list[TargetType] = []
        self.before_open = lambda: None

    @contextmanager
    def __call__(self, target_type: TargetType):
        self.before_open()
        self.opened.append(target_type)
        try:
            yield self.pipelines[target_type]
        finally:
            self.closed.append(target_type)


def _job(
    session: Session,
    *,
    target_type: TargetType = TargetType.GAME,
    status: JobStatus = JobStatus.QUEUED,
) -> AnalysisJob:
    canonical_id = (
        str(1_000_000 + uuid4().int % 1_000_000)
        if target_type is TargetType.GAME
        else f"UC{uuid4().hex}"
    )
    canonical_url = (
        f"https://store.steampowered.com/app/{canonical_id}"
        if target_type is TargetType.GAME
        else f"https://www.youtube.com/channel/{canonical_id}"
    )
    job = AnalysisJob(
        target_type=target_type,
        canonical_target_id=canonical_id,
        canonical_url=canonical_url,
        mode=JobMode.CREATE,
        status=status,
        correlation_id=f"correlation-{uuid4()}",
    )
    session.add(job)
    session.flush()
    return job


@contextmanager
def _session_factory(session: Session):
    yield session


def _executor(
    session: Session,
    pipeline: FakePipeline,
    *,
    target_type: TargetType = TargetType.GAME,
) -> tuple[AnalysisJobExecutor, PipelineFactory]:
    other_type = (
        TargetType.CREATOR if target_type is TargetType.GAME else TargetType.GAME
    )
    factory = PipelineFactory({target_type: pipeline, other_type: FakePipeline()})
    executor = AnalysisJobExecutor(
        session_factory=lambda: _session_factory(session),
        pipeline_factory=factory,
        clock=lambda: NOW,
    )
    return executor, factory


def test_celery_app_is_broker_only_json_and_registers_stable_task() -> None:
    assert run_analysis_job.name == ANALYSIS_TASK_NAME
    assert celery_app.tasks[ANALYSIS_TASK_NAME].name == ANALYSIS_TASK_NAME
    assert celery_app.backend.__class__.__name__ == "DisabledBackend"
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.task_ignore_result is True
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.broker_connection_retry_on_startup is True
    assert "app.workers.analysis_tasks" in celery_app.conf.include


def test_worker_retry_delay_environment_misconfiguration_fails_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANALYSIS_RETRY_BASE_DELAY_SECONDS", "300")
    monkeypatch.setenv("ANALYSIS_RETRY_MAX_DELAY_SECONDS", "1")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError, match="base delay"):
            get_retry_policy()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "raw_job_id",
    ["", "not-a-uuid", str(UUID(int=0)), str(uuid4()).upper(), f"{{{uuid4()}}}"],
)
def test_invalid_noncanonical_job_id_is_a_noop_before_database_access(
    monkeypatch: pytest.MonkeyPatch, raw_job_id: str
) -> None:
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor",
        lambda: (_ for _ in ()).throw(AssertionError("executor must not be built")),
    )
    assert run_analysis_job.apply(args=[raw_job_id], throw=True).get() is None


@pytest.mark.parametrize("target_type", list(TargetType))
def test_queued_job_is_claimed_once_and_dispatched_by_persisted_target(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    target_type: TargetType,
) -> None:
    job = _job(session, target_type=target_type)
    pipeline = FakePipeline()
    executor, factory = _executor(session, pipeline, target_type=target_type)
    factory.before_open = lambda: (
        None
        if not session.in_transaction()
        else (_ for _ in ()).throw(AssertionError("session spans pipeline work"))
    )
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )

    assert run_analysis_job.apply(args=[str(job.id)], throw=True).get() is None
    session.expire_all()
    saved = session.get(AnalysisJob, job.id)
    assert saved is not None
    assert saved.status is JobStatus.RUNNING
    assert saved.stage is AnalysisStage.FETCHING_DATA
    assert saved.started_at == NOW
    assert saved.completed_units == 0
    assert saved.total_units == 5
    assert saved.correlation_id == job.correlation_id
    assert pipeline.calls == [job.id]
    assert factory.opened == [target_type]
    assert factory.closed == [target_type]


def test_running_redelivery_preserves_progress_and_started_time(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(session, status=JobStatus.RUNNING)
    original_started = datetime(2026, 9, 1, 1, 2, tzinfo=UTC)
    job.started_at = original_started
    job.stage = AnalysisStage.ANALYZING
    job.completed_units = 3
    job.total_units = 5
    session.flush()
    pipeline = FakePipeline()
    executor, _factory = _executor(session, pipeline)
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )

    run_analysis_job.apply(args=[str(job.id)], throw=True).get()
    session.expire_all()
    saved = session.get(AnalysisJob, job.id)
    assert saved is not None
    assert saved.started_at == original_started
    assert saved.stage is AnalysisStage.ANALYZING
    assert (saved.completed_units, saved.total_units) == (3, 5)
    assert pipeline.calls == [job.id]


@pytest.mark.parametrize("status", [JobStatus.FAILED, JobStatus.SUCCEEDED])
def test_terminal_redelivery_is_a_noop(
    session: Session, monkeypatch: pytest.MonkeyPatch, status: JobStatus
) -> None:
    job = _job(session, status=status)
    if status is JobStatus.SUCCEEDED:
        profile = GameProfile(
            steam_app_id=job.canonical_target_id,
            canonical_url=job.canonical_url,
            sort_name="Finished",
        )
        session.add(profile)
        session.flush()
        job.profile_id = profile.id
        job.result_payload = {"profile_id": str(profile.id)}
    session.flush()
    pipeline = FakePipeline()
    executor, factory = _executor(session, pipeline)
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )

    run_analysis_job.apply(args=[str(job.id)], throw=True).get()
    assert pipeline.calls == []
    assert factory.opened == []


def test_missing_job_is_a_safe_noop(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, factory = _executor(session, FakePipeline())
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )
    run_analysis_job.apply(args=[str(uuid4())], throw=True).get()
    assert factory.opened == []


def test_transient_failure_retries_without_marking_final_failure(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(session)
    pipeline = FakePipeline(TransientIntegrationError("steam_unavailable"))
    executor, factory = _executor(session, pipeline)
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_retry_policy",
        lambda: RetryPolicy(max_retries=3, base_delay_seconds=4, max_delay_seconds=30),
    )
    monkeypatch.setattr("app.workers.analysis_tasks.random_jitter", lambda ceiling: 1)

    with pytest.raises(Retry) as raised:
        run_analysis_job.apply(args=[str(job.id)], throw=True)

    session.expire_all()
    saved = session.get(AnalysisJob, job.id)
    assert saved is not None
    assert saved.status is JobStatus.RUNNING
    assert saved.error_code is None
    assert saved.completed_at is None
    assert raised.value.when == 5
    assert "steam_unavailable" in str(raised.value)
    assert factory.closed == [TargetType.GAME]


def test_invalid_model_output_receives_a_clean_full_job_retry(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(session)
    executor, _factory = _executor(
        session, FakePipeline(InvalidModelOutput("deepseek_model_output_invalid"))
    )
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )
    with pytest.raises(Retry):
        run_analysis_job.apply(args=[str(job.id)], throw=True)
    session.expire_all()
    assert session.get(AnalysisJob, job.id).status is JobStatus.RUNNING


def test_last_transient_attempt_persists_safe_retryable_failure(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(session)
    executor, _factory = _executor(
        session, FakePipeline(TransientIntegrationError("deepseek_unavailable"))
    )
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_retry_policy",
        lambda: RetryPolicy(max_retries=3, base_delay_seconds=1, max_delay_seconds=8),
    )

    assert (
        run_analysis_job.apply(args=[str(job.id)], retries=3, throw=True).get() is None
    )
    session.expire_all()
    saved = session.get(AnalysisJob, job.id)
    assert saved is not None
    assert saved.status is JobStatus.FAILED
    assert saved.error_code == "deepseek_unavailable"
    assert saved.error_message == "Analysis is temporarily unavailable. Please retry."
    assert saved.retryable is True
    assert saved.completed_at == NOW


def test_permanent_failure_fails_immediately_without_celery_retry(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(session)
    executor, _factory = _executor(
        session, FakePipeline(PermanentIntegrationError("steam_game_not_found"))
    )
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )

    run_analysis_job.apply(args=[str(job.id)], throw=True).get()
    session.expire_all()
    saved = session.get(AnalysisJob, job.id)
    assert saved is not None
    assert saved.status is JobStatus.FAILED
    assert saved.error_code == "steam_game_not_found"
    assert saved.error_message == "Analysis could not be completed for this target."
    assert saved.retryable is False


def test_unexpected_exception_is_contained_and_never_persisted_verbatim(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(session)
    executor, _factory = _executor(
        session, FakePipeline(RuntimeError("password=do-not-store"))
    )
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )

    run_analysis_job.apply(args=[str(job.id)], throw=True).get()
    session.expire_all()
    saved = session.get(AnalysisJob, job.id)
    assert saved is not None
    assert saved.error_code == "analysis_internal_error"
    assert saved.error_message == "Analysis failed unexpectedly. Please retry."
    assert saved.retryable is True
    assert "password" not in str(saved.error_message)


def test_celery_control_flow_exception_is_never_persisted_as_business_failure(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(session)
    executor, _factory = _executor(session, FakePipeline(Retry("worker-control")))
    monkeypatch.setattr(
        "app.workers.analysis_tasks.get_analysis_executor", lambda: executor
    )

    with pytest.raises(Retry):
        run_analysis_job.apply(args=[str(job.id)], throw=True)
    session.expire_all()
    saved = session.get(AnalysisJob, job.id)
    assert saved is not None
    assert saved.status is JobStatus.RUNNING
    assert saved.error_code is None


def test_terminal_failure_is_idempotent_and_preserves_first_outcome(
    session: Session,
) -> None:
    job = _job(session)
    factory = lambda: _session_factory(session)
    first = TerminalFailure(
        code="steam_game_not_found",
        message="Analysis could not be completed for this target.",
        retryable=False,
    )
    second = TerminalFailure(
        code="analysis_queue_unavailable",
        message="Analysis could not be queued. Please retry.",
        retryable=True,
    )
    write_terminal_failure(job.id, first, session_factory=factory, clock=lambda: NOW)
    write_terminal_failure(job.id, second, session_factory=factory, clock=lambda: NOW)
    session.expire_all()
    saved = session.get(AnalysisJob, job.id)
    assert saved is not None
    assert (saved.error_code, saved.retryable) == ("steam_game_not_found", False)


@pytest.mark.parametrize("terminal_state", ["missing", "failed", "succeeded"])
def test_terminal_noop_never_evaluates_failure_clock(
    session: Session, terminal_state: str
) -> None:
    if terminal_state == "missing":
        job_id = uuid4()
    else:
        job = _job(
            session,
            status=(
                JobStatus.FAILED if terminal_state == "failed" else JobStatus.SUCCEEDED
            ),
        )
        job_id = job.id
        if terminal_state == "succeeded":
            profile = GameProfile(
                steam_app_id=job.canonical_target_id,
                canonical_url=job.canonical_url,
                sort_name="Valid terminal success",
            )
            session.add(profile)
            session.flush()
            job.profile_id = profile.id
            job.result_payload = {"profile_id": str(profile.id)}
            session.flush()

    def forbidden_clock() -> datetime:
        raise AssertionError("terminal no-op must not read the clock")

    assert (
        write_terminal_failure(
            job_id,
            TerminalFailure(
                code="analysis_internal_error",
                message="Analysis failed unexpectedly. Please retry.",
                retryable=True,
            ),
            session_factory=lambda: _session_factory(session),
            clock=forbidden_clock,
        )
        is False
    )


@pytest.mark.parametrize("target_type", list(TargetType))
def test_valid_success_wins_over_a_late_failure(
    session: Session, target_type: TargetType
) -> None:
    job = _job(session, target_type=target_type, status=JobStatus.SUCCEEDED)
    if target_type is TargetType.GAME:
        profile = GameProfile(
            steam_app_id=job.canonical_target_id,
            canonical_url=job.canonical_url,
            sort_name="Success",
        )
    else:
        profile = CreatorProfile(
            youtube_channel_id=job.canonical_target_id,
            canonical_url=job.canonical_url,
            sort_name="Success",
        )
    session.add(profile)
    session.flush()
    job.profile_id = profile.id
    job.result_payload = {"profile_id": str(profile.id)}
    session.flush()

    changed = write_terminal_failure(
        job.id,
        TerminalFailure(
            code="analysis_internal_error",
            message="Analysis failed unexpectedly. Please retry.",
            retryable=True,
        ),
        session_factory=lambda: _session_factory(session),
        clock=lambda: NOW,
    )
    assert changed is False
    assert job.status is JobStatus.SUCCEEDED


def test_corrupted_success_is_rejected_and_never_overwritten(
    session: Session,
) -> None:
    job = _job(session, status=JobStatus.SUCCEEDED)
    job.profile_id = uuid4()
    job.result_payload = {"profile_id": str(job.profile_id)}
    session.flush()

    with pytest.raises(PermanentIntegrationError) as raised:
        write_terminal_failure(
            job.id,
            TerminalFailure(
                code="analysis_internal_error",
                message="Analysis failed unexpectedly. Please retry.",
                retryable=True,
            ),
            session_factory=lambda: _session_factory(session),
            clock=lambda: NOW,
        )
    assert raised.value.code == "analysis_job_result_invalid"
    assert job.status is JobStatus.SUCCEEDED


@pytest.mark.parametrize("target_type", list(TargetType))
def test_coordinated_malformed_success_is_rejected_and_never_overwritten(
    session: Session, target_type: TargetType
) -> None:
    malformed_id = "AKIASECRETEXAMPLE123"
    malformed_url = "https://evil.example/path?api_key=provider-secret"
    job = AnalysisJob(
        target_type=target_type,
        canonical_target_id=malformed_id,
        canonical_url=malformed_url,
        mode=JobMode.CREATE,
        status=JobStatus.SUCCEEDED,
    )
    if target_type is TargetType.GAME:
        profile = GameProfile(
            steam_app_id=malformed_id,
            canonical_url=malformed_url,
            sort_name="Malformed game success",
        )
    else:
        profile = CreatorProfile(
            youtube_channel_id=malformed_id,
            canonical_url=malformed_url,
            sort_name="Malformed creator success",
        )
    session.add_all([job, profile])
    session.flush()
    job.profile_id = profile.id
    job.result_payload = {"profile_id": str(profile.id)}
    session.flush()

    with pytest.raises(PermanentIntegrationError) as raised:
        write_terminal_failure(
            job.id,
            TerminalFailure(
                code="analysis_internal_error",
                message="Analysis failed unexpectedly. Please retry.",
                retryable=True,
            ),
            session_factory=lambda: _session_factory(session),
            clock=lambda: NOW,
        )

    assert raised.value.code == "analysis_job_result_invalid"
    assert job.status is JobStatus.SUCCEEDED


def test_terminal_failure_validates_aware_clock(session: Session) -> None:
    job = _job(session)
    with pytest.raises(PermanentIntegrationError) as raised:
        write_terminal_failure(
            job.id,
            TerminalFailure(
                code="analysis_internal_error",
                message="Analysis failed unexpectedly. Please retry.",
                retryable=True,
            ),
            session_factory=lambda: _session_factory(session),
            clock=lambda: datetime(2026, 9, 2, 8, 30),
        )
    assert raised.value.code == "analysis_clock_invalid"
