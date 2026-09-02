from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import (
    Barrier,
    BrokenBarrierError,
    Event,
    Lock,
    Thread,
    enumerate as threads,
)
from time import monotonic, sleep
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.targets import (
    CanonicalTarget,
    ChannelResolutionUnavailable,
)
from app.core.crypto import SecretCipher
from app.core.idempotency import request_hash
from app.core.security import hash_workspace_key
from app.db.models.enums import JobMode, JobStatus, TargetType
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile, GameProfile
from app.integrations.errors import PermanentIntegrationError
from app.main import create_app


class AllowAllRateLimiter:
    def allow(self, workspace_key_hash: str, client_address: str) -> bool:
        return True


class NoopJobDispatcher:
    def dispatch(self, job_id: UUID) -> None:
        pass


class FakeChannelResolver:
    def __init__(
        self,
        channel_id: str = "UCresolved123",
        *,
        error: Exception | None = None,
    ) -> None:
        self.channel_id = channel_id
        self.error = error
        self.targets: list[CanonicalTarget] = []

    def resolve_channel(self, target: CanonicalTarget) -> str:
        self.targets.append(target)
        if self.error is not None:
            raise self.error
        return self.channel_id


class SessionCollisionCoordinator:
    """Coordinate only the two Sessions created for one concurrency test."""

    def __init__(
        self,
        *,
        target_id: str | None = None,
        idempotency_key: str | None = None,
        expected_constraint: str | None = None,
    ) -> None:
        if (target_id is None) == (idempotency_key is None):
            raise ValueError("coordinate exactly one ORM operation")
        self._target_id = target_id
        self._idempotency_key = idempotency_key
        self._expected_constraint = expected_constraint
        self._barrier = Barrier(2)
        self._lock = Lock()
        self._lock_acquired = Event()
        self._second_backend_ready = Event()
        self._second_lock_attempt = Event()
        self._arrivals = 0
        self._unique_errors = 0
        self._unexpected_unique_constraints: list[str | None] = []
        self._guarded_flush_sessions: set[int] = set()
        self._guarded_lock_sessions: dict[int, int] = {}
        self._second_backend_pid: int | None = None
        self._observed_lock_waits = 0

        coordinator = self

        class CoordinatedSession(Session):
            def flush(self, objects=None) -> None:
                coordinator._before_flush(self)
                try:
                    return super().flush(objects)
                except IntegrityError as error:
                    coordinator._record_unique_error(error)
                    raise

            def scalar(
                self,
                statement,
                params=None,
                *,
                execution_options=None,
                bind_arguments=None,
                **kwargs,
            ):
                parent_scalar = super().scalar

                def issue_scalar():
                    return parent_scalar(
                        statement,
                        params=params,
                        execution_options=execution_options,
                        bind_arguments=bind_arguments,
                        **kwargs,
                    )

                return coordinator._guard_scalar(self, statement, issue_scalar)

        self.session_class = CoordinatedSession

    @property
    def arrivals(self) -> int:
        with self._lock:
            return self._arrivals

    @property
    def unique_errors(self) -> int:
        with self._lock:
            return self._unique_errors

    @property
    def unexpected_unique_constraints(self) -> list[str | None]:
        with self._lock:
            return list(self._unexpected_unique_constraints)

    @property
    def observed_lock_waits(self) -> int:
        with self._lock:
            return self._observed_lock_waits

    def __enter__(self) -> "SessionCollisionCoordinator":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.abort()

    def abort(self) -> None:
        try:
            self._barrier.abort()
        except BrokenBarrierError:
            pass
        self._lock_acquired.set()
        self._second_backend_ready.set()
        self._second_lock_attempt.set()

    def _before_flush(self, session: Session) -> None:
        if self._target_id is None:
            return
        if not any(
            isinstance(model, AnalysisJob)
            and model.canonical_target_id == self._target_id
            for model in session.new
        ):
            return
        with self._lock:
            session_identity = id(session)
            if session_identity in self._guarded_flush_sessions:
                return
            self._guarded_flush_sessions.add(session_identity)
            self._arrivals += 1
        try:
            self._barrier.wait(timeout=5)
        except BrokenBarrierError as error:
            raise AssertionError(
                "concurrent requests did not reach the guarded SQL point"
            ) from error

    def _guard_scalar(self, session: Session, statement, issue_scalar):
        if not self._is_target_idempotency_lock(statement):
            return issue_scalar()
        with self._lock:
            session_identity = id(session)
            if session_identity in self._guarded_lock_sessions:
                return issue_scalar()
            role = len(self._guarded_lock_sessions)
            if role >= 2:
                return issue_scalar()
            self._guarded_lock_sessions[session_identity] = role
            self._arrivals += 1
        if role == 0:
            result = issue_scalar()
            self._lock_acquired.set()
            if not self._second_backend_ready.wait(timeout=5):
                raise AssertionError("second request did not expose its DB backend")
            if not self._second_lock_attempt.wait(timeout=5):
                raise AssertionError(
                    "second request did not attempt the guarded row lock"
                )
            self._wait_for_second_row_lock(session)
            return result
        backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
        with self._lock:
            self._second_backend_pid = backend_pid
        self._second_backend_ready.set()
        if not self._lock_acquired.wait(timeout=5):
            raise AssertionError("first request did not acquire the guarded row lock")
        self._second_lock_attempt.set()
        return issue_scalar()

    def _wait_for_second_row_lock(self, session: Session) -> None:
        deadline = monotonic() + 5
        while monotonic() < deadline:
            with self._lock:
                backend_pid = self._second_backend_pid
            wait_event_type = session.scalar(
                text(
                    "SELECT wait_event_type FROM pg_stat_activity "
                    "WHERE pid = :backend_pid"
                ),
                {"backend_pid": backend_pid},
            )
            if wait_event_type == "Lock":
                with self._lock:
                    self._observed_lock_waits += 1
                return
            sleep(0.01)
        raise AssertionError("second request never waited on the guarded row lock")

    def _is_target_idempotency_lock(self, statement) -> bool:
        if self._idempotency_key is None:
            return False
        if getattr(statement, "_for_update_arg", None) is None:
            return False
        descriptions = getattr(statement, "column_descriptions", ())
        if not any(
            description.get("entity") is IdempotencyRecord
            for description in descriptions
        ):
            return False
        return self._idempotency_key in statement.compile().params.values()

    def _record_unique_error(self, error: IntegrityError) -> None:
        original = error.orig
        if not isinstance(original, UniqueViolation):
            return
        constraint = original.diag.constraint_name
        with self._lock:
            if constraint == self._expected_constraint:
                self._unique_errors += 1
            else:
                self._unexpected_unique_constraints.append(constraint)


