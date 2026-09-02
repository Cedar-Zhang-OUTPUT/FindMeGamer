from contextlib import contextmanager
from datetime import UTC, datetime
import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.core.security import hash_workspace_key
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile, GameProfile
from app.main import create_app
from app.api.routes.jobs import CeleryJobDispatcher
from app.workers.celery_app import create_celery_app


NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


class AllowAllRateLimiter:
    def allow(self, workspace_key_hash: str, client_address: str) -> bool:
        return True


class ObservingDispatcher:
    def __init__(self, engine: Engine, *, error: Exception | None = None) -> None:
        self.engine = engine
        self.error = error
        self.calls: list[UUID] = []
        self.observed_committed: list[tuple[bool, bool]] = []

    def dispatch(self, job_id: UUID) -> None:
        with Session(self.engine) as verification:
            job_exists = verification.get(AnalysisJob, job_id) is not None
            record_exists = (
                verification.scalar(
                    select(IdempotencyRecord.id).where(
                        IdempotencyRecord.response_body["id"].astext == str(job_id)
                    )
                )
                is not None
            )
        self.observed_committed.append((job_exists, record_exists))
        self.calls.append(job_id)
        if self.error is not None:
            raise self.error


class CorruptSuccessThenFailDispatcher(ObservingDispatcher):
    def dispatch(self, job_id: UUID) -> None:
        super().dispatch(job_id)
        with Session(self.engine) as mutate, mutate.begin():
            job = mutate.get(AnalysisJob, job_id)
            assert job is not None
            profile = GameProfile(
                steam_app_id=job.canonical_target_id,
                canonical_url=job.canonical_url,
                sort_name="Concurrent corrupt success",
            )
            mutate.add(profile)
            mutate.flush()
            job.status = JobStatus.SUCCEEDED
            job.stage = AnalysisStage.FINALIZING
            job.completed_units = 5
            job.total_units = 5
            job.profile_id = profile.id
            job.result_payload = {"profile_id": str(uuid4())}
            job.started_at = NOW
            job.completed_at = NOW
        raise RuntimeError("redis://unsafe@broker")


class MalformedSuccessThenFailDispatcher(ObservingDispatcher):
    def dispatch(self, job_id: UUID) -> None:
        super().dispatch(job_id)
        malformed_id = "AKIASECRETEXAMPLE123"
        malformed_url = "https://evil.example/path?api_key=provider-secret"
        with Session(self.engine) as mutate, mutate.begin():
            job = mutate.get(AnalysisJob, job_id)
            assert job is not None
            profile = GameProfile(
                steam_app_id=malformed_id,
                canonical_url=malformed_url,
                sort_name="Concurrent malformed success",
            )
            mutate.add(profile)
            mutate.flush()
            job.canonical_target_id = malformed_id
            job.canonical_url = malformed_url
            job.status = JobStatus.SUCCEEDED
            job.stage = AnalysisStage.FINALIZING
            job.completed_units = 5
            job.total_units = 5
            job.profile_id = profile.id
            job.result_payload = {"profile_id": str(profile.id)}
            job.started_at = NOW
            job.completed_at = NOW
        raise RuntimeError("redis://unsafe@broker")


class ClaimThenFailDispatcher(ObservingDispatcher):
    def dispatch(self, job_id: UUID) -> None:
        super().dispatch(job_id)
        with Session(self.engine) as mutate, mutate.begin():
            job = mutate.get(AnalysisJob, job_id)
            assert job is not None
            job.status = JobStatus.RUNNING
            job.stage = AnalysisStage.FETCHING_DATA
            job.completed_units = 0
            job.total_units = 5
            job.started_at = NOW
        raise RuntimeError("redis://unsafe@broker")


class UnsafeCorrelationThenFailDispatcher(ObservingDispatcher):
    def dispatch(self, job_id: UUID) -> None:
        super().dispatch(job_id)
        with Session(self.engine) as mutate, mutate.begin():
            job = mutate.get(AnalysisJob, job_id)
            assert job is not None
            job.correlation_id = "api-key=secret-value"
        raise RuntimeError("redis://unsafe@broker")


