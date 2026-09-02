import base64
from collections.abc import Callable
from contextlib import contextmanager
import json
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, update
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.core.errors import APIError
from app.core.analysis_job_contract import PUBLIC_JOB_FAILURES
from app.core.security import hash_workspace_key
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile, GameProfile
from app.main import create_app
from app.api.routes.jobs import project_analysis_job
from app.schemas.jobs import AnalysisJobError, AnalysisJobResponse


NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
JOB_CREATED_AT = datetime(2000, 1, 1, tzinfo=UTC)


def _job(
    session: Session,
    *,
    status: JobStatus = JobStatus.QUEUED,
    updated_at: datetime | None = None,
    profile_id: UUID | None = None,
) -> AnalysisJob:
    profile = session.get(GameProfile, profile_id) if profile_id is not None else None
    app_id = (
        profile.steam_app_id
        if profile is not None
        else str(2_000_000 + uuid4().int % 1_000_000)
    )
    canonical_url = (
        profile.canonical_url
        if profile is not None
        else f"https://store.steampowered.com/app/{app_id}"
    )
    job = AnalysisJob(
        target_type=TargetType.GAME,
        canonical_target_id=app_id,
        canonical_url=canonical_url,
        mode=JobMode.CREATE,
        status=status,
        stage=(
            None
            if status is JobStatus.QUEUED
            else (
                AnalysisStage.FINALIZING
                if status is JobStatus.SUCCEEDED
                else AnalysisStage.FETCHING_DATA
            )
        ),
        completed_units=5 if status is JobStatus.SUCCEEDED else 0,
        total_units=0 if status is JobStatus.QUEUED else 5,
        retryable=status is JobStatus.FAILED,
        correlation_id=str(uuid4()),
        profile_id=profile_id,
        created_at=JOB_CREATED_AT,
        started_at=None if status is JobStatus.QUEUED else NOW,
        completed_at=NOW if status in {JobStatus.SUCCEEDED, JobStatus.FAILED} else None,
    )
    if status is JobStatus.FAILED:
        job.error_code = "analysis_queue_unavailable"
        job.error_message = "Analysis could not be queued. Please retry."
    if status is JobStatus.SUCCEEDED and profile_id is not None:
        job.result_payload = {"profile_id": str(profile_id)}
    session.add(job)
    session.flush()
    if updated_at is not None:
        session.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == job.id)
            .values(updated_at=updated_at)
        )
        session.flush()
        session.refresh(job)
    return job


def _decode(cursor: str) -> dict:
    return json.loads(
        base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    )


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _encode_raw(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class AllowAllRateLimiter:
    def allow(self, workspace_key_hash: str, client_address: str) -> bool:
        return True


@contextmanager
def _engine_client(engine: Engine, workspace_access_key: str):
    @contextmanager
    def session_factory():
        with Session(engine, expire_on_commit=False) as database_session:
            try:
                yield database_session
            except Exception:
                database_session.rollback()
                raise

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        job_session_factory=session_factory,
    )
    with TestClient(
        app,
        headers={"Authorization": f"Bearer {workspace_access_key}"},
    ) as client:
        yield client


def test_changed_jobs_endpoint_returns_authenticated_empty_page_with_cursor(
    auth_client: TestClient,
) -> None:
    response = auth_client.get("/api/v1/jobs")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "cursor": response.json()["cursor"],
        "has_more": False,
        "affected_profile_ids": [],
    }
    assert response.json()["cursor"]