def _profile_fields(canonical_url: str, name: str) -> dict:
    return {
        "canonical_url": canonical_url,
        "sort_name": name,
        "current_facts": {},
        "analysis": {},
        "brief": {},
        "source_status": {},
        "model_metadata": {},
        "prompt_metadata": {},
        "last_analyzed_at": datetime.now(UTC),
    }


def _failed_job(
    session: Session,
    *,
    target_type: TargetType = TargetType.GAME,
    canonical_id: str = "7654321",
    retryable: bool = True,
    status: JobStatus = JobStatus.FAILED,
    mode: JobMode = JobMode.REANALYZE,
) -> AnalysisJob:
    canonical_url = (
        f"https://store.steampowered.com/app/{canonical_id}"
        if target_type is TargetType.GAME
        else f"https://www.youtube.com/channel/{canonical_id}"
    )
    job = AnalysisJob(
        target_type=target_type,
        canonical_target_id=canonical_id,
        canonical_url=canonical_url,
        mode=mode,
        status=status,
        retryable=retryable,
        error_code="upstream_timeout",
        error_message="contains unsafe upstream detail secret=do-not-return",
        result_payload={"hidden": "do-not-return"},
        completed_at=datetime.now(UTC) if status is JobStatus.FAILED else None,
    )
    session.add(job)
    session.flush()
    return job


@contextmanager
def _client_with_session(
    session: Session,
    workspace_access_key: str,
    *,
    channel_resolver=None,
    idempotency_clock=None,
) -> Iterator[TestClient]:
    @contextmanager
    def job_session_factory() -> Iterator[Session]:
        yield session

    optional_dependencies = {}
    if idempotency_clock is not None:
        optional_dependencies["idempotency_clock"] = idempotency_clock
    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        channel_resolver=channel_resolver,
        job_session_factory=job_session_factory,
        job_dispatcher=NoopJobDispatcher(),
        **optional_dependencies,
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {workspace_access_key}"
        yield client


@contextmanager
def _independent_client(
    database_engine: Engine,
    workspace_access_key: str,
    *,
    idempotency_clock=None,
    collision_coordinator: SessionCollisionCoordinator | None = None,
) -> Iterator[TestClient]:
    @contextmanager
    def job_session_factory() -> Iterator[Session]:
        session_class = (
            collision_coordinator.session_class
            if collision_coordinator is not None
            else Session
        )
        with session_class(database_engine, expire_on_commit=False) as session:
            try:
                session.execute(text("SET LOCAL lock_timeout = '8s'"))
                session.execute(text("SET LOCAL statement_timeout = '12s'"))
                yield session
            except Exception:
                session.rollback()
                raise

    optional_dependencies = {}
    if idempotency_clock is not None:
        optional_dependencies["idempotency_clock"] = idempotency_clock
    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        job_session_factory=job_session_factory,
        job_dispatcher=NoopJobDispatcher(),
        **optional_dependencies,
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {workspace_access_key}"
        yield client


def _run_two_requests(
    callables,
    *,
    abort,
    cleanup=lambda: None,
    timeout: float = 15,
    teardown_timeout: float = 1,
    thread_name_prefix: str = "analysis-job-concurrency",
):
    outcomes: Queue[tuple[int, object | None, BaseException | None]] = Queue()

    def run(index: int, callable_) -> None:
        try:
            outcomes.put((index, callable_(), None))
        except BaseException as error:
            outcomes.put((index, None, error))
            abort()

    worker_threads = [
        Thread(
            target=run,
            args=(index, callable_),
            name=f"{thread_name_prefix}-{index}",
            daemon=True,
        )
        for index, callable_ in enumerate(callables)
    ]
    for worker_thread in worker_threads:
        worker_thread.start()
    deadline = monotonic() + timeout
    for worker_thread in worker_threads:
        worker_thread.join(timeout=max(0, deadline - monotonic()))
    alive_threads = [thread for thread in worker_threads if thread.is_alive()]
    if alive_threads:
        abort()
        teardown_deadline = monotonic() + teardown_timeout
        for worker_thread in alive_threads:
            worker_thread.join(timeout=max(0, teardown_deadline - monotonic()))
        cleanup_errors: Queue[BaseException] = Queue()

        def run_cleanup() -> None:
            try:
                cleanup()
            except BaseException as error:
                cleanup_errors.put(error)

        cleanup_thread = Thread(
            target=run_cleanup,
            name=f"{thread_name_prefix}-cleanup",
            daemon=True,
        )
        cleanup_thread.start()
        cleanup_thread.join(timeout=teardown_timeout)
        still_alive = [thread.name for thread in worker_threads if thread.is_alive()]
        if cleanup_thread.is_alive():
            still_alive.append(cleanup_thread.name)
        if still_alive:
            raise AssertionError(
                f"concurrent teardown failed to stop: {', '.join(still_alive)}"
            )
        if not cleanup_errors.empty():
            raise cleanup_errors.get_nowait()
        raise AssertionError("concurrent workers exceeded their bounded timeout")
    abort()
    ordered: list[object | None] = [None] * len(worker_threads)
    errors: list[tuple[int, BaseException]] = []
    while not outcomes.empty():
        index, value, error = outcomes.get_nowait()
        ordered[index] = value
        if error is not None:
            errors.append((index, error))
    if errors:
        errors.sort(key=lambda item: item[0])
        raise errors[0][1]
    return ordered


