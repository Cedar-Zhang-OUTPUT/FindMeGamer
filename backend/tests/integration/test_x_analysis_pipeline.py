from contextlib import contextmanager
from copy import deepcopy
import json
import importlib.util
from importlib import import_module
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.core.crypto import SecretCipher
from app.core.database import get_session
from app.core.security import hash_workspace_key
from app.db.models.profiles import CreatorProfile
from app.main import create_app
from app.integrations.x_creator import XCreatorGateway
from app.analysis.creator_checkpoints import CreatorAnalysisCheckpointStore
from app.workers.analysis_tasks import AnalysisJobExecutor
from app.workers.analysis_tasks import _failure_for
from app.integrations.errors import (
    IntegrationError,
    InvalidModelOutput,
    TransientIntegrationError,
)
from app.db.models.settings import SharedSettings
from tests.integration.test_analyze_vertical_slice import (
    vertical_factory,
    AllowAllRateLimiter,
    AfterCommitDispatcher,
)
from tests.integration.test_creator_analysis_commit import Artifacts
from tests.integration.test_library_v2_creators import new_creator, edit
from tests.integration.test_x_analysis import queue
from tests.unit.integrations.test_x_creator import user_payload, posts_payload


@pytest.fixture
def x_vertical(vertical_factory, workspace_access_key):
    factory = vertical_factory
    with factory() as session:
        original_collection_enabled = dict(
            session.scalar(select(SharedSettings)).collection_enabled
        )

    @contextmanager
    def session_factory():
        with factory() as session:
            yield session

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AllowAllRateLimiter(),
        secret_cipher=SecretCipher(bytes(range(32))),
        job_session_factory=session_factory,
        job_dispatcher=AfterCommitDispatcher(factory),
    )

    def api_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = api_session
    with TestClient(
        app, headers={"Authorization": f"Bearer {workspace_access_key}"}
    ) as client:
        try:
            yield client, factory, session_factory
        finally:
            with factory.begin() as session:
                settings = session.scalar(select(SharedSettings))
                settings.collection_enabled = original_collection_enabled


class SourceAI:
    def __init__(self):
        self.calls = []

    def complete_structured(self, model, messages, schema, *, max_tokens=None):
        self.calls.append((model, messages, max_tokens))
        payload = json.loads(messages[-1].content.split("\n", 1)[1])
        reference = (
            payload["posts"][0]["source_id"]
            if payload.get("posts")
            else (
                payload["validated_intermediate_interpretations"][0]["content_summary"][
                    "cited_source_ids"
                ][0]
                if payload.get("validated_intermediate_interpretations")
                else "account"
            )
        )
        claim = {
            "status": "available",
            "text": "Public game review posts suggest a gaming focus.",
            "cited_source_ids": [reference],
            "kind": "ai_inference",
        }
        unknown = {"status": "unavailable", "reason": "Insufficient source evidence."}
        return schema.model_validate(
            {
                "english_language_check": True,
                "content_summary": claim,
                "content_style": unknown,
                "audience_inference": unknown,
                "promotion_fit": unknown,
                "brand_safety": unknown,
            }
        )


def make_pipeline(session_factory, gateway, ai):
    module_name = "app.analysis.x_pipeline"
    assert importlib.util.find_spec(
        module_name
    ), "The full X Analyze pipeline is missing"
    module = import_module(module_name)
    return module.XCreatorAnalysisPipeline(
        session_factory=session_factory,
        x=gateway,
        deepseek=ai,
        artifacts=Artifacts(),
        checkpoints=CreatorAnalysisCheckpointStore(session_factory=session_factory),
    )


