from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import socket
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.creator_pipeline import CreatorAnalysisPipeline
from app.analysis.service import CreatorAnalysisService
from app.analysis.targets import CanonicalTarget
from app.core.crypto import SecretCipher
from app.core.database import get_session
from app.core.security import hash_workspace_key
from app.db.models.enums import JobStatus, TargetType
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorContact, CreatorProfile
from app.main import create_app
from app.schemas.ai_creator import (
    CreatorMetadataAnalysis,
    CreatorSynthesis,
)
from app.workers.analysis_tasks import AnalysisJobExecutor
from tests.integration.test_creator_analysis_commit import AI, Artifacts, YouTube
from tests.unit.analysis.test_ai_schemas import (
    creator_metadata_unavailable_payload,
    creator_synthesis_payload,
)
from tests.unit.analysis.test_creator_pipeline import FakePages, Page, _source


class AllowAllRateLimiter:
    def allow(self, workspace_digest: str, client_address: str) -> bool:
        return True


class AlphaChannelResolver:
    def __init__(self) -> None:
        self.targets: list[CanonicalTarget] = []

    def resolve_channel(self, target: CanonicalTarget) -> str:
        self.targets.append(target)
        return "UCcreator123"


class AfterCommitDispatcher:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory
        self.calls: list[UUID] = []

    def dispatch(self, job_id: UUID) -> None:
        with self.factory() as verification_session:
            persisted = verification_session.get(AnalysisJob, job_id)
            assert persisted is not None
            assert persisted.status is JobStatus.QUEUED
        self.calls.append(job_id)


class AlphaYouTube(YouTube):
    def fetch_creator(self, channel_id: str, video_limit: int = 50):
        assert channel_id == "UCcreator123"
        assert video_limit == 50
        return _source().model_copy(update={"title": "Alpha Strategy"})


@pytest.fixture
def vertical_factory(
    migrated_database: None, database_engine: Engine
) -> Iterator[sessionmaker[Session]]:
    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    with factory.begin() as database_session:
        database_session.execute(delete(IdempotencyRecord))
        database_session.execute(delete(AnalysisJob))
        database_session.execute(delete(CreatorContact))
        database_session.execute(delete(CreatorProfile))
    yield factory
    with factory.begin() as database_session:
        database_session.execute(delete(IdempotencyRecord))
        database_session.execute(delete(AnalysisJob))
        database_session.execute(delete(CreatorContact))
        database_session.execute(delete(CreatorProfile))