def _cleanup_concurrency_rows(
    database_engine: Engine,
    *,
    target_ids: set[str],
    idempotency_keys: set[str],
) -> None:
    with Session(database_engine) as cleanup_session:
        cleanup_session.execute(text("SET LOCAL lock_timeout = '8s'"))
        cleanup_session.execute(text("SET LOCAL statement_timeout = '12s'"))
        cleanup_session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.key.in_(idempotency_keys)
            )
        )
        cleanup_session.execute(
            delete(AnalysisJob).where(
                AnalysisJob.canonical_target_id.in_(target_ids)
            )
        )
        cleanup_session.commit()
    with Session(database_engine) as verification_session:
        assert verification_session.scalar(
            select(func.count()).select_from(IdempotencyRecord).where(
                IdempotencyRecord.key.in_(idempotency_keys)
            )
        ) == 0
        assert verification_session.scalar(
            select(func.count()).select_from(AnalysisJob).where(
                AnalysisJob.canonical_target_id.in_(target_ids)
            )
        ) == 0


def test_session_collision_coordinator_does_not_install_engine_wide_listeners(
    database_engine: Engine,
) -> None:
    before_cursor_execute = len(database_engine.dispatch.before_cursor_execute)
    handle_error = len(database_engine.dialect.dispatch.handle_error)
    probe = SessionCollisionCoordinator(
        target_id="1234567890",
    )

    with probe:
        assert (
            len(database_engine.dispatch.before_cursor_execute)
            == before_cursor_execute
        )
        assert len(database_engine.dialect.dispatch.handle_error) == handle_error


def test_concurrent_runner_aborts_and_cleans_up_within_its_timeout() -> None:
    release_worker = Event()
    abort_called = Event()
    cleanup_called = Event()
    thread_prefix = f"bounded-concurrency-{uuid4().hex}"

    def blocked_worker() -> None:
        release_worker.wait(timeout=5)

    def abort() -> None:
        abort_called.set()
        release_worker.set()

    started_at = monotonic()
    with pytest.raises(AssertionError, match="concurrent workers exceeded"):
        _run_two_requests(
            [blocked_worker, lambda: None],
            abort=abort,
            cleanup=cleanup_called.set,
            timeout=0.05,
            teardown_timeout=0.5,
            thread_name_prefix=thread_prefix,
        )

    assert monotonic() - started_at < 1
    assert abort_called.is_set()
    assert cleanup_called.is_set()
    assert not [thread for thread in threads() if thread.name.startswith(thread_prefix)]


def test_duplicate_active_job_is_returned(auth_client: TestClient) -> None:
    headers = {"Idempotency-Key": "same-request"}
    payload = {
        "target_type": "game",
        "url": "https://store.steampowered.com/app/1245620",
    }
    first = auth_client.post(
        "/api/v1/jobs/analysis", headers=headers, json=payload
    )
    second = auth_client.post(
        "/api/v1/jobs/analysis", headers=headers, json=payload
    )
    assert first.json()["id"] == second.json()["id"]


def test_analysis_requires_authentication_before_idempotency(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs/analysis",
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/10",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "workspace_key_invalid"


@pytest.mark.parametrize(
    "key",
    [None, "short", "contains space", "x" * 129, "contains/slash"],
)
def test_analysis_requires_a_bounded_safe_idempotency_key(
    auth_client: TestClient, key: str | None
) -> None:
    headers = {} if key is None else {"Idempotency-Key": key}
    response = auth_client.post(
        "/api/v1/jobs/analysis",
        headers=headers,
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/11",
        },
    )
    if key is None:
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "request_invalid"
    else:
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "idempotency_key_invalid"


def test_analysis_request_is_strict_and_validates_enums(
    auth_client: TestClient,
) -> None:
    unknown = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "unknown-field-key"},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/12",
            "unexpected": True,
        },
    )
    invalid_enum = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "invalid-enum-key"},
        json={
            "target_type": "publisher",
            "url": "https://store.steampowered.com/app/12",
            "mode": "refresh",
        },
    )
    assert unknown.status_code == 422
    assert invalid_enum.status_code == 422
    assert unknown.json()["error"]["code"] == "request_invalid"
    assert invalid_enum.json()["error"]["code"] == "request_invalid"


def test_invalid_target_returns_safe_error(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "invalid-target-key"},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com.evil.example/app/13",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "analysis_target_invalid"
    assert "evil.example" not in str(response.json())


def test_same_key_canonical_url_variant_replays_stored_response(
    auth_client: TestClient,
) -> None:
    headers = {"Idempotency-Key": "canonical-replay-key"}
    first = auth_client.post(
        "/api/v1/jobs/analysis",
        headers=headers,
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/20/Display_Slug",
        },
    )
    second = auth_client.post(
        "/api/v1/jobs/analysis",
        headers=headers,
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/20?l=english#reviews",
        },
    )
    assert first.status_code == 201
    assert second.status_code == first.status_code
    assert second.json() == first.json()


def test_same_key_different_canonical_request_conflicts_without_new_job(
    auth_client: TestClient, session: Session
) -> None:
    key = "payload-conflict-key"
    first = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": key},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/21",
        },
    )
    conflict = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": key},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/22",
        },
    )
    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_conflict"
    assert session.scalar(
        select(func.count()).select_from(AnalysisJob).where(
            AnalysisJob.canonical_target_id.in_(("21", "22"))
        )
    ) == 1


def test_new_idempotency_record_expires_exactly_twenty_four_hours_later(
    session: Session, workspace_access_key: str
) -> None:
    fixed_now = datetime(2026, 9, 2, 4, 0, tzinfo=UTC)
    key = "stored-expiry-key"
    with _client_with_session(
        session,
        workspace_access_key,
        idempotency_clock=lambda: fixed_now,
    ) as client:
        response = client.post(
            "/api/v1/jobs/analysis",
            headers={"Idempotency-Key": key},
            json={
                "target_type": "game",
                "url": "https://store.steampowered.com/app/600",
            },
        )

    record = session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.key == key)
    )
    assert response.status_code == 201
    assert record is not None
    assert record.expires_at == fixed_now + timedelta(hours=24)


