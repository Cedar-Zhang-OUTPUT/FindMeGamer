from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier, BrokenBarrierError, Lock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation
from sqlalchemy import Engine, delete, event, func, select, text
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
from app.main import create_app


class AllowAllRateLimiter:
    def allow(self, workspace_key_hash: str, client_address: str) -> bool:
        return True


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


class SQLCollisionProbe:
    """Synchronize two real SQL statements and observe DB unique failures."""

    def __init__(
        self,
        database_engine: Engine,
        *,
        statement_fragment: str,
        parameter_marker: str,
    ) -> None:
        self._engine = database_engine
        self._statement_fragment = statement_fragment
        self._parameter_marker = parameter_marker
        self._barrier = Barrier(2)
        self._lock = Lock()
        self._arrivals = 0
        self._unique_errors = 0

    @property
    def arrivals(self) -> int:
        with self._lock:
            return self._arrivals

    @property
    def unique_errors(self) -> int:
        with self._lock:
            return self._unique_errors

    def __enter__(self) -> "SQLCollisionProbe":
        event.listen(
            self._engine,
            "before_cursor_execute",
            self._before_cursor_execute,
        )
        event.listen(self._engine, "handle_error", self._handle_error)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.abort()
        event.remove(
            self._engine,
            "before_cursor_execute",
            self._before_cursor_execute,
        )
        event.remove(self._engine, "handle_error", self._handle_error)

    def abort(self) -> None:
        try:
            self._barrier.abort()
        except BrokenBarrierError:
            pass

    def _before_cursor_execute(
        self,
        connection,
        cursor,
        statement: str,
        parameters,
        context,
        executemany: bool,
    ) -> None:
        if (
            self._statement_fragment not in statement
            or self._parameter_marker not in repr(parameters)
        ):
            return
        with self._lock:
            if self._arrivals >= 2:
                return
            self._arrivals += 1
        try:
            self._barrier.wait(timeout=5)
        except BrokenBarrierError as error:
            raise AssertionError(
                "concurrent requests did not reach the guarded SQL point"
            ) from error

    def _handle_error(self, exception_context) -> None:
        if isinstance(exception_context.original_exception, UniqueViolation):
            with self._lock:
                self._unique_errors += 1


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
) -> Iterator[TestClient]:
    @contextmanager
    def job_session_factory() -> Iterator[Session]:
        with Session(database_engine, expire_on_commit=False) as session:
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
        **optional_dependencies,
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {workspace_access_key}"
        yield client


def _run_two_requests(
    callables,
    *,
    abort,
):
    executor = ThreadPoolExecutor(max_workers=2)
    futures = [executor.submit(callable_) for callable_ in callables]
    try:
        return [future.result(timeout=15) for future in futures]
    finally:
        abort()
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


def _cleanup_concurrency_rows(
    database_engine: Engine,
    *,
    target_ids: set[str],
    idempotency_keys: set[str],
) -> None:
    with Session(database_engine) as cleanup_session:
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
    assert response.json()["error"]["code"] == "channel_resolution_unavailable"


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
    probe = SQLCollisionProbe(
        database_engine,
        statement_fragment="INSERT INTO analysis_jobs",
        parameter_marker=app_id,
    )
    try:
        with probe, _independent_client(
            database_engine, workspace_access_key
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
            )
        assert probe.arrivals == 2
        assert probe.unique_errors >= 1
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
    probe = SQLCollisionProbe(
        database_engine,
        statement_fragment="INSERT INTO analysis_jobs",
        parameter_marker=app_id,
    )
    try:
        with probe, _independent_client(
            database_engine, workspace_access_key
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
            )
        assert probe.arrivals == 2
        assert probe.unique_errors >= 1
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

    probe = SQLCollisionProbe(
        database_engine,
        statement_fragment="INSERT INTO analysis_jobs",
        parameter_marker=app_id,
    )
    try:
        with probe, _independent_client(
            database_engine, workspace_access_key
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
            )
        expected_statuses = {201} if same_key else {200, 201}
        assert probe.arrivals == 2
        assert probe.unique_errors >= 1
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
    probe = SQLCollisionProbe(
        database_engine,
        statement_fragment="FROM idempotency_records",
        parameter_marker=key,
    )
    try:
        with probe, _independent_client(
            database_engine,
            workspace_access_key,
            idempotency_clock=lambda: now,
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
            )
        assert probe.arrivals == 2
        assert probe.unique_errors >= 1
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