def test_x_real_pipeline_publishes_same_library_uuid_manual_values_and_job_result(
    x_vertical,
):
    client, factory, session_factory = x_vertical
    with factory.begin() as session:
        settings = session.scalar(select(SharedSettings))
        settings.collection_enabled = {
            **settings.collection_enabled,
            "youtube": False,
            "x": True,
        }
    creator = new_creator(
        client,
        platform="x",
        account_id="123456",
        name="Human X",
        internal_notes="Keep private note",
        languages=["Japanese"],
    )
    queued = queue(client, creator)
    assert queued.status_code == 201, queued.text
    job_id = UUID(queued.json()["id"])
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=(
                posts_payload()
                if request.url.path.endswith("tweets")
                else user_payload()
            ),
        )

    ai = SourceAI()
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        XCreatorGateway(bearer_token="fixture", http_client=transport) as gateway,
    ):
        pipeline = make_pipeline(session_factory, gateway, ai)

        @contextmanager
        def x_factory():
            yield pipeline

        def other_factory(target):
            pytest.fail("An X job must not construct a YouTube pipeline")

        executor = AnalysisJobExecutor(
            session_factory=session_factory,
            pipeline_factory=other_factory,
            x_pipeline_factory=x_factory,
        )
        executor.execute(job_id)
        assert str(pipeline.run(job_id)) == creator["id"]
    assert len(requests) == 2 and len(ai.calls) == 1
    result = client.get(f"/api/v2/library/creators/{creator['id']}").json()
    assert (
        result["name"] == "Human X" and result["internal_notes"] == "Keep private note"
    )
    assert result["languages"] == ["Japanese"] and result["source_fields"][
        "languages"
    ] == ["en"]
    assert result["analysis_available"] and result["last_analyzed_at"]
    assert result["analysis"]["content_summary"]["kind"] == "ai_inference"
    assert result["source_status"]["coverage"] == "recent_account_posts"
    assert [contact["email"] for contact in result["contacts"]] == ["press@example.com"]
    polled = client.get(f"/api/v1/jobs/{job_id}")
    assert polled.status_code == 200, polled.text
    assert (
        polled.json()["status"] == "succeeded"
        and polled.json()["profile_id"] == creator["id"]
    )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 1
        row = session.get(CreatorProfile, UUID(creator["id"]))
        assert row.platform == "x" and row.youtube_channel_id is None
        assert row.analysis["content_summary"]["cited_source_ids"] == ["456789"]
        assert row.works[0].source_fields["language"] == "en"
        assert row.works[0].source_fields["content_type"] == "unverified"
        assert row.next_analysis_at > row.last_analyzed_at


@pytest.mark.parametrize("failure", ["source", "invalid_citation", "model"])
def test_failed_x_reanalysis_preserves_profile_and_public_failure_is_pollable(
    x_vertical, failure
):
    client, factory, sessions = x_vertical
    creator = new_creator(client, platform="x", account_id="123456", name="Human X")
    state = {"fail": False}

    def handler(request):
        if state["fail"] and failure == "source":
            return httpx.Response(403, text="private-provider-detail")
        return httpx.Response(
            200,
            json=(
                posts_payload()
                if request.url.path.endswith("tweets")
                else user_payload()
            ),
        )

    class AI(SourceAI):
        def complete_structured(self, *args, **kwargs):
            if state["fail"] and failure == "model":
                raise TransientIntegrationError("deepseek_unavailable")
            output = super().complete_structured(*args, **kwargs)
            if state["fail"] and failure == "invalid_citation":
                output.content_summary.cited_source_ids = ["invented-post"]
            return output

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        XCreatorGateway(bearer_token="fixture", http_client=transport) as gateway,
    ):
        pipeline = make_pipeline(sessions, gateway, AI())
        first = queue(client, creator).json()
        pipeline.run(UUID(first["id"]))
        before = client.get(f"/api/v2/library/creators/{creator['id']}").json()
        state["fail"] = True
        next_job = queue(client, creator).json()
        job_id = UUID(next_job["id"])
        with pytest.raises(IntegrationError) as caught:
            pipeline.run(job_id)
        executor = AnalysisJobExecutor(
            session_factory=sessions, pipeline_factory=lambda _: None
        )
        assert executor.fail(job_id, _failure_for(caught.value.code))
        polled = client.get(f"/api/v1/jobs/{job_id}")
        assert polled.status_code == 200, polled.text
        assert polled.json()["status"] == "failed"
        assert polled.json()["error"]["code"] == caught.value.code
        assert "private-provider-detail" not in polled.text
        assert client.get(f"/api/v2/library/creators/{creator['id']}").json() == before