@contextmanager
def _client(
    engine: Engine,
    workspace_access_key: str,
    dispatcher: ObservingDispatcher,
):
    @contextmanager
    def factory():
        with Session(engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        job_session_factory=factory,
        job_dispatcher=dispatcher,
        analysis_failure_clock=lambda: NOW,
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {workspace_access_key}"
        yield client


def _cleanup(engine: Engine, *, app_ids: set[str], keys: set[str]) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.key.in_(keys))
        )
        session.execute(
            delete(AnalysisJob).where(AnalysisJob.canonical_target_id.in_(app_ids))
        )
        session.execute(
            delete(GameProfile).where(GameProfile.steam_app_id.in_(app_ids))
        )
        session.execute(
            delete(CreatorProfile).where(CreatorProfile.youtube_channel_id.in_(app_ids))
        )


def test_created_job_and_idempotency_commit_before_dispatch(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-after-commit-{uuid4().hex}"
    dispatcher = ObservingDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            response = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
        assert response.status_code == 201
        assert dispatcher.calls == [UUID(response.json()["id"])]
        assert dispatcher.observed_committed == [(True, True)]
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


def test_queued_idempotency_replay_republishes_to_heal_commit_publish_gap(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-replay-{uuid4().hex}"
    dispatcher = ObservingDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            first = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
            second = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
        assert second.json() == first.json()
        assert dispatcher.calls == [UUID(first.json()["id"])] * 2
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


def test_stale_queued_replay_reconciles_from_postgres_before_dispatch(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-stale-replay-{uuid4().hex}"
    dispatcher = ObservingDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            created = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
            dispatcher.calls.clear()
            with Session(database_engine) as mutate, mutate.begin():
                job = mutate.get(AnalysisJob, UUID(created.json()["id"]))
                assert job is not None
                job.status = JobStatus.FAILED
                job.error_code = "analysis_internal_error"
                job.error_message = "Analysis failed unexpectedly. Please retry."
                job.retryable = True
                job.completed_at = NOW
            replay = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
        assert replay.status_code == created.status_code
        assert replay.json()["status"] == "failed"
        assert replay.json()["error"]["code"] == "analysis_internal_error"
        assert dispatcher.calls == []
        with Session(database_engine) as verification:
            record = verification.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
            assert record is not None
            assert record.response_body == replay.json()
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


def test_replay_reconciliation_suppresses_unsafe_persisted_correlation(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-safe-replay-{uuid4().hex}"
    dispatcher = ObservingDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            created = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
            dispatcher.calls.clear()
            with Session(database_engine) as mutate, mutate.begin():
                job = mutate.get(AnalysisJob, UUID(created.json()["id"]))
                assert job is not None
                job.correlation_id = "api-key=secret-value"
            replay = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )

        assert replay.status_code == 201
        assert replay.json()["correlation_id"] is None
        assert "secret-value" not in replay.text
        assert dispatcher.calls == [UUID(created.json()["id"])]
        with Session(database_engine) as verification:
            record = verification.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
            assert record is not None
            assert record.response_body["correlation_id"] is None
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


def test_stale_queued_replay_rejects_corrupt_succeeded_result(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-corrupt-replay-{uuid4().hex}"
    dispatcher = ObservingDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            created = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
            dispatcher.calls.clear()
            with Session(database_engine) as mutate, mutate.begin():
                job = mutate.get(AnalysisJob, UUID(created.json()["id"]))
                assert job is not None
                profile = GameProfile(
                    steam_app_id=job.canonical_target_id,
                    canonical_url=job.canonical_url,
                    sort_name="Corrupt replay",
                )
                mutate.add(profile)
                mutate.flush()
                job.status = JobStatus.SUCCEEDED
                job.stage = AnalysisStage.FINALIZING
                job.completed_units = 5
                job.total_units = 5
                job.profile_id = profile.id
                job.result_payload = {"profile_id": str(uuid4())}
                job.started_at = NOW
                job.completed_at = NOW
            replay = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
        assert replay.status_code == 500
        assert replay.json()["error"]["code"] == "analysis_job_result_invalid"
        assert dispatcher.calls == []
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


@pytest.mark.parametrize("target_type", list(TargetType))
def test_stale_replay_rejects_coordinated_malformed_success_identity(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
    target_type: TargetType,
) -> None:
    if target_type is TargetType.GAME:
        target_id = str(1_500_000_000 + uuid4().int % 100_000_000)
        target_url = f"https://store.steampowered.com/app/{target_id}"
        malformed_id = "AKIASECRETEXAMPLE123"
    else:
        target_id = f"UC{uuid4().hex}"
        target_url = f"https://www.youtube.com/channel/{target_id}"
        malformed_id = "UC-invalid/channel-secret"
    malformed_url = "https://evil.example/path?api_key=provider-secret"
    key = f"dispatch-malformed-replay-{uuid4().hex}"
    dispatcher = ObservingDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            created = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={"target_type": target_type.value, "url": target_url},
            )
            dispatcher.calls.clear()
            with Session(database_engine) as mutate, mutate.begin():
                job = mutate.get(AnalysisJob, UUID(created.json()["id"]))
                assert job is not None
                if target_type is TargetType.GAME:
                    profile = GameProfile(
                        steam_app_id=malformed_id,
                        canonical_url=malformed_url,
                        sort_name="Malformed replay game",
                    )
                else:
                    profile = CreatorProfile(
                        youtube_channel_id=malformed_id,
                        canonical_url=malformed_url,
                        sort_name="Malformed replay creator",
                    )
                mutate.add(profile)
                mutate.flush()
                job.canonical_target_id = malformed_id
                job.canonical_url = malformed_url
                job.status = JobStatus.SUCCEEDED
                job.stage = AnalysisStage.FINALIZING
                job.completed_units = 5
                job.total_units = 5
                job.profile_id = profile.id
                job.result_payload = {"profile_id": str(profile.id)}
                job.started_at = NOW
                job.completed_at = NOW
            replay = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={"target_type": target_type.value, "url": target_url},
            )

        assert replay.status_code == 500
        assert replay.json()["error"]["code"] == "analysis_job_result_invalid"
        assert malformed_id not in replay.text
        assert "provider-secret" not in replay.text
        assert dispatcher.calls == []
    finally:
        _cleanup(
            database_engine,
            app_ids={target_id, malformed_id},
            keys={key},
        )


def test_cached_succeeded_replay_revalidates_postgres_result_identity(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-cached-success-{uuid4().hex}"
    dispatcher = ObservingDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            created = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
            dispatcher.calls.clear()
            with Session(database_engine) as mutate, mutate.begin():
                job = mutate.get(AnalysisJob, UUID(created.json()["id"]))
                assert job is not None
                profile = GameProfile(
                    steam_app_id=job.canonical_target_id,
                    canonical_url=job.canonical_url,
                    sort_name="Initially valid success",
                )
                mutate.add(profile)
                mutate.flush()
                job.status = JobStatus.SUCCEEDED
                job.stage = AnalysisStage.FINALIZING
                job.completed_units = 5
                job.total_units = 5
                job.profile_id = profile.id
                job.result_payload = {"profile_id": str(profile.id)}
                job.started_at = NOW
                job.completed_at = NOW
            valid_replay = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
            assert valid_replay.json().get("status") == "succeeded", valid_replay.json()
            with Session(database_engine) as mutate, mutate.begin():
                job = mutate.get(AnalysisJob, UUID(created.json()["id"]))
                assert job is not None
                job.result_payload = {"profile_id": str(uuid4())}
            corrupt_replay = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
        assert corrupt_replay.status_code == 500
        assert corrupt_replay.json()["error"]["code"] == "analysis_job_result_invalid"
        assert dispatcher.calls == []
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


def test_broker_failure_converges_job_and_stored_replay_to_safe_failed_resource(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-broker-failure-{uuid4().hex}"
    dispatcher = ObservingDispatcher(
        database_engine, error=RuntimeError("redis://secret@broker")
    )
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            first = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
            dispatcher.error = None
            replay = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
        assert first.status_code == 201
        assert first.json()["status"] == "failed"
        assert first.json()["error"] == {
            "code": "analysis_queue_unavailable",
            "message": "Analysis could not be queued. Please retry.",
        }
        assert first.json() == replay.json()
        assert len(dispatcher.calls) == 1
        assert "redis://" not in str(first.json())
        with Session(database_engine) as verification:
            job = verification.get(AnalysisJob, UUID(first.json()["id"]))
            record = verification.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
            assert job is not None and record is not None
            assert job.status is JobStatus.FAILED
            assert job.error_code == "analysis_queue_unavailable"
            assert job.retryable is True
            assert job.completed_at == NOW
            assert record.response_body == first.json()
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


def test_dispatch_failure_reconciliation_suppresses_unsafe_correlation(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-safe-failure-{uuid4().hex}"
    dispatcher = UnsafeCorrelationThenFailDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            response = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )

        assert response.status_code == 201
        assert response.json()["status"] == "failed"
        assert response.json()["correlation_id"] is None
        assert "secret-value" not in response.text
        with Session(database_engine) as verification:
            record = verification.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
            assert record is not None
            assert record.response_body["correlation_id"] is None
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


def test_broker_failure_preserves_concurrent_corrupt_success_error(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-corrupt-race-{uuid4().hex}"
    dispatcher = CorruptSuccessThenFailDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            response = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "analysis_job_result_invalid"
        assert "redis://" not in str(response.json())
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


def test_broker_failure_rejects_concurrent_coordinated_malformed_success(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    malformed_id = "AKIASECRETEXAMPLE123"
    key = f"dispatch-malformed-race-{uuid4().hex}"
    dispatcher = MalformedSuccessThenFailDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            response = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "analysis_job_result_invalid"
        assert malformed_id not in response.text
        assert "provider-secret" not in response.text
    finally:
        _cleanup(database_engine, app_ids={app_id, malformed_id}, keys={key})


def test_failing_replay_publisher_never_overwrites_successfully_claimed_job(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    key = f"dispatch-running-race-{uuid4().hex}"
    dispatcher = ClaimThenFailDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            response = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": key},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{app_id}",
                },
            )

        assert response.status_code == 201
        assert response.json()["status"] == "running"
        assert response.json()["error"] is None
        with Session(database_engine) as verification:
            job = verification.get(AnalysisJob, UUID(response.json()["id"]))
            assert job is not None
            assert job.status is JobStatus.RUNNING
            assert job.error_code is None
    finally:
        _cleanup(database_engine, app_ids={app_id}, keys={key})


def test_existing_profile_and_running_active_job_are_not_dispatched(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    existing_id = str(1_500_000_000 + uuid4().int % 100_000_000)
    running_id = str(1_600_000_000 + uuid4().int % 100_000_000)
    keys = {f"no-dispatch-{uuid4().hex}", f"no-dispatch-{uuid4().hex}"}
    with Session(database_engine) as seed, seed.begin():
        seed.add(
            GameProfile(
                steam_app_id=existing_id,
                canonical_url=f"https://store.steampowered.com/app/{existing_id}",
                sort_name="Existing",
            )
        )
        running = AnalysisJob(
            target_type=TargetType.GAME,
            canonical_target_id=running_id,
            canonical_url=f"https://store.steampowered.com/app/{running_id}",
            mode=JobMode.CREATE,
            status=JobStatus.RUNNING,
            stage=AnalysisStage.FETCHING_DATA,
            completed_units=0,
            total_units=5,
            started_at=NOW,
        )
        seed.add(running)
    dispatcher = ObservingDispatcher(database_engine)
    try:
        with _client(database_engine, workspace_access_key, dispatcher) as client:
            existing = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": next(iter(keys))},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{existing_id}",
                },
            )
            running_response = client.post(
                "/api/v1/jobs/analysis",
                headers={"Idempotency-Key": list(keys)[1]},
                json={
                    "target_type": "game",
                    "url": f"https://store.steampowered.com/app/{running_id}",
                },
            )
        assert existing.json()["outcome"] == "existing_profile"
        assert running_response.json()["status"] == "running"
        assert dispatcher.calls == []
    finally:
        _cleanup(database_engine, app_ids={existing_id, running_id}, keys=keys)


def test_real_redis_broker_publishes_only_the_canonical_job_id() -> None:
    broker_url = os.environ.get("REAL_REDIS_URL")
    if not broker_url:
        pytest.skip("REAL_REDIS_URL is required for the real broker slice")
    queue_name = f"task11-{uuid4().hex}"
    app = create_celery_app(broker_url=broker_url)
    dispatcher = CeleryJobDispatcher(app=app, queue=queue_name)
    job_id = uuid4()

    with app.connection_for_write() as connection:
        connection.ensure_connection(max_retries=1)
        queue = connection.SimpleQueue(queue_name)
        try:
            queue.clear()
            dispatcher.dispatch(job_id)
            message = queue.get(block=True, timeout=5)
            try:
                assert message.payload[0] == [str(job_id)]
                assert message.payload[1] == {}
                assert str(job_id) in message.body.decode()
            finally:
                message.ack()
        finally:
            queue.clear()
            queue.close()