@pytest.mark.parametrize(
    ("clock_offset", "should_replay"),
    [
        (timedelta(microseconds=-1), True),
        (timedelta(0), False),
    ],
)
def test_idempotency_expiry_boundary_is_exclusive(
    session: Session,
    workspace_access_key: str,
    clock_offset: timedelta,
    should_replay: bool,
) -> None:
    expires_at = datetime(2026, 9, 3, 4, 0, tzinfo=UTC)
    now = expires_at + clock_offset
    key = f"expiry-boundary-{'before' if should_replay else 'at'}"
    digest = request_hash(
        method="POST",
        path="/api/v1/jobs/analysis",
        canonical_request={
            "target_type": "game",
            "canonical_target_id": "601",
            "mode": "create",
        },
    )
    old_record = IdempotencyRecord(
        key=key,
        request_hash=digest,
        method="POST",
        path="/api/v1/jobs/analysis",
        response_status=200,
        response_body={"sentinel": "old-response"},
        expires_at=expires_at,
    )
    session.add(old_record)
    session.flush()

    with _client_with_session(
        session,
        workspace_access_key,
        idempotency_clock=lambda: now,
    ) as client:
        response = client.post(
            "/api/v1/jobs/analysis",
            headers={"Idempotency-Key": key},
            json={
                "target_type": "game",
                "url": "https://store.steampowered.com/app/601",
            },
        )

    if should_replay:
        assert response.status_code == 200
        assert response.json() == {"sentinel": "old-response"}
        assert session.get(IdempotencyRecord, old_record.id) is not None
    else:
        assert response.status_code == 201
        assert response.json()["canonical_target_id"] == "601"
        replacement = session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        )
        assert replacement is not None
        assert replacement.id != old_record.id
        assert replacement.expires_at == now + timedelta(hours=24)


@pytest.mark.parametrize("same_request", [True, False])
def test_expired_key_can_be_reused_for_same_or_different_request(
    session: Session,
    workspace_access_key: str,
    same_request: bool,
) -> None:
    now = datetime(2026, 9, 4, 4, 0, tzinfo=UTC)
    old_target_id = "602"
    new_target_id = old_target_id if same_request else "603"
    key = f"expired-reuse-{'same' if same_request else 'different'}"
    old_record = IdempotencyRecord(
        key=key,
        request_hash=request_hash(
            method="POST",
            path="/api/v1/jobs/analysis",
            canonical_request={
                "target_type": "game",
                "canonical_target_id": old_target_id,
                "mode": "create",
            },
        ),
        method="POST",
        path="/api/v1/jobs/analysis",
        response_status=200,
        response_body={"sentinel": "expired-response"},
        expires_at=now - timedelta(seconds=1),
    )
    session.add(old_record)
    session.flush()

    with _client_with_session(
        session,
        workspace_access_key,
        idempotency_clock=lambda: now,
    ) as client:
        response = client.post(
            "/api/v1/jobs/analysis",
            headers={"Idempotency-Key": key},
            json={
                "target_type": "game",
                "url": (
                    "https://store.steampowered.com/app/" + new_target_id
                ),
            },
        )

    assert response.status_code == 201
    assert response.json()["canonical_target_id"] == new_target_id
    replacement = session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.key == key)
    )
    assert replacement is not None
    assert replacement.id != old_record.id
    assert replacement.request_hash == request_hash(
        method="POST",
        path="/api/v1/jobs/analysis",
        canonical_request={
            "target_type": "game",
            "canonical_target_id": new_target_id,
            "mode": "create",
        },
    )
    assert replacement.expires_at == now + timedelta(hours=24)


def test_failed_reuse_keeps_expired_record_and_business_state_atomic(
    session: Session, workspace_access_key: str
) -> None:
    now = datetime(2026, 9, 5, 4, 0, tzinfo=UTC)
    missing_job_id = uuid4()
    key = "expired-failed-reuse"
    old_record = IdempotencyRecord(
        key=key,
        request_hash=request_hash(
            method="POST",
            path=f"/api/v1/jobs/analysis/{missing_job_id}/retry",
            canonical_request={"source_job_id": str(missing_job_id)},
        ),
        method="POST",
        path=f"/api/v1/jobs/analysis/{missing_job_id}/retry",
        response_status=200,
        response_body={"sentinel": "expired-response"},
        expires_at=now - timedelta(seconds=1),
    )
    session.add(old_record)
    session.flush()

    with _client_with_session(
        session,
        workspace_access_key,
        idempotency_clock=lambda: now,
    ) as client:
        response = client.post(
            f"/api/v1/jobs/analysis/{missing_job_id}/retry",
            headers={"Idempotency-Key": key},
            json={},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_job_not_found"
    session.expire_all()
    preserved = session.get(IdempotencyRecord, old_record.id)
    assert preserved is not None
    assert preserved.response_body == {"sentinel": "expired-response"}
    assert session.scalar(
        select(func.count()).select_from(AnalysisJob).where(
            AnalysisJob.id == missing_job_id
        )
    ) == 0


def test_different_keys_and_url_variants_reuse_global_active_job(
    auth_client: TestClient,
) -> None:
    first = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "global-dedupe-one"},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/23/First",
        },
    )
    second = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "global-dedupe-two"},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/23?l=schinese",
        },
    )
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_existing_profile_create_returns_profile_without_job(
    auth_client: TestClient, session: Session
) -> None:
    profile = GameProfile(
        steam_app_id="30",
        **_profile_fields("https://store.steampowered.com/app/30", "Existing"),
    )
    session.add(profile)
    session.flush()

    response = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "existing-profile-create"},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/30",
            "mode": "create",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "outcome": "existing_profile",
        "existing_profile_id": str(profile.id),
        "target_type": "game",
        "canonical_target_id": "30",
        "canonical_url": "https://store.steampowered.com/app/30",
    }
    assert session.scalar(
        select(func.count()).select_from(AnalysisJob).where(
            AnalysisJob.canonical_target_id == "30"
        )
    ) == 0


def test_existing_profile_reanalyze_creates_job(
    auth_client: TestClient, session: Session
) -> None:
    profile = CreatorProfile(
        youtube_channel_id="UCexisting123",
        **_profile_fields(
            "https://www.youtube.com/channel/UCexisting123", "Existing Creator"
        ),
    )
    session.add(profile)
    session.flush()

    response = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "existing-reanalyze"},
        json={
            "target_type": "creator",
            "url": "https://youtube.com/channel/UCexisting123",
            "mode": "reanalyze",
        },
    )
    assert response.status_code == 201
    assert response.json()["mode"] == "reanalyze"
    assert response.json()["profile_id"] is None


