import base64
from contextlib import contextmanager
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.core.security import hash_workspace_key
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import GameProfile
from app.main import create_app


NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def _job(
    session: Session,
    *,
    status: JobStatus = JobStatus.QUEUED,
    updated_at: datetime | None = None,
    profile_id: UUID | None = None,
) -> AnalysisJob:
    app_id = str(2_000_000 + uuid4().int % 1_000_000)
    job = AnalysisJob(
        target_type=TargetType.GAME,
        canonical_target_id=app_id,
        canonical_url=f"https://store.steampowered.com/app/{app_id}",
        mode=JobMode.CREATE,
        status=status,
        stage=(
            AnalysisStage.FINALIZING
            if status is JobStatus.SUCCEEDED
            else AnalysisStage.FETCHING_DATA
        ),
        completed_units=5 if status is JobStatus.SUCCEEDED else 0,
        total_units=5,
        retryable=status is JobStatus.FAILED,
        correlation_id=f"job-correlation-{uuid4()}",
        profile_id=profile_id,
        started_at=NOW,
        completed_at=NOW if status in {JobStatus.SUCCEEDED, JobStatus.FAILED} else None,
    )
    if status is JobStatus.FAILED:
        job.error_code = "analysis_queue_unavailable"
        job.error_message = "unsafe raw broker redis://credential@example"
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
    inserted_id: UUID | None = None

    class AllowAllRateLimiter:
        def allow(self, workspace_key_hash: str, client_address: str) -> bool:
            return True

    class InsertingSession(Session):
        def scalars(self, statement, *args, **kwargs):
            nonlocal inserted_id
            result = super().scalars(statement, *args, **kwargs)
            entities = {
                description.get("entity")
                for description in getattr(statement, "column_descriptions", ())
            }
            if AnalysisJob in entities and inserted_id is None:
                with Session(database_engine) as seed, seed.begin():
                    inserted = AnalysisJob(
                        target_type=TargetType.GAME,
                        canonical_target_id=app_id,
                        canonical_url=(f"https://store.steampowered.com/app/{app_id}"),
                        mode=JobMode.CREATE,
                        status=JobStatus.QUEUED,
                    )
                    seed.add(inserted)
                    seed.flush()
                    inserted_id = inserted.id
            return result

    @contextmanager
    def session_factory():
        with InsertingSession(database_engine) as database_session:
            yield database_session

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        job_session_factory=session_factory,
    )
    try:
        with TestClient(
            app,
            headers={"Authorization": f"Bearer {workspace_access_key}"},
        ) as client:
            first = client.get("/api/v1/jobs").json()
            second = client.get(
                "/api/v1/jobs", params={"changed_after": first["cursor"]}
            ).json()
        assert first["items"] == []
        assert [item["id"] for item in second["items"]] == [str(inserted_id)]
    finally:
        with Session(database_engine) as cleanup, cleanup.begin():
            cleanup.query(AnalysisJob).filter_by(canonical_target_id=app_id).delete()


def test_job_read_uses_one_safe_projection_and_never_reflects_internal_fields(
    auth_client: TestClient, session: Session
) -> None:
    job = _job(session, status=JobStatus.FAILED)
    job.result_payload = {"provider_text": "do-not-return"}
    session.flush()

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


def test_unknown_stored_error_degrades_to_generic_safe_failure(
    auth_client: TestClient, session: Session
) -> None:
    job = _job(session, status=JobStatus.FAILED)
    job.error_code = "unknown_private_provider_error"
    job.error_message = "api-key=never-return"
    session.flush()
    body = auth_client.get(f"/api/v1/jobs/{job.id}").json()
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

    session.execute(
        update(AnalysisJob)
        .where(AnalysisJob.id == job.id)
        .values(status=JobStatus.SUCCEEDED, updated_at=NOW + timedelta(seconds=2))
    )
    session.flush()
    succeeded = auth_client.get("/api/v1/jobs", params={"status": "succeeded"}).json()
    assert [item["id"] for item in succeeded["items"]] == [str(job.id)]


def test_succeeded_items_return_stable_deduplicated_affected_profile_ids(
    auth_client: TestClient, session: Session
) -> None:
    profile = GameProfile(
        steam_app_id=str(3_000_000 + uuid4().int % 1_000_000),
        canonical_url="https://store.steampowered.com/app/3000000",
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
