from uuid import UUID, uuid4
from contextlib import contextmanager
from datetime import datetime, UTC, timedelta

from sqlalchemy import select

from app.db.models.jobs import AnalysisJob
from app.db.models.settings import SharedSettings
from app.db.models.profiles import CreatorProfile
from app.workers.schedules import ScheduledReanalysisService
from app.workers.analysis_tasks import AnalysisJobExecutor
from tests.integration.test_library_v2_creators import new_creator, post


def queue(client, creator, *, key=None):
    return post(
        client,
        "/api/v1/jobs/analysis",
        payload={
            "target_type": "creator",
            "url": creator["source_identity"]["canonical_url"],
            "mode": "reanalyze",
        },
        key=key,
    )


def test_x_account_uses_existing_job_protocol_and_its_own_collection_switch(
    auth_client, session
):
    creator = new_creator(
        auth_client, platform="x", account_id="123456", name="Manual X"
    )
    settings = session.scalar(select(SharedSettings))
    settings.collection_enabled = {
        **settings.collection_enabled,
        "youtube": False,
        "x": True,
    }
    session.commit()
    key = str(uuid4())
    response = queue(auth_client, creator, key=key)
    assert response.status_code == 201, response.text
    result = response.json()
    assert (
        result["target_type"] == "creator"
        and result["canonical_target_id"] == "x:123456"
    )
    assert result["canonical_url"] == "https://x.com/i/user/123456"
    assert result["status"] == "queued"
    assert queue(auth_client, creator, key=key).json()["id"] == result["id"]
    assert queue(auth_client, creator).json()["id"] == result["id"]
    assert (
        auth_client.get(f"/api/v1/jobs/{result['id']}").json()["waiting_reason"] is None
    )
    settings.collection_enabled = {**settings.collection_enabled, "x": False}
    session.commit()
    assert queue(auth_client, creator).status_code == 409
    assert (
        auth_client.get(f"/api/v1/jobs/{result['id']}").json()["waiting_reason"]
        == "collection_disabled"
    )
    response = auth_client.put(
        f"/api/v2/library/creators/{creator['id']}/identity",
        json={
            "expected_revision": creator["revision"],
            "platform": "x",
            "account_id": "654321",
            "confirmed": True,
        },
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "creator_analysis_in_progress"
    )


def test_youtube_first_binding_never_accepts_x_after_multiplatform_jobs_are_added(
    auth_client,
):
    creator = new_creator(
        auth_client,
        platform="youtube",
        account_id=None,
        profile_url="https://www.youtube.com/@fixturecreator",
    )
    response = post(
        auth_client,
        f"/api/v2/library/creators/{creator['id']}/youtube-binding",
        payload={
            "url": "https://x.com/i/user/123456",
            "expected_revision": creator["revision"],
        },
    )
    assert response.status_code == 422


def test_x_scheduled_reanalysis_respects_x_pause_and_reuses_the_active_target(
    auth_client, session
):
    creator = new_creator(auth_client, platform="x", account_id="123456")
    now = datetime.now(UTC)
    row = session.get(CreatorProfile, UUID(creator["id"]))
    row.last_analyzed_at = now - timedelta(days=31)
    row.next_analysis_at = now - timedelta(days=1)
    row.source_status = {"x": "available"}
    settings = session.scalar(select(SharedSettings))
    settings.collection_enabled = {
        **settings.collection_enabled,
        "x": False,
        "youtube": False,
    }
    session.commit()
    dispatched = []

    class Dispatcher:
        def dispatch(self, job_id):
            dispatched.append(job_id)

    @contextmanager
    def factory():
        yield session

    scheduler = ScheduledReanalysisService(
        session_factory=factory, dispatcher=Dispatcher(), clock=lambda: now
    )
    assert scheduler.run() == 0
    settings.collection_enabled = {**settings.collection_enabled, "x": True}
    session.commit()
    assert scheduler.run() == 1
    assert scheduler.run() == 0
    assert len(dispatched) == 1
    job = session.get(AnalysisJob, dispatched[0])
    assert job.canonical_target_id == "x:123456" and job.mode == "reanalyze"
    session.refresh(row)
    assert (
        row.source_status["x"] == "stale" and row.source_status["freshness"] == "stale"
    )


def test_paused_x_worker_requires_explicit_resume_without_youtube_access(
    auth_client, session
):
    creator = new_creator(auth_client, platform="x", account_id="123456")
    job_id = queue(auth_client, creator).json()["id"]
    settings = session.scalar(select(SharedSettings))
    settings.collection_enabled = {"youtube": False, "x": False}
    session.commit()

    @contextmanager
    def factory():
        yield session

    def forbidden(*args):
        raise AssertionError("Paused job must not construct providers")

    executor = AnalysisJobExecutor(
        session_factory=factory,
        pipeline_factory=forbidden,
        x_pipeline_factory=forbidden,
    )
    executor.execute(UUID(job_id))
    assert (
        auth_client.get(f"/api/v1/jobs/{job_id}").json()["waiting_reason"]
        == "collection_disabled"
    )
    settings.collection_enabled = {**settings.collection_enabled, "x": True}
    session.commit()
    assert (
        auth_client.get(f"/api/v1/jobs/{job_id}").json()["waiting_reason"]
        == "explicit_resume_required"
    )
    response = post(auth_client, f"/api/v1/jobs/analysis/{job_id}/resume", payload={})
    assert response.status_code == 200, response.text
    assert response.json()["waiting_reason"] is None


def test_discovery_reports_full_x_analysis_capability(auth_client):
    from app.schemas.discovery import platform_capabilities

    capabilities = {item.platform: item for item in platform_capabilities()}
    assert capabilities["x"].analysis_available
    assert not capabilities["twitch"].analysis_available
    assert not capabilities["instagram"].analysis_available