def test_x_batched_analysis_checkpoints_and_successful_refresh_clear_staleness(
    x_vertical,
):
    client, factory, sessions = x_vertical
    creator = new_creator(client, platform="x", account_id="123456", languages=[])
    with factory.begin() as session:
        row = session.get(CreatorProfile, UUID(creator["id"]))
        row.source_status = {"x": "stale", "freshness": "stale"}
    payload = posts_payload()
    payload["data"] = [{**payload["data"][0], "id": str(456789 + i)} for i in range(21)]
    payload["meta"]["result_count"] = 21
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json=payload if request.url.path.endswith("tweets") else user_payload()
        )

    ai = SourceAI()
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        XCreatorGateway(bearer_token="fixture", http_client=transport) as gateway,
    ):
        pipeline = make_pipeline(sessions, gateway, ai)
        job_id = UUID(queue(client, creator).json()["id"])
        assert str(pipeline.run(job_id)) == creator["id"]
        pipeline.run(job_id)
    assert len(calls) == 2 and len(ai.calls) == 4
    assert all(call[2] == 4096 for call in ai.calls)
    result = client.get(f"/api/v2/library/creators/{creator['id']}").json()
    assert result["languages"] == [] and result["source_fields"]["languages"] == ["en"]
    assert result["source_status"]["freshness"] == "current"
    assert result["source_status"]["sample_size"] == 21


def test_x_resume_reuses_successful_source_and_batch_checkpoints(x_vertical):
    client, factory, sessions = x_vertical
    creator = new_creator(client, platform="x", account_id="123456")
    payload = posts_payload()
    payload["data"] = [{**payload["data"][0], "id": str(456789 + i)} for i in range(21)]
    payload["meta"]["result_count"] = 21
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json=payload if request.url.path.endswith("tweets") else user_payload()
        )

    class FailFinalOnce(SourceAI):
        failed = False
        attempts = 0

        def complete_structured(self, model, messages, schema, **kwargs):
            self.attempts += 1
            if (
                "validated_intermediate_interpretations" in messages[-1].content
                and not self.failed
            ):
                self.failed = True
                raise TransientIntegrationError("deepseek_unavailable")
            return super().complete_structured(model, messages, schema, **kwargs)

    ai = FailFinalOnce()
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        XCreatorGateway(bearer_token="fixture", http_client=transport) as gateway,
    ):
        pipeline = make_pipeline(sessions, gateway, ai)
        job_id = UUID(queue(client, creator).json()["id"])
        with pytest.raises(TransientIntegrationError):
            pipeline.run(job_id)
        assert (
            client.get(f"/api/v2/library/creators/{creator['id']}").json()[
                "last_analyzed_at"
            ]
            is None
        )
        assert str(pipeline.run(job_id)) == creator["id"]
    assert len(requests) == 2 and ai.attempts == 5


def test_x_refresh_preserves_manual_work_contact_overrides_and_historical_job_identity(
    x_vertical,
):
    client, factory, sessions = x_vertical
    creator = new_creator(client, platform="x", account_id="123456")

    def handler(request):
        return httpx.Response(
            200,
            json=(
                posts_payload()
                if request.url.path.endswith("tweets")
                else user_payload()
            ),
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        XCreatorGateway(bearer_token="fixture", http_client=transport) as gateway,
    ):
        pipeline = make_pipeline(sessions, gateway, SourceAI())
        original_job = UUID(queue(client, creator).json()["id"])
        pipeline.run(original_job)
        with factory.begin() as session:
            row = session.get(CreatorProfile, UUID(creator["id"]))
            work, contact = row.works[0], row.contacts[0]
            work_id, contact_id = work.id, contact.id
            work.manual_overrides = {
                "content_title": "Human clip",
                "verification_notes": "Human note",
            }
            contact.manual_overrides = {"purpose": "Media only", "is_active": False}
        pipeline.run(UUID(queue(client, creator).json()["id"]))
    with factory() as session:
        row = session.get(CreatorProfile, UUID(creator["id"]))
        assert (
            row.works[0].id == work_id
            and row.works[0].manual_overrides["content_title"] == "Human clip"
        )
        assert (
            row.contacts[0].id == contact_id and row.contacts[0].purpose == "Media only"
        )
        assert row.contacts[0].is_active is False
    current = client.get(f"/api/v2/library/creators/{creator['id']}").json()
    response = client.put(
        f"/api/v2/library/creators/{creator['id']}/identity",
        json={
            "expected_revision": current["revision"],
            "platform": "x",
            "account_id": "654321",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    polled = client.get(f"/api/v1/jobs/{original_job}")
    assert polled.status_code == 200, polled.text
    assert polled.json()["profile_id"] == creator["id"]
