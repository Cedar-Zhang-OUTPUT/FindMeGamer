from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.analysis.targets import CanonicalTarget
from app.db.models.enums import JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile, GameProfile
from app.repositories.collection_settings import update_collection
from app.repositories.jobs import JobsRepository


def test_disabled_creator_submit_rejects_before_handle_resolution(
    auth_client, session, job_dispatcher
):
    update_collection(session, "youtube", False)
    session.commit()
    response = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "target_type": "creator",
            "url": "https://www.youtube.com/@fixture",
            "mode": "reanalyze",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "collection_disabled"
    assert session.scalar(select(AnalysisJob.id)) is None
    assert job_dispatcher.calls == []
    game = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "target_type": "game",
            "url": "https://store.steampowered.com/app/123/",
            "mode": "reanalyze",
        },
    )
    assert game.status_code == 201


@pytest.mark.parametrize("method", ["create_or_reuse_job", "create_creator_seed_job"])
def test_all_new_creator_job_insertions_respect_switch(session, method):
    from app.core.errors import APIError

    update_collection(session, "youtube", False)
    target = CanonicalTarget(
        target_type=TargetType.CREATOR,
        canonical_id="UCfixture12",
        canonical_url="https://www.youtube.com/channel/UCfixture12",
    )
    kwargs = {"correlation_id": str(uuid4())}
    if method == "create_or_reuse_job":
        kwargs["mode"] = JobMode.REANALYZE
    with pytest.raises(APIError) as error:
        getattr(JobsRepository(session), method)(target, **kwargs)
    assert error.value.code == "collection_disabled"
    assert session.scalar(select(AnalysisJob.id)) is None


def test_queued_delivery_pauses_without_failure_and_explicit_resume_is_required(
    auth_client, session, job_dispatcher
):
    from app.workers.analysis_tasks import AnalysisJobExecutor

    job = AnalysisJob(
        target_type=TargetType.CREATOR,
        canonical_target_id="UCfixture12",
        canonical_url="https://www.youtube.com/channel/UCfixture12",
    )
    session.add(job)
    session.commit()
    job_id = job.id
    update_collection(session, "youtube", False)
    session.commit()

    @contextmanager
    def sessions():
        yield session

    @contextmanager
    def forbidden(target_type):
        pytest.fail("Paused job performed acquisition")
        yield

    executor = AnalysisJobExecutor(session_factory=sessions, pipeline_factory=forbidden)
    executor.execute(job_id)
    response = auth_client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["waiting_reason"] == "collection_disabled"
    assert response.json()["error"] is None
    assert response.json()["resume_available"] is False
    update_collection(session, "youtube", True)
    session.commit()
    executor.execute(job_id)  # A duplicate delivery cannot bypass explicit resume.
    current = auth_client.get(f"/api/v1/jobs/{job_id}").json()
    assert current["waiting_reason"] == "explicit_resume_required"
    assert current["resume_available"] is True
    assert job_dispatcher.calls == []
    resumed = auth_client.post(
        f"/api/v1/jobs/analysis/{job_id}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert resumed.status_code == 200
    assert resumed.json()["waiting_reason"] is None
    assert job_dispatcher.calls == [job_id]


def test_disabled_due_creators_do_not_starve_game_or_rewrite_dates(session):
    from app.repositories.profiles import ProfilesRepository

    now = datetime.now(UTC)
    creator = CreatorProfile(
        platform="youtube",
        platform_account_id="UCfixture12",
        youtube_channel_id="UCfixture12",
        canonical_url="https://www.youtube.com/channel/UCfixture12",
        sort_name="Creator",
        next_analysis_at=now - timedelta(days=2),
    )
    game = GameProfile(
        steam_app_id="123",
        canonical_url="https://store.steampowered.com/app/123/",
        sort_name="Game",
        next_analysis_at=now - timedelta(days=1),
    )
    session.add_all([creator, game])
    session.flush()
    original = creator.next_analysis_at
    update_collection(session, "youtube", False)
    due = ProfilesRepository(session).list_due_profiles(now=now, limit=1)
    assert [row.profile_id for row in due] == [game.id]
    assert creator.next_analysis_at == original


def test_disable_between_claim_and_source_pauses_running_job_then_resumes(
    auth_client, session, job_dispatcher
):
    from app.analysis.service import CreatorAnalysisService
    from app.workers.analysis_tasks import AnalysisJobExecutor

    job = AnalysisJob(
        target_type=TargetType.CREATOR,
        canonical_target_id="UCfixture12",
        canonical_url="https://www.youtube.com/channel/UCfixture12",
    )
    session.add(job)
    session.commit()
    job_id = job.id

    @contextmanager
    def sessions():
        yield session

    class Pipeline:
        def run(self, current_id):
            CreatorAnalysisService(session_factory=sessions).start(current_id)
            pytest.fail("Disabled source acquisition started after claim")

    @contextmanager
    def pipelines(target_type):
        update_collection(session, "youtube", False)
        session.commit()
        yield Pipeline()

    AnalysisJobExecutor(session_factory=sessions, pipeline_factory=pipelines).execute(
        job_id
    )
    current = auth_client.get(f"/api/v1/jobs/{job_id}").json()
    assert current["status"] == "running"
    assert current["waiting_reason"] == "collection_disabled"
    update_collection(session, "youtube", True)
    session.commit()
    response = auth_client.post(
        f"/api/v1/jobs/analysis/{job_id}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200
    assert job_dispatcher.calls == [job_id]


def test_resume_queue_failure_can_recover_same_request_without_staying_paused(
    auth_client, session, job_dispatcher
):
    job = AnalysisJob(
        target_type=TargetType.CREATOR,
        canonical_target_id="UCfixture12",
        canonical_url="https://www.youtube.com/channel/UCfixture12",
        collection_paused=True,
    )
    session.add(job)
    session.commit()
    key = {"Idempotency-Key": str(uuid4())}
    path = f"/api/v1/jobs/analysis/{job.id}/resume"
    job_dispatcher.error = RuntimeError("fixture queue down")
    failed = auth_client.post(path, headers=key)
    assert failed.status_code == 503
    assert (
        auth_client.get(f"/api/v1/jobs/{job.id}").json()["waiting_reason"]
        == "explicit_resume_required"
    )
    job_dispatcher.error = None
    resumed = auth_client.post(path, headers=key)
    assert resumed.status_code == 200
    assert resumed.json()["waiting_reason"] is None
    session.refresh(job)
    assert job.collection_paused is False
    count = len(job_dispatcher.calls)
    assert auth_client.post(path, headers=key).status_code == 200
    assert len(job_dispatcher.calls) == count