def test_creator_analyze_job_reaches_searchable_library_once_without_network(
    vertical_factory: sessionmaker[Session],
    workspace_access_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blocked_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("vertical slice attempted a live network call")

    class GuardedSocket(socket.socket):
        def connect(self, *args: object, **kwargs: object) -> None:
            blocked_network()

        def connect_ex(self, *args: object, **kwargs: object) -> None:
            blocked_network()

    monkeypatch.setattr(socket, "socket", GuardedSocket)
    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.setattr(socket, "getaddrinfo", blocked_network)
    monkeypatch.setattr(socket, "gethostbyname", blocked_network)

    resolver = AlphaChannelResolver()
    dispatcher = AfterCommitDispatcher(vertical_factory)

    @contextmanager
    def job_session_factory() -> Iterator[Session]:
        with vertical_factory() as database_session:
            try:
                yield database_session
            except Exception:
                database_session.rollback()
                raise

    test_app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        channel_resolver=resolver,
        job_session_factory=job_session_factory,
        job_dispatcher=dispatcher,
    )

    def api_session() -> Iterator[Session]:
        with vertical_factory() as database_session:
            yield database_session

    test_app.dependency_overrides[get_session] = api_session
    metadata = CreatorMetadataAnalysis.model_validate(
        creator_metadata_unavailable_payload()
    )
    synthesis = CreatorSynthesis.model_validate(creator_synthesis_payload())
    youtube = AlphaYouTube()
    artifacts = Artifacts()
    pages = FakePages(
        {
            "https://creator.example/about": Page(
                "https://creator.example/about",
                "partnerships@example.org https://social.example/creator",
            )
        }
    )
    deepseek = AI(structured=[metadata, synthesis], vision_failure=None)
    pipeline = CreatorAnalysisPipeline(
        service=CreatorAnalysisService(
            session_factory=job_session_factory,
            clock=lambda: datetime.now(UTC),
        ),
        youtube=youtube,
        artifacts=artifacts,
        public_pages=pages,
        deepseek=deepseek,
    )

    @contextmanager
    def pipeline_factory(target_type: TargetType):
        assert target_type is TargetType.CREATOR
        yield pipeline

    executor = AnalysisJobExecutor(
        session_factory=job_session_factory,
        pipeline_factory=pipeline_factory,
        clock=lambda: datetime.now(UTC),
    )
    headers = {
        "Authorization": f"Bearer {workspace_access_key}",
        "Idempotency-Key": "creator-e2e-alpha",
    }
    payload = {
        "target_type": "creator",
        "url": "https://www.youtube.com/@Alpha",
    }

    try:
        with TestClient(test_app) as client:
            created = client.post(
                "/api/v1/jobs/analysis", headers=headers, json=payload
            )
            assert created.status_code == 201
            created_job = created.json()
            job_id = UUID(created_job["id"])
            assert created_job["outcome"] == "job"
            assert created_job["status"] == "queued"
            assert created_job["target_type"] == "creator"
            assert created_job["canonical_target_id"] == "UCcreator123"
            assert created_job["canonical_url"] == (
                "https://www.youtube.com/channel/UCcreator123"
            )
            assert dispatcher.calls == [job_id]

            executor.execute(job_id)

            polled = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
            assert polled.status_code == 200
            assert polled.json()["status"] == "succeeded"
            profile_id = UUID(polled.json()["profile_id"])

            changed = client.get("/api/v1/jobs", headers=headers)
            assert changed.status_code == 200
            assert changed.json()["items"][0]["id"] == str(job_id)
            assert changed.json()["items"][0]["profile_id"] == str(profile_id)
            assert changed.json()["affected_profile_ids"] == [str(profile_id)]

            library = client.get(
                "/api/v1/profiles/creators",
                headers=headers,
                params={"query": "Alpha"},
            )
            assert library.status_code == 200
            assert len(library.json()["items"]) == 1
            card = library.json()["items"][0]
            assert card["id"] == str(profile_id)
            assert card["name"] == "Alpha Strategy"
            assert card["current_facts"]["title"] == "Alpha Strategy"
            assert card["brief"]["positioning"]["value"] == (
                "A compact creator summary."
            )

            detail = client.get(
                f"/api/v1/profiles/creators/{profile_id}", headers=headers
            )
            assert detail.status_code == 200
            assert detail.json()["analysis"]["content_summary"]["value"] == (
                "A creator metadata statement."
            )
            serialized_detail = json.dumps(detail.json(), sort_keys=True).casefold()
            for forbidden in (
                "raw_channel",
                "raw_playlist_pages",
                "raw_video_responses",
                "result_payload",
                "hidden_total_score",
                "numeric_score",
                "backend_rank",
            ):
                assert forbidden not in serialized_detail

            replayed = client.post(
                "/api/v1/jobs/analysis", headers=headers, json=payload
            )
            assert replayed.status_code == 201
            assert replayed.json()["id"] == str(job_id)
            assert replayed.json()["status"] == "succeeded"
            assert replayed.json()["profile_id"] == str(profile_id)
    finally:
        test_app.dependency_overrides.clear()

    assert [target.canonical_id for target in resolver.targets] == ["@alpha", "@alpha"]
    assert dispatcher.calls == [job_id]
    assert youtube.failure is None
    assert artifacts.names == [
        "youtube-channel.json",
        "youtube-playlist-pages.json",
        "youtube-video-responses.json",
    ]
    assert pages.calls == ["https://creator.example/about"]
    with vertical_factory() as database_session:
        assert (
            database_session.scalar(select(func.count()).select_from(AnalysisJob)) == 1
        )
        assert (
            database_session.scalar(select(func.count()).select_from(CreatorProfile))
            == 1
        )
        assert database_session.get(CreatorProfile, profile_id) is not None