def test_initial_empty_cursor_cannot_skip_a_job_committed_between_poll_statements(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_700_000_000 + uuid4().int % 100_000_000)
    completed = Event()
    responses = []
    try:
        with _engine_client(database_engine, workspace_access_key) as client:
            with Session(database_engine, expire_on_commit=False) as delayed:
                transaction = delayed.begin()
                inserted = AnalysisJob(
                    target_type=TargetType.GAME,
                    canonical_target_id=app_id,
                    canonical_url=f"https://store.steampowered.com/app/{app_id}",
                    mode=JobMode.CREATE,
                    status=JobStatus.QUEUED,
                )
                delayed.add(inserted)
                delayed.flush()

                def poll() -> None:
                    try:
                        responses.append(client.get("/api/v1/jobs"))
                    finally:
                        completed.set()

                poll_thread = Thread(target=poll)
                poll_thread.start()
                completed_before_commit = completed.wait(0.5)
                transaction.commit()
                assert completed.wait(5)
                poll_thread.join()

            response = responses[0]
            assert completed_before_commit is False
            assert response.status_code == 200
            assert [item["id"] for item in response.json()["items"]] == [
                str(inserted.id)
            ]
    finally:
        with Session(database_engine) as cleanup, cleanup.begin():
            cleanup.query(AnalysisJob).filter_by(canonical_target_id=app_id).delete()


def test_subsequent_poll_waits_for_invisible_update_before_advancing(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_800_000_000 + uuid4().int % 100_000_000)
    completed = Event()
    responses = []
    try:
        with Session(database_engine) as seed, seed.begin():
            job = AnalysisJob(
                target_type=TargetType.GAME,
                canonical_target_id=app_id,
                canonical_url=f"https://store.steampowered.com/app/{app_id}",
                mode=JobMode.CREATE,
                status=JobStatus.QUEUED,
            )
            seed.add(job)
            seed.flush()
            job_id = job.id

        with _engine_client(database_engine, workspace_access_key) as client:
            baseline = client.get("/api/v1/jobs").json()["cursor"]
            with Session(database_engine) as delayed:
                transaction = delayed.begin()
                job = delayed.get(AnalysisJob, job_id)
                assert job is not None
                job.status = JobStatus.RUNNING
                job.stage = AnalysisStage.FETCHING_DATA
                job.total_units = 5
                job.started_at = datetime.now(UTC)
                delayed.flush()

                def poll() -> None:
                    try:
                        responses.append(
                            client.get(
                                "/api/v1/jobs",
                                params={"changed_after": baseline},
                            )
                        )
                    finally:
                        completed.set()

                poll_thread = Thread(target=poll)
                poll_thread.start()
                completed_before_commit = completed.wait(0.5)
                transaction.commit()
                assert completed.wait(5)
                poll_thread.join()

            response = responses[0]
            assert completed_before_commit is False
            assert response.status_code == 200
            assert [
                (item["id"], item["status"]) for item in response.json()["items"]
            ] == [(str(job_id), "running")]
    finally:
        with Session(database_engine) as cleanup, cleanup.begin():
            cleanup.query(AnalysisJob).filter_by(canonical_target_id=app_id).delete()


def test_change_arriving_after_cursor_advances_past_regressed_database_clock(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> None:
    app_id = str(1_900_000_000 + uuid4().int % 100_000_000)
    future_timestamp = datetime.now(UTC) + timedelta(days=1)
    try:
        with Session(database_engine) as seed, seed.begin():
            job = AnalysisJob(
                target_type=TargetType.GAME,
                canonical_target_id=app_id,
                canonical_url=f"https://store.steampowered.com/app/{app_id}",
                mode=JobMode.CREATE,
                status=JobStatus.QUEUED,
            )
            seed.add(job)
            seed.flush()
            job_id = job.id
        with Session(database_engine) as force_future, force_future.begin():
            force_future.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id == job_id)
                .values(updated_at=future_timestamp)
            )

        with _engine_client(database_engine, workspace_access_key) as client:
            baseline = client.get("/api/v1/jobs").json()["cursor"]
            with Session(database_engine) as mutate, mutate.begin():
                job = mutate.get(AnalysisJob, job_id)
                assert job is not None
                job.status = JobStatus.RUNNING
                job.stage = AnalysisStage.FETCHING_DATA
                job.total_units = 5
                job.started_at = datetime.now(UTC)
            changed = client.get("/api/v1/jobs", params={"changed_after": baseline})

        assert changed.status_code == 200
        assert [(item["id"], item["status"]) for item in changed.json()["items"]] == [
            (str(job_id), "running")
        ]
    finally:
        with Session(database_engine) as cleanup, cleanup.begin():
            cleanup.query(AnalysisJob).filter_by(canonical_target_id=app_id).delete()