@pytest.mark.parametrize("target_type", [TargetType.GAME, TargetType.CREATOR])
@pytest.mark.parametrize("active_status", [JobStatus.QUEUED, JobStatus.RUNNING])
def test_create_prefers_existing_profile_over_active_reanalysis(
    auth_client: TestClient,
    session: Session,
    target_type: TargetType,
    active_status: JobStatus,
) -> None:
    suffix = "1" if active_status is JobStatus.QUEUED else "2"
    if target_type is TargetType.GAME:
        canonical_id = f"31{suffix}"
        canonical_url = f"https://store.steampowered.com/app/{canonical_id}"
        profile = GameProfile(
            steam_app_id=canonical_id,
            **_profile_fields(canonical_url, "Existing Game"),
        )
    else:
        canonical_id = f"UCexistingMatrix{suffix}"
        canonical_url = f"https://www.youtube.com/channel/{canonical_id}"
        profile = CreatorProfile(
            youtube_channel_id=canonical_id,
            **_profile_fields(canonical_url, "Existing Creator"),
        )
    active = AnalysisJob(
        target_type=target_type,
        canonical_target_id=canonical_id,
        canonical_url=canonical_url,
        mode=JobMode.REANALYZE,
        status=active_status,
        correlation_id="original-active-correlation",
    )
    session.add_all((profile, active))
    session.flush()
    key = f"profile-precedence-{target_type.value}-{active_status.value}"
    payload = {
        "target_type": target_type.value,
        "url": canonical_url,
        "mode": "create",
    }

    first = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    replay = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": key},
        json=payload,
    )

    expected = {
        "outcome": "existing_profile",
        "existing_profile_id": str(profile.id),
        "target_type": target_type.value,
        "canonical_target_id": canonical_id,
        "canonical_url": canonical_url,
    }
    assert first.status_code == 200
    assert first.json() == expected
    assert replay.status_code == 200
    assert replay.json() == expected
    session.refresh(active)
    assert active.status is active_status
    assert active.mode is JobMode.REANALYZE
    assert active.correlation_id == "original-active-correlation"
    assert session.scalar(
        select(func.count()).select_from(AnalysisJob).where(
            AnalysisJob.target_type == target_type,
            AnalysisJob.canonical_target_id == canonical_id,
        )
    ) == 1


@pytest.mark.parametrize("target_type", [TargetType.GAME, TargetType.CREATOR])
def test_reanalyze_with_existing_profile_still_returns_active_job(
    auth_client: TestClient,
    session: Session,
    target_type: TargetType,
) -> None:
    if target_type is TargetType.GAME:
        canonical_id = "319"
        canonical_url = f"https://store.steampowered.com/app/{canonical_id}"
        profile = GameProfile(
            steam_app_id=canonical_id,
            **_profile_fields(canonical_url, "Existing Game"),
        )
    else:
        canonical_id = "UCexistingReanalyze9"
        canonical_url = f"https://www.youtube.com/channel/{canonical_id}"
        profile = CreatorProfile(
            youtube_channel_id=canonical_id,
            **_profile_fields(canonical_url, "Existing Creator"),
        )
    active = AnalysisJob(
        target_type=target_type,
        canonical_target_id=canonical_id,
        canonical_url=canonical_url,
        mode=JobMode.REANALYZE,
        status=JobStatus.RUNNING,
    )
    session.add_all((profile, active))
    session.flush()

    response = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={
            "Idempotency-Key": f"reanalyze-precedence-{target_type.value}"
        },
        json={
            "target_type": target_type.value,
            "url": canonical_url,
            "mode": "reanalyze",
        },
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "job"
    assert response.json()["id"] == str(active.id)


def test_handle_resolves_before_session_and_dedupes_by_channel_id(
    session: Session, workspace_access_key: str
) -> None:
    resolver = FakeChannelResolver("UCresolved123")
    session_opened = False

    @contextmanager
    def ordered_session_factory() -> Iterator[Session]:
        nonlocal session_opened
        assert resolver.targets, "database session opened before Handle resolution"
        session_opened = True
        yield session

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        channel_resolver=resolver,
        job_session_factory=ordered_session_factory,
        job_dispatcher=NoopJobDispatcher(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/jobs/analysis",
            headers={
                "Authorization": f"Bearer {workspace_access_key}",
                "Idempotency-Key": "handle-resolution-key",
            },
            json={
                "target_type": "creator",
                "url": "https://youtube.com/@ExampleCreator",
            },
        )
    assert response.status_code == 201
    assert session_opened is True
    assert response.json()["canonical_target_id"] == "UCresolved123"
    assert response.json()["canonical_url"] == (
        "https://www.youtube.com/channel/UCresolved123"
    )


def test_unavailable_handle_resolver_fails_safely_without_database_work(
    session: Session, workspace_access_key: str
) -> None:
    resolver = FakeChannelResolver(
        error=ChannelResolutionUnavailable("API key=secret")
    )
    session_calls = 0

    @contextmanager
    def forbidden_session_factory() -> Iterator[Session]:
        nonlocal session_calls
        session_calls += 1
        yield session

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        channel_resolver=resolver,
        job_session_factory=forbidden_session_factory,
        job_dispatcher=NoopJobDispatcher(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/jobs/analysis",
            headers={
                "Authorization": f"Bearer {workspace_access_key}",
                "Idempotency-Key": "handle-failure-key",
            },
            json={
                "target_type": "creator",
                "url": "https://youtube.com/@ExampleCreator",
            },
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "channel_resolution_unavailable"
    assert "secret" not in str(response.json())
    assert session_calls == 0


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            PermanentIntegrationError("youtube_channel_not_found"),
            422,
            "analysis_target_invalid",
        ),
        (
            PermanentIntegrationError("analysis_configuration_invalid"),
            503,
            "analysis_configuration_invalid",
        ),
        (
            PermanentIntegrationError("youtube_request_rejected"),
            502,
            "youtube_request_rejected",
        ),
        (
            PermanentIntegrationError("youtube_response_invalid"),
            502,
            "youtube_response_invalid",
        ),
    ],
)
def test_handle_permanent_failures_are_nonretryable_and_safely_classified(
    session: Session,
    workspace_access_key: str,
    error: PermanentIntegrationError,
    status_code: int,
    code: str,
) -> None:
    session_calls = 0

    @contextmanager
    def forbidden_session_factory() -> Iterator[Session]:
        nonlocal session_calls
        session_calls += 1
        yield session

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        channel_resolver=FakeChannelResolver(error=error),
        job_session_factory=forbidden_session_factory,
        job_dispatcher=NoopJobDispatcher(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/jobs/analysis",
            headers={
                "Authorization": f"Bearer {workspace_access_key}",
                "Idempotency-Key": f"handle-permanent-{code}",
            },
            json={
                "target_type": "creator",
                "url": "https://youtube.com/@ExampleCreator",
            },
        )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["retryable"] is False
    assert session_calls == 0


