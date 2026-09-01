from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.analysis.targets import (
    CanonicalTarget,
    ChannelResolutionUnavailable,
)
from app.core.crypto import SecretCipher
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
) -> Iterator[TestClient]:
    @contextmanager
    def job_session_factory() -> Iterator[Session]:
        yield session

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        channel_resolver=channel_resolver,
        job_session_factory=job_session_factory,
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {workspace_access_key}"
        yield client


@contextmanager
def _independent_client(
    database_engine: Engine, workspace_access_key: str
) -> Iterator[TestClient]:
    @contextmanager
    def job_session_factory() -> Iterator[Session]:
        with Session(database_engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        job_session_factory=job_session_factory,
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {workspace_access_key}"
        yield client


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
    with _independent_client(database_engine, workspace_access_key) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda _: client.post(
                        "/api/v1/jobs/analysis",
                        headers={"Idempotency-Key": key},
                        json=payload,
                    ),
                    range(2),
                )
            )
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
    with _independent_client(database_engine, workspace_access_key) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda key: client.post(
                        "/api/v1/jobs/analysis",
                        headers={"Idempotency-Key": key},
                        json=payload,
                    ),
                    keys,
                )
            )
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

    with _independent_client(database_engine, workspace_access_key) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda key: client.post(
                        f"/api/v1/jobs/analysis/{source_id}/retry",
                        headers={"Idempotency-Key": key},
                        json={},
                    ),
                    keys,
                )
            )

    expected_statuses = {201} if same_key else {200, 201}
    assert {response.status_code for response in responses} == expected_statuses
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