def test_job_read_uses_one_safe_projection_and_never_reflects_internal_fields(
    auth_client: TestClient, session: Session
) -> None:
    job = _job(session, status=JobStatus.FAILED)

    response = auth_client.get(f"/api/v1/jobs/{job.id}")
    body = response.json()
    assert response.status_code == 200
    assert body["id"] == str(job.id)
    assert body["correlation_id"] == job.correlation_id
    assert body["error"] == {
        "code": "analysis_queue_unavailable",
        "message": "Analysis could not be queued. Please retry.",
    }
    serialized = json.dumps(body)
    assert "redis://" not in serialized
    assert "provider_text" not in serialized
    assert "result_payload" not in serialized
    assert "error_message" not in serialized


def test_unsafe_persisted_correlation_is_suppressed_by_read_and_changed_list(
    auth_client: TestClient, session: Session
) -> None:
    job = _job(session, status=JobStatus.RUNNING)
    job.correlation_id = "test-workspace-access-key"
    session.flush()

    read = auth_client.get(f"/api/v1/jobs/{job.id}")
    changed = auth_client.get("/api/v1/jobs")

    assert read.status_code == 200
    assert read.json()["correlation_id"] is None
    changed_job = next(
        item for item in changed.json()["items"] if item["id"] == str(job.id)
    )
    assert changed_job["correlation_id"] is None
    assert "test-workspace-access-key" not in read.text
    assert "test-workspace-access-key" not in changed.text


