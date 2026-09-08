from contextlib import contextmanager
from datetime import datetime, UTC
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.analysis.creator_map_reduce_pipeline import CreatorMapReducePipeline
from app.analysis.service import CreatorAnalysisService
from app.core.crypto import SecretCipher
from app.core.database import get_session
from app.core.security import hash_workspace_key
from app.db.models.profiles import CreatorProfile
from app.main import create_app
from app.discovery.library import import_discovered_account
from app.schemas.discovery import DiscoveredAccount
from tests.integration.test_analyze_vertical_slice import (
    vertical_factory,
    AllowAllRateLimiter,
    AlphaChannelResolver,
    AfterCommitDispatcher,
)
from tests.integration.test_creator_analysis_commit import Artifacts
from tests.integration.test_creator_content_languages import youtube_language_source
from tests.integration.test_library_v2_creators import new_creator, edit
from tests.unit.analysis.test_creator_pipeline import FakePages
from tests.unit.analysis.test_creator_map_reduce_pipeline import (
    ConcurrentAI,
    MemoryCheckpoints,
)


@pytest.mark.parametrize(
    "seed_kind, audio, expected",
    [
        ("url", "en-US", ["en-US"]),
        ("url", None, []),
        ("url", "und", []),
        ("discovery", "en-US", ["en-US"]),
    ],
)
def test_binding_then_production_map_reduce_preserves_uuid_and_publishes_source_language(
    vertical_factory,
    workspace_access_key,
    seed_kind,
    audio,
    expected,
):
    factory = vertical_factory

    @contextmanager
    def session_factory():
        with factory() as session:
            yield session

    dispatcher = AfterCommitDispatcher(factory)
    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        channel_resolver=AlphaChannelResolver(),
        job_session_factory=session_factory,
        job_dispatcher=dispatcher,
    )

    def api_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = api_session
    source = youtube_language_source(audio=audio)

    class YouTube:
        def fetch_creator(self, channel_id, video_limit=50):
            assert channel_id == source.channel_id
            return source

    checkpoints = MemoryCheckpoints()
    ai = ConcurrentAI()
    pipeline = CreatorMapReducePipeline(
        service=CreatorAnalysisService(session_factory=session_factory),
        youtube=YouTube(),
        artifacts=Artifacts(),
        public_pages=FakePages({}),
        deepseek=ai,
        checkpoints=checkpoints,
    )
    with TestClient(
        app, headers={"Authorization": f"Bearer {workspace_access_key}"}
    ) as client:
        if seed_kind == "url":
            original = new_creator(
                client,
                platform="youtube",
                account_id=None,
                profile_url="https://www.youtube.com/@fixturecreator",
                name="Human title",
                internal_notes="Keep these notes",
            )
        else:
            with factory.begin() as session:
                imported = import_discovered_account(
                    session,
                    DiscoveredAccount(
                        platform="youtube",
                        account_id=source.channel_id,
                        profile_url=source.canonical_url,
                        display_name="Source title",
                        collected_at=datetime.now(UTC),
                    ),
                    [],
                )
                imported_id = str(imported.id)
            original = client.get(f"/api/v2/library/creators/{imported_id}").json()
        path = f"/api/v2/library/creators/{original['id']}"
        if seed_kind == "url":
            bound = client.post(
                path + "/youtube-binding",
                headers={"Idempotency-Key": str(uuid4())},
                json={
                    "url": original["profile_url"],
                    "expected_revision": original["revision"],
                },
            )
            assert bound.status_code == 200, bound.text
            target_url = bound.json()["source_identity"]["canonical_url"]
        else:
            assert original["last_analyzed_at"] is None
            target_url = original["source_identity"]["canonical_url"]
        queued = client.post(
            "/api/v1/jobs/analysis",
            headers={"Idempotency-Key": str(uuid4())},
            json={"target_type": "creator", "url": target_url, "mode": "reanalyze"},
        )
        assert queued.status_code == 201, queued.text
        job_id = UUID(queued.json()["id"])
        assert dispatcher.calls == [job_id]
        assert str(pipeline.run(job_id)) == original["id"]
        result = client.get(path).json()
        assert result["id"] == original["id"]
        if seed_kind == "url":
            assert result["name"] == "Human title"
            assert result["internal_notes"] == "Keep these notes"
        assert result["last_analyzed_at"] is not None
        assert result["languages"] == expected
        assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "succeeded"
        filtered = client.get(
            "/api/v2/library/creators", params={"language": "English"}
        ).json()
        assert [item["id"] for item in filtered["items"]] == (
            [original["id"]] if expected else []
        )
        assert ai.calls, "The actual MapReduce model stages must execute"
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 1
            profile = session.get(CreatorProfile, UUID(original["id"]))
            assert profile.current_facts["languages"] == expected
            assert profile.works[0].source_fields["language"] == audio
            assert profile.current_facts["language_evidence"] == (
                [
                    {
                        "language": audio,
                        "source_url": "https://www.youtube.com/watch?v=video-001",
                        "source_field": "snippet.defaultAudioLanguage",
                    }
                ]
                if expected
                else []
            )
        changed = edit(client, result, languages=["Japanese"])
        assert changed.status_code == 200, changed.text
        assert changed.json()["languages"] == ["Japanese"]
        assert changed.json()["source_fields"]["languages"] == expected