def test_unexpected_handle_failure_stays_internal_and_safe(
    session: Session, workspace_access_key: str
) -> None:
    session_calls = 0

    @contextmanager
    def session_factory() -> Iterator[Session]:
        nonlocal session_calls
        session_calls += 1
        yield session

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        channel_resolver=FakeChannelResolver(
            error=RuntimeError("master-key-path=/private/secret")
        ),
        job_session_factory=session_factory,
        job_dispatcher=NoopJobDispatcher(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/jobs/analysis",
            headers={
                "Authorization": f"Bearer {workspace_access_key}",
                "Idempotency-Key": "handle-unexpected",
            },
            json={
                "target_type": "creator",
                "url": "https://youtube.com/@ExampleCreator",
            },
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "master-key" not in str(response.json())
    assert session_calls == 0


def test_default_production_resolver_does_not_treat_handle_as_channel_id(
    session: Session, workspace_access_key: str
) -> None:
    with _client_with_session(session, workspace_access_key) as client:
        response = client.post(
            "/api/v1/jobs/analysis",
            headers={"Idempotency-Key": "no-resolver-key"},
            json={
                "target_type": "creator",
                "url": "https://youtube.com/@ExampleCreator",
            },
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "analysis_configuration_invalid"
    assert response.json()["error"]["message"] == (
        "Analysis service configuration is unavailable."
    )
    assert response.json()["error"]["retryable"] is False


def test_job_response_does_not_leak_internal_fields(
    auth_client: TestClient, session: Session
) -> None:
    active = _failed_job(
        session,
        canonical_id="40",
        status=JobStatus.QUEUED,
        retryable=True,
    )
    active.error_message = "unsafe secret"
    active.result_payload = {"secret": "hidden"}
    session.flush()

    response = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "response-redaction-key"},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/40",
        },
    )
    serialized = str(response.json())
    assert response.status_code == 200
    assert response.json()["id"] == str(active.id)
    assert "unsafe" not in serialized
    assert "hidden" not in serialized
    assert "idempotency" not in serialized.casefold()