@pytest.mark.parametrize(
    ("target_type", "malformed_id", "malformed_url"),
    [
        (
            TargetType.GAME,
            "AKIASECRETEXAMPLE123",
            "https://evil.example/path?api_key=provider-secret",
        ),
        (
            TargetType.CREATOR,
            "UC-invalid/channel-secret",
            "https://evil.example/path?api_key=provider-secret",
        ),
    ],
)
def test_coordinated_malformed_success_identity_is_rejected_by_public_projection(
    session: Session,
    target_type: TargetType,
    malformed_id: str,
    malformed_url: str,
) -> None:
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
    session.add(profile)
    session.flush()
    job = AnalysisJob(
        id=uuid4(),
        target_type=target_type,
        canonical_target_id=malformed_id,
        canonical_url=malformed_url,
        mode=JobMode.CREATE,
        status=JobStatus.SUCCEEDED,
        stage=AnalysisStage.FINALIZING,
        completed_units=5,
        total_units=5,
        retryable=False,
        profile_id=profile.id,
        result_payload={"profile_id": str(profile.id)},
        started_at=NOW,
        completed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(job)
    with pytest.raises(APIError) as error:
        project_analysis_job(session, job, succeeded_profile=profile)
    assert error.value.code == "analysis_job_result_invalid"
    assert malformed_id not in error.value.message
    assert "provider-secret" not in error.value.message


@pytest.mark.parametrize(
    ("status", "completed_units", "total_units", "retryable"),
    [
        (JobStatus.RUNNING, -1, 5, False),
        (JobStatus.RUNNING, 6, 5, False),
        (JobStatus.RUNNING, 0, 5, True),
    ],
)
def test_central_projection_rejects_invalid_persisted_job_state(
    session: Session,
    status: JobStatus,
    completed_units: int,
    total_units: int,
    retryable: bool,
) -> None:
    job = _job(session, status=status)
    job.completed_units = completed_units
    job.total_units = total_units
    job.retryable = retryable

    with pytest.raises(APIError) as error:
        project_analysis_job(session, job)

    assert error.value.code == "analysis_job_state_invalid"
    assert error.value.status_code == 500


@pytest.mark.parametrize("case", ["queued", "running", "succeeded", "failed"])
def test_central_projection_rejects_cross_status_state(
    session: Session, case: str
) -> None:
    if case == "succeeded":
        app_id = str(1_900_000_000 + uuid4().int % 100_000_000)
        profile = GameProfile(
            steam_app_id=app_id,
            canonical_url=f"https://store.steampowered.com/app/{app_id}",
            sort_name="Structurally corrupt success",
        )
        session.add(profile)
        session.flush()
        job = _job(session, status=JobStatus.SUCCEEDED, profile_id=profile.id)
        job.stage = None
        job.completed_units = 0
        job.completed_at = None
    else:
        status = {
            "queued": JobStatus.QUEUED,
            "running": JobStatus.RUNNING,
            "failed": JobStatus.FAILED,
        }[case]
        job = _job(session, status=status)
        if case == "queued":
            job.stage = AnalysisStage.FINALIZING
            job.completed_units = 5
            job.total_units = 5
            job.started_at = NOW
            job.completed_at = NOW
        elif case == "running":
            job.error_code = "steam_unavailable"
            job.error_message = "Analysis is temporarily unavailable. Please retry."
            job.completed_at = NOW
        else:
            job.error_code = None
            job.error_message = None
            job.completed_at = None
            job.profile_id = uuid4()

    with pytest.raises(APIError) as error:
        project_analysis_job(session, job)

    assert error.value.code == "analysis_job_state_invalid"


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"completed_units": -1}, "completed_units"),
        ({"total_units": -1}, "total_units"),
        ({"completed_units": 6, "total_units": 5}, "completed_units"),
        ({"status": "running", "retryable": True}, "retryable"),
        ({"correlation_id": "api-key=secret-value"}, "correlation_id"),
    ],
)
def test_public_job_schema_rejects_unsafe_state(
    session: Session, updates: dict[str, object], match: str
) -> None:
    job = _job(session, status=JobStatus.RUNNING)
    payload = project_analysis_job(session, job).model_dump(mode="json")
    payload.update(updates)

    with pytest.raises(ValidationError, match=match):
        AnalysisJobResponse.model_validate(payload)


def _valid_queued_response_payload() -> dict[str, object]:
    return {
        "outcome": "job",
        "id": str(uuid4()),
        "target_type": "game",
        "canonical_target_id": "123",
        "canonical_url": "https://store.steampowered.com/app/123",
        "mode": "create",
        "status": "queued",
        "stage": None,
        "completed_units": 0,
        "total_units": 0,
        "retryable": False,
        "error": None,
        "correlation_id": None,
        "profile_id": None,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "started_at": None,
        "completed_at": None,
    }


@pytest.mark.parametrize(
    "updates",
    [
        {
            "stage": "finalizing",
            "completed_units": 5,
            "total_units": 5,
            "profile_id": str(uuid4()),
            "started_at": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
        },
        {
            "status": "running",
            "stage": "fetching_data",
            "total_units": 5,
            "started_at": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
            "error": {
                "code": "steam_unavailable",
                "message": "Analysis is temporarily unavailable. Please retry.",
            },
        },
        {
            "status": "succeeded",
            "total_units": 5,
        },
        {
            "status": "failed",
            "profile_id": str(uuid4()),
        },
        {
            "status": "failed",
            "stage": "fetching_data",
            "total_units": 5,
            "error": {
                "code": "steam_unavailable",
                "message": "Analysis is temporarily unavailable. Please retry.",
            },
            "retryable": True,
            "started_at": (NOW + timedelta(hours=1)).isoformat(),
            "completed_at": (NOW - timedelta(hours=1)).isoformat(),
        },
    ],
)
def test_public_job_schema_rejects_cross_status_state(updates) -> None:
    payload = _valid_queued_response_payload()
    payload.update(updates)

    with pytest.raises(ValidationError):
        AnalysisJobResponse.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "api_key_secret", "message": "Bearer-secret-value"},
        {
            "code": "analysis_internal_error",
            "message": "Analysis is temporarily unavailable. Please retry.",
        },
    ],
)
def test_public_job_error_schema_accepts_only_fixed_safe_mappings(payload) -> None:
    with pytest.raises(ValidationError):
        AnalysisJobError.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "code": "steam_game_not_found",
            "message": "Analysis is temporarily unavailable. Please retry.",
        },
        {
            "code": "steam_unavailable",
            "message": "Analysis could not be completed for this target.",
        },
    ],
)
def test_public_job_error_schema_rejects_cross_code_message_mappings(payload) -> None:
    with pytest.raises(ValidationError):
        AnalysisJobError.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "code": "analysis_internal_error",
            "message": "Analysis failed unexpectedly. Please retry.",
        },
        {
            "code": "analysis_queue_unavailable",
            "message": "Analysis could not be queued. Please retry.",
        },
        {
            "code": "steam_unavailable",
            "message": "Analysis is temporarily unavailable. Please retry.",
        },
        {
            "code": "steam_game_not_found",
            "message": "Analysis could not be completed for this target.",
        },
    ],
)
def test_public_job_error_schema_accepts_existing_safe_mappings(payload) -> None:
    assert AnalysisJobError.model_validate(payload).model_dump() == payload


def test_every_public_job_error_code_has_one_schema_message() -> None:
    alternate_messages = {failure.message for failure in PUBLIC_JOB_FAILURES.values()}
    for code, failure in PUBLIC_JOB_FAILURES.items():
        assert AnalysisJobError(
            code=code,
            message=failure.message,
        ).model_dump() == {"code": code, "message": failure.message}
        wrong_message = next(
            message for message in alternate_messages if message != failure.message
        )
        with pytest.raises(ValidationError):
            AnalysisJobError(code=code, message=wrong_message)


def test_corrupt_succeeded_job_is_rejected_by_central_public_projection(
    session: Session,
) -> None:
    profile = GameProfile(
        steam_app_id=str(3_100_000 + uuid4().int % 1_000_000),
        canonical_url="https://store.steampowered.com/app/3100000",
        sort_name="Corrupt success",
    )
    session.add(profile)
    session.flush()
    job = _job(session, status=JobStatus.SUCCEEDED, profile_id=profile.id)
    job.result_payload = {"profile_id": str(uuid4())}
    with pytest.raises(APIError) as error:
        project_analysis_job(session, job, succeeded_profile=profile)
    assert error.value.code == "analysis_job_result_invalid"
    assert error.value.message == "The Analysis Job result is invalid."
    assert error.value.retryable is False
    assert str(profile.id) not in error.value.message


def test_unknown_stored_error_degrades_to_generic_safe_failure(
    session: Session,
) -> None:
    job = _job(session, status=JobStatus.FAILED)
    job.error_code = "unknown_private_provider_error"
    job.error_message = "api-key=never-return"
    body = project_analysis_job(session, job).model_dump(mode="json")
    assert body["error"] == {
        "code": "analysis_internal_error",
        "message": "Analysis failed unexpectedly. Please retry.",
    }
    assert "api-key" not in str(body)


def test_job_read_is_authenticated_and_missing_job_is_safe(
    client: TestClient, auth_client: TestClient
) -> None:
    auth_client.headers.pop("Authorization")
    unauthenticated = client.get(f"/api/v1/jobs/{uuid4()}")
    client.headers["Authorization"] = "Bearer test-workspace-access-key"
    missing = client.get(f"/api/v1/jobs/{uuid4()}")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "workspace_key_invalid"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "analysis_job_not_found"