@pytest.mark.parametrize(
    ("status", "retryable", "expected_code"),
    [
        (JobStatus.QUEUED, True, "analysis_job_not_failed"),
        (JobStatus.RUNNING, True, "analysis_job_not_failed"),
        (JobStatus.SUCCEEDED, True, "analysis_job_not_failed"),
        (JobStatus.FAILED, False, "analysis_job_not_retryable"),
    ],
)
def test_retry_rejects_ineligible_source_jobs(
    auth_client: TestClient,
    session: Session,
    status: JobStatus,
    retryable: bool,
    expected_code: str,
) -> None:
    source = _failed_job(
        session,
        canonical_id=str(100 + list(JobStatus).index(status)),
        status=status,
        retryable=retryable,
    )
    response = auth_client.post(
        f"/api/v1/jobs/analysis/{source.id}/retry",
        headers={"Idempotency-Key": f"retry-ineligible-{status.value}"},
        json={},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == expected_code


def test_retry_missing_job_is_safe(auth_client: TestClient) -> None:
    response = auth_client.post(
        f"/api/v1/jobs/analysis/{uuid4()}/retry",
        headers={"Idempotency-Key": "retry-missing-job"},
        json={},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_job_not_found"


def test_retry_requires_authentication_and_idempotency_header(
    client: TestClient, auth_client: TestClient, session: Session
) -> None:
    source = _failed_job(session, canonical_id="205")
    auth_client.headers.pop("Authorization")
    unauthenticated = client.post(
        f"/api/v1/jobs/analysis/{source.id}/retry", json={}
    )
    client.headers["Authorization"] = "Bearer test-workspace-access-key"
    missing_key = client.post(
        f"/api/v1/jobs/analysis/{source.id}/retry", json={}
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "workspace_key_invalid"
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "request_invalid"


def test_retry_creates_new_historical_job_and_replays_same_key(
    auth_client: TestClient, session: Session
) -> None:
    source = _failed_job(session, canonical_id="200", mode=JobMode.REANALYZE)
    headers = {"Idempotency-Key": "retry-history-key"}
    first = auth_client.post(
        f"/api/v1/jobs/analysis/{source.id}/retry", headers=headers, json={}
    )
    second = auth_client.post(
        f"/api/v1/jobs/analysis/{source.id}/retry", headers=headers, json={}
    )
    session.refresh(source)
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert UUID(first.json()["id"]) != source.id
    assert first.json()["mode"] == "reanalyze"
    assert source.status is JobStatus.FAILED
    assert source.error_code == "upstream_timeout"
    assert session.scalar(
        select(func.count()).select_from(AnalysisJob).where(
            AnalysisJob.canonical_target_id == "200"
        )
    ) == 2


def test_retry_accepts_an_empty_request_body(
    auth_client: TestClient, session: Session
) -> None:
    source = _failed_job(session, canonical_id="207")
    response = auth_client.post(
        f"/api/v1/jobs/analysis/{source.id}/retry",
        headers={"Idempotency-Key": "retry-without-body"},
    )
    assert response.status_code == 201
    assert response.json()["canonical_target_id"] == "207"


def test_retry_reuses_an_existing_active_duplicate(
    auth_client: TestClient, session: Session
) -> None:
    source = _failed_job(session, canonical_id="201")
    active = AnalysisJob(
        target_type=source.target_type,
        canonical_target_id=source.canonical_target_id,
        canonical_url=source.canonical_url,
        mode=JobMode.REANALYZE,
        status=JobStatus.RUNNING,
    )
    session.add(active)
    session.flush()

    response = auth_client.post(
        f"/api/v1/jobs/analysis/{source.id}/retry",
        headers={"Idempotency-Key": "retry-active-duplicate"},
        json={},
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(active.id)
    assert session.scalar(
        select(func.count()).select_from(AnalysisJob).where(
            AnalysisJob.canonical_target_id == "201"
        )
    ) == 2


def test_retry_request_rejects_unknown_fields(
    auth_client: TestClient, session: Session
) -> None:
    source = _failed_job(session, canonical_id="202")
    response = auth_client.post(
        f"/api/v1/jobs/analysis/{source.id}/retry",
        headers={"Idempotency-Key": "retry-unknown-field"},
        json={"mode": "create"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"


def test_idempotency_key_cannot_cross_create_and_retry_paths(
    auth_client: TestClient, session: Session
) -> None:
    key = "cross-path-key"
    created = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": key},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/203",
        },
    )
    source = _failed_job(session, canonical_id="204")
    conflict = auth_client.post(
        f"/api/v1/jobs/analysis/{source.id}/retry",
        headers={"Idempotency-Key": key},
        json={},
    )
    assert created.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_conflict"


def test_correlation_id_is_captured_but_idempotency_key_is_not_logged(
    auth_client: TestClient,
    session: Session,
    captured_logs,
) -> None:
    key = "never-log-this-idempotency-key"
    response = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={
            "Idempotency-Key": key,
            "X-Correlation-ID": "job-correlation-123",
        },
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/206",
        },
    )
    job = session.get(AnalysisJob, UUID(response.json()["id"]))
    assert response.status_code == 201
    assert job is not None
    assert job.correlation_id == "job-correlation-123"
    assert key not in captured_logs.text


def test_concurrent_same_key_creates_one_job_and_one_record(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_000_000_000 + (uuid4().int % 1_000_000_000))
    key = f"same-{uuid4().hex}"
    payload = {
        "target_type": "game",
        "url": f"https://store.steampowered.com/app/{app_id}",
    }
    probe = SessionCollisionCoordinator(
        target_id=app_id,
        expected_constraint="uq_analysis_jobs_active_target",
    )
    try:
        with probe, _independent_client(
            database_engine,
            workspace_access_key,
            collision_coordinator=probe,
        ) as client:
            responses = _run_two_requests(
                [
                    lambda: client.post(
                        "/api/v1/jobs/analysis",
                        headers={"Idempotency-Key": key},
                        json=payload,
                    )
                    for _index in range(2)
                ],
                abort=probe.abort,
                cleanup=lambda: _cleanup_concurrency_rows(
                    database_engine,
                    target_ids={app_id},
                    idempotency_keys={key},
                ),
            )
        assert probe.arrivals == 2
        assert probe.unique_errors == 1
        assert probe.unexpected_unique_constraints == []
        assert {response.status_code for response in responses} == {201}
        assert len({response.json()["id"] for response in responses}) == 1
        with Session(database_engine) as verification_session:
            assert verification_session.scalar(
                select(func.count()).select_from(AnalysisJob).where(
                    AnalysisJob.canonical_target_id == app_id
                )
            ) == 1
            assert verification_session.scalar(
                select(func.count()).select_from(IdempotencyRecord).where(
                    IdempotencyRecord.key == key
                )
            ) == 1
    finally:
        probe.abort()
        _cleanup_concurrency_rows(
            database_engine,
            target_ids={app_id},
            idempotency_keys={key},
        )


def test_concurrent_different_keys_create_one_active_target_job(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_000_000_000 + (uuid4().int % 1_000_000_000))
    keys = [f"different-{uuid4().hex}", f"different-{uuid4().hex}"]
    payload = {
        "target_type": "game",
        "url": f"https://store.steampowered.com/app/{app_id}",
    }
    probe = SessionCollisionCoordinator(
        target_id=app_id,
        expected_constraint="uq_analysis_jobs_active_target",
    )
    try:
        with probe, _independent_client(
            database_engine,
            workspace_access_key,
            collision_coordinator=probe,
        ) as client:
            responses = _run_two_requests(
                [
                    lambda key=key: client.post(
                        "/api/v1/jobs/analysis",
                        headers={"Idempotency-Key": key},
                        json=payload,
                    )
                    for key in keys
                ],
                abort=probe.abort,
                cleanup=lambda: _cleanup_concurrency_rows(
                    database_engine,
                    target_ids={app_id},
                    idempotency_keys=set(keys),
                ),
            )
        assert probe.arrivals == 2
        assert probe.unique_errors == 1
        assert probe.unexpected_unique_constraints == []
        assert {response.status_code for response in responses} == {200, 201}
        assert len({response.json()["id"] for response in responses}) == 1
        with Session(database_engine) as verification_session:
            assert verification_session.scalar(
                select(func.count()).select_from(AnalysisJob).where(
                    AnalysisJob.canonical_target_id == app_id
                )
            ) == 1
            assert verification_session.scalar(
                select(func.count()).select_from(IdempotencyRecord).where(
                    IdempotencyRecord.key.in_(keys)
                )
            ) == 2
    finally:
        probe.abort()
        _cleanup_concurrency_rows(
            database_engine,
            target_ids={app_id},
            idempotency_keys=set(keys),
        )


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_retry_is_idempotent_and_target_deduplicated(
    same_key: bool,
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_000_000_000 + (uuid4().int % 1_000_000_000))
    with Session(database_engine, expire_on_commit=False) as seed_session:
        source = _failed_job(seed_session, canonical_id=app_id)
        source_id = source.id
        seed_session.commit()
    first_key = f"retry-race-{uuid4().hex}"
    keys = [first_key, first_key if same_key else f"retry-race-{uuid4().hex}"]

    probe = SessionCollisionCoordinator(
        target_id=app_id,
        expected_constraint="uq_analysis_jobs_active_target",
    )
    try:
        with probe, _independent_client(
            database_engine,
            workspace_access_key,
            collision_coordinator=probe,
        ) as client:
            responses = _run_two_requests(
                [
                    lambda key=key: client.post(
                        f"/api/v1/jobs/analysis/{source_id}/retry",
                        headers={"Idempotency-Key": key},
                        json={},
                    )
                    for key in keys
                ],
                abort=probe.abort,
                cleanup=lambda: _cleanup_concurrency_rows(
                    database_engine,
                    target_ids={app_id},
                    idempotency_keys=set(keys),
                ),
            )
        expected_statuses = {201} if same_key else {200, 201}
        assert probe.arrivals == 2
        assert probe.unique_errors == 1
        assert probe.unexpected_unique_constraints == []
        assert {
            response.status_code for response in responses
        } == expected_statuses
        assert len({response.json()["id"] for response in responses}) == 1
        with Session(database_engine) as verification_session:
            source = verification_session.get(AnalysisJob, source_id)
            assert source is not None
            assert source.status is JobStatus.FAILED
            assert verification_session.scalar(
                select(func.count()).select_from(AnalysisJob).where(
                    AnalysisJob.canonical_target_id == app_id
                )
            ) == 2
            assert verification_session.scalar(
                select(func.count()).select_from(IdempotencyRecord).where(
                    IdempotencyRecord.key.in_(set(keys))
                )
            ) == len(set(keys))
    finally:
        probe.abort()
        _cleanup_concurrency_rows(
            database_engine,
            target_ids={app_id},
            idempotency_keys=set(keys),
        )


@pytest.mark.parametrize("different_request", [False, True])
def test_concurrent_expired_key_reuse_is_serialized_and_atomic(
    different_request: bool,
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    now = datetime(2026, 9, 6, 4, 0, tzinfo=UTC)
    first_app_id = str(1_000_000_000 + (uuid4().int % 500_000_000))
    second_app_id = (
        str(1_500_000_000 + (uuid4().int % 500_000_000))
        if different_request
        else first_app_id
    )
    target_ids = {first_app_id, second_app_id}
    key = f"expired-race-{uuid4().hex}"
    digest = request_hash(
        method="POST",
        path="/api/v1/jobs/analysis",
        canonical_request={
            "target_type": "game",
            "canonical_target_id": first_app_id,
            "mode": "create",
        },
    )
    with Session(database_engine, expire_on_commit=False) as seed_session:
        old_record = IdempotencyRecord(
            key=key,
            request_hash=digest,
            method="POST",
            path="/api/v1/jobs/analysis",
            response_status=200,
            response_body={"sentinel": "expired"},
            expires_at=now - timedelta(seconds=1),
        )
        seed_session.add(old_record)
        seed_session.commit()
        old_record_id = old_record.id
    payloads = [
        {
            "target_type": "game",
            "url": f"https://store.steampowered.com/app/{app_id}",
        }
        for app_id in (first_app_id, second_app_id)
    ]
    probe = SessionCollisionCoordinator(
        idempotency_key=key,
        expected_constraint="idempotency_records_key_key",
    )
    try:
        with probe, _independent_client(
            database_engine,
            workspace_access_key,
            idempotency_clock=lambda: now,
            collision_coordinator=probe,
        ) as client:
            responses = _run_two_requests(
                [
                    lambda payload=payload: client.post(
                        "/api/v1/jobs/analysis",
                        headers={"Idempotency-Key": key},
                        json=payload,
                    )
                    for payload in payloads
                ],
                abort=probe.abort,
                cleanup=lambda: _cleanup_concurrency_rows(
                    database_engine,
                    target_ids=target_ids,
                    idempotency_keys={key},
                ),
            )
        assert probe.arrivals == 2
        assert probe.observed_lock_waits == 1
        assert probe.unique_errors == 1
        assert probe.unexpected_unique_constraints == []
        expected_statuses = {201, 409} if different_request else {201}
        assert {
            response.status_code for response in responses
        } == expected_statuses
        successful = [response for response in responses if response.status_code == 201]
        assert successful
        assert len({response.json()["id"] for response in successful}) == 1
        with Session(database_engine) as verification_session:
            replacement = verification_session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
            assert replacement is not None
            assert replacement.id != old_record_id
            assert replacement.expires_at == now + timedelta(hours=24)
            assert verification_session.scalar(
                select(func.count()).select_from(AnalysisJob).where(
                    AnalysisJob.canonical_target_id.in_(target_ids)
                )
            ) == 1
            assert verification_session.scalar(
                select(func.count()).select_from(IdempotencyRecord).where(
                    IdempotencyRecord.key == key
                )
            ) == 1
    finally:
        probe.abort()
        _cleanup_concurrency_rows(
            database_engine,
            target_ids=target_ids,
            idempotency_keys={key},
        )


def test_concurrency_harness_leaves_no_global_listeners_or_worker_threads(
    database_engine: Engine,
) -> None:
    assert len(database_engine.dispatch.before_cursor_execute) == 0
    assert len(database_engine.dialect.dispatch.handle_error) == 0
    assert not [
        thread
        for thread in threads()
        if thread.name.startswith("analysis-job-concurrency")
    ]


def test_openapi_exposes_required_headers_and_safe_outcome_schemas(
    client: TestClient,
) -> None:
    schema = client.app.openapi()
    create_operation = schema["paths"]["/api/v1/jobs/analysis"]["post"]
    retry_operation = schema["paths"][
        "/api/v1/jobs/analysis/{job_id}/retry"
    ]["post"]

    for operation in (create_operation, retry_operation):
        idempotency_header = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert idempotency_header["required"] is True

    create_schema = str(create_operation["responses"])
    retry_schema = str(retry_operation["responses"])
    assert "AnalysisJobResponse" in create_schema
    assert "ExistingProfileResponse" in create_schema
    assert "AnalysisJobResponse" in retry_schema
    for forbidden in (
        "result_payload",
        "error_message",
        "IdempotencyRecord",
        "idempotency_key",
    ):
        assert forbidden not in create_schema
        assert forbidden not in retry_schema