def test_changed_jobs_cursor_is_monotonic_and_empty_poll_preserves_it(
    auth_client: TestClient, session: Session
) -> None:
    first_job = _job(session, updated_at=NOW)
    first = auth_client.get("/api/v1/jobs").json()
    second_job = _job(session, updated_at=NOW + timedelta(seconds=1))
    second = auth_client.get(
        "/api/v1/jobs", params={"changed_after": first["cursor"]}
    ).json()
    empty = auth_client.get(
        "/api/v1/jobs", params={"changed_after": second["cursor"]}
    ).json()
    assert {item["id"] for item in first["items"]} == {str(first_job.id)}
    assert {item["id"] for item in second["items"]} == {str(second_job.id)}
    assert empty["items"] == []
    assert empty["cursor"] == second["cursor"]


def test_equal_timestamp_ties_and_pages_drain_without_duplicates(
    auth_client: TestClient, session: Session
) -> None:
    jobs = [_job(session, updated_at=NOW) for _ in range(4)]
    expected = [str(job.id) for job in sorted(jobs, key=lambda item: item.id)]
    cursor = None
    seen: list[str] = []
    while True:
        params = {"limit": 1}
        if cursor:
            params["changed_after"] = cursor
        body = auth_client.get("/api/v1/jobs", params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["cursor"]
        if not body["has_more"]:
            break
    assert seen == expected


def test_status_cursor_is_scope_bound_and_later_transition_appears(
    auth_client: TestClient, session: Session
) -> None:
    job = _job(session, status=JobStatus.RUNNING, updated_at=NOW)
    running_page = auth_client.get("/api/v1/jobs", params={"status": "running"}).json()
    wrong_scope = auth_client.get(
        "/api/v1/jobs",
        params={"status": "succeeded", "changed_after": running_page["cursor"]},
    )
    assert wrong_scope.status_code == 400
    assert wrong_scope.json()["error"]["code"] == "analysis_job_cursor_invalid"

    profile = GameProfile(
        steam_app_id=job.canonical_target_id,
        canonical_url=job.canonical_url,
        sort_name="Transitioned",
    )
    session.add(profile)
    session.flush()
    session.execute(
        update(AnalysisJob)
        .where(AnalysisJob.id == job.id)
        .values(
            status=JobStatus.SUCCEEDED,
            stage=AnalysisStage.FINALIZING,
            completed_units=5,
            total_units=5,
            profile_id=profile.id,
            result_payload={"profile_id": str(profile.id)},
            completed_at=NOW + timedelta(seconds=1),
            updated_at=NOW + timedelta(seconds=2),
        )
    )
    session.flush()
    succeeded = auth_client.get("/api/v1/jobs", params={"status": "succeeded"}).json()
    assert [item["id"] for item in succeeded["items"]] == [str(job.id)]


def test_succeeded_items_return_stable_deduplicated_affected_profile_ids(
    auth_client: TestClient, session: Session
) -> None:
    app_id = str(3_000_000 + uuid4().int % 1_000_000)
    profile = GameProfile(
        steam_app_id=app_id,
        canonical_url=f"https://store.steampowered.com/app/{app_id}",
        sort_name="Affected",
    )
    session.add(profile)
    session.flush()
    first = _job(session, status=JobStatus.SUCCEEDED, profile_id=profile.id)
    second = _job(session, status=JobStatus.SUCCEEDED, profile_id=profile.id)
    body = auth_client.get("/api/v1/jobs").json()
    assert {item["id"] for item in body["items"]} == {
        str(first.id),
        str(second.id),
    }
    assert body["affected_profile_ids"] == [str(profile.id)]


def test_succeeded_job_polling_bulk_loads_profiles_under_one_fenced_snapshot(
    auth_client: TestClient, session: Session
) -> None:
    for offset in range(25):
        app_id = str(1_800_000_000 + offset)
        profile = GameProfile(
            steam_app_id=app_id,
            canonical_url=f"https://store.steampowered.com/app/{app_id}",
            sort_name=f"Bulk profile {offset}",
        )
        session.add(profile)
        session.flush()
        _job(session, status=JobStatus.SUCCEEDED, profile_id=profile.id)
    session.expunge_all()

    statements: list[str] = []

    def record_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(" ".join(statement.casefold().split()))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", record_statement)
    try:
        response = auth_client.get("/api/v1/jobs", params={"limit": 100})
    finally:
        event.remove(connection, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 25
    profile_selects = [
        statement
        for statement in statements
        if statement.startswith("select") and " from game_profiles" in statement
    ]
    assert len(profile_selects) == 1
    assert all(
        column not in profile_selects[0]
        for column in (
            "current_facts",
            "analysis",
            "brief",
            "source_status",
            "model_metadata",
            "prompt_metadata",
        )
    )
    advisory_index = next(
        index
        for index, statement in enumerate(statements)
        if "pg_advisory_xact_lock" in statement
    )
    jobs_index = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith("select") and " from analysis_jobs" in statement
    )
    profiles_index = statements.index(profile_selects[0])
    assert advisory_index < jobs_index < profiles_index
    assert len(statements) <= 4


@pytest.mark.parametrize("cursor", ["", "x" * 2049, "not-base64", _encode([1, 2])])
def test_malformed_cursor_is_rejected_safely(
    auth_client: TestClient, cursor: str
) -> None:
    response = auth_client.get("/api/v1/jobs", params={"changed_after": cursor})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "analysis_job_cursor_invalid"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: {**value, "v": 2},
        lambda value: {**value, "unexpected": True},
        lambda value: {
            **value,
            "key": ["2026-09-02T09:00:00", value["key"][1]],
        },
        lambda value: {
            **value,
            "key": [value["key"][0], str(uuid4()).upper()],
        },
    ],
)
def test_tampered_future_shape_naive_time_and_noncanonical_uuid_are_rejected(
    auth_client: TestClient, mutate
) -> None:
    cursor = auth_client.get("/api/v1/jobs").json()["cursor"]
    tampered = _encode(mutate(_decode(cursor)))
    response = auth_client.get("/api/v1/jobs", params={"changed_after": tampered})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "analysis_job_cursor_invalid"


@pytest.mark.parametrize(
    "reencode",
    [
        lambda value, canonical: json.dumps(value, indent=2).encode(),
        lambda value, canonical: json.dumps(
            {
                "signature": value["signature"],
                "scope": value["scope"],
                "key": value["key"],
                "v": value["v"],
            },
            separators=(",", ":"),
        ).encode(),
        lambda value, canonical: canonical.replace(b'"v":1', b'"v":1,"v":1', 1),
        lambda value, canonical: canonical.replace(b'"scope"', b'"\\u0073cope"', 1),
    ],
    ids=["whitespace", "key-order", "duplicate-key", "escaped-key"],
)
def test_signed_cursor_requires_exact_canonical_json_bytes(
    auth_client: TestClient,
    reencode: Callable[[dict, bytes], bytes],
) -> None:
    cursor = auth_client.get("/api/v1/jobs").json()["cursor"]
    value = _decode(cursor)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    noncanonical = _encode_raw(reencode(value, canonical))

    response = auth_client.get("/api/v1/jobs", params={"changed_after": noncanonical})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "analysis_job_cursor_invalid"


def test_polling_validates_limit_and_status(auth_client: TestClient) -> None:
    for params in ({"limit": 0}, {"limit": 201}, {"status": "finished"}):
        response = auth_client.get("/api/v1/jobs", params=params)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "request_invalid"


def test_job_openapi_never_exposes_internal_storage_fields(client: TestClient) -> None:
    schema = client.app.openapi()
    serialized = json.dumps(
        {
            key: value
            for key, value in schema["components"]["schemas"].items()
            if key.startswith("AnalysisJob") or key.startswith("ChangedJob")
        }
    )
    for forbidden in (
        "result_payload",
        "error_message",
        "task_id",
        "broker",
        "idempotency",
    ):
        assert forbidden not in serialized.casefold()
