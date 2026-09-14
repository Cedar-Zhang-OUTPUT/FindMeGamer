from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from app.db.models.jobs import AnalysisJob
from app.db.models.enums import JobStatus
from app.db.models.match import MatchTask, MatchCandidateInput
from app.db.models.profiles import CreatorProfile
from tests.integration.test_discover_analysis_batches import seed, submit_batch, service
from tests.integration.test_match_input_lock import _creator


def finish_creator(session, job, monkeypatch, *, fail=False):
    from app.workers import analysis_tasks
    from tests.integration.test_creator_analysis_commit import _pipeline
    from tests.unit.analysis.test_creator_pipeline import _source
    from app.integrations.errors import TransientIntegrationError

    now = datetime.now(UTC) + timedelta(seconds=1)

    @contextmanager
    def sessions():
        yield session

    class YouTube:
        def fetch_creator(self, channel_id, video_limit=50):
            if fail:
                raise TransientIntegrationError("youtube_unavailable")
            source = _source()
            return source.model_copy(
                update={
                    "channel_id": channel_id,
                    "canonical_url": "https://www.youtube.com/channel/" + channel_id,
                    "videos": tuple(
                        v.model_copy(update={"channel_id": channel_id})
                        for v in source.videos
                    ),
                }
            )

    @contextmanager
    def pipelines(target_type):
        yield _pipeline(sessions, youtube=YouTube(), clock=lambda: now)

    monkeypatch.setattr(
        analysis_tasks,
        "get_analysis_executor",
        lambda: analysis_tasks.AnalysisJobExecutor(
            session_factory=sessions, pipeline_factory=pipelines, clock=lambda: now
        ),
    )
    analysis_tasks.run_analysis_job.push_request(retries=10)
    try:
        analysis_tasks.run_analysis_job.run(str(job.id))
    finally:
        analysis_tasks.run_analysis_job.pop_request()
    session.expire_all()
    assert session.get(AnalysisJob, job.id).status == (
        JobStatus.FAILED if fail else JobStatus.SUCCEEDED
    )


def test_mixed_batch_matches_entire_library_once_through_worker_and_restart(
    auth_client, session, job_dispatcher, match_dispatcher, smtp_gateway, monkeypatch
):
    discovery, candidates = seed(session, 920, 921)
    old = _creator(919)
    session.add(old)
    session.flush()
    key = str(uuid4())
    response = submit_batch(
        auth_client, discovery, candidates, key=key, mode="analyze_and_match"
    )
    assert response.status_code == 202
    batch_id = UUID(response.json()["id"])
    coordinator = service(session, job_dispatcher, match_dispatcher)
    coordinator.execute(batch_id)
    jobs = {j.canonical_target_id: j for j in session.scalars(select(AnalysisJob))}
    finish_creator(session, jobs[candidates[0].platform_account_id], monkeypatch)
    finish_creator(
        session, jobs[candidates[1].platform_account_id], monkeypatch, fail=True
    )
    from app.workers import discover_batch_tasks

    monkeypatch.setattr(
        discover_batch_tasks,
        "get_discover_batch_service",
        lambda: service(session, job_dispatcher, match_dispatcher),
    )
    discover_batch_tasks.run_discover_batch.run(str(batch_id))
    detail = auth_client.get(
        f"/api/v1/discover/{discovery.id}/analysis-batches/{batch_id}"
    ).json()
    assert detail["status"] == "partial"
    assert detail["match_task_id"] is not None
    match_id = UUID(detail["match_task_id"])
    new = session.scalar(
        select(CreatorProfile).where(
            CreatorProfile.platform_account_id == candidates[0].platform_account_id
        )
    )
    locked = set(
        session.scalars(
            select(MatchCandidateInput.creator_id).where(
                MatchCandidateInput.match_task_id == match_id
            )
        )
    )
    assert locked == {old.id, new.id}
    discover_batch_tasks.run_discover_batch.run(str(batch_id))
    assert submit_batch(
        auth_client, discovery, candidates, key=key, mode="analyze_and_match"
    ).json()["match_task_id"] == str(match_id)
    # A separately retried ordinary Analysis cannot schedule another automatic Match.
    retry = auth_client.post(
        f"/api/v1/jobs/analysis/{jobs[candidates[1].platform_account_id].id}/retry",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert retry.status_code == 201
    finish_creator(
        session, session.get(AnalysisJob, UUID(retry.json()["id"])), monkeypatch
    )
    discover_batch_tasks.run_discover_batch.run(str(batch_id))
    assert session.scalar(select(func.count()).select_from(MatchTask)) == 1
    assert smtp_gateway.sends == []


@pytest.mark.parametrize("invalid_game", [False, True])
def test_auto_match_blocks_invalid_inputs_without_empty_match(
    auth_client, session, job_dispatcher, match_dispatcher, invalid_game
):
    from app.db.models.profiles import GameProfile

    discovery, candidates = seed(session, 930)
    if invalid_game:
        creator = _creator(930)
        session.add(creator)
        session.get(GameProfile, discovery.game_id).brief = {}
        session.flush()
    response = submit_batch(
        auth_client, discovery, candidates, mode="analyze_and_match"
    )
    assert response.status_code == 202
    identifier = UUID(response.json()["id"])
    coordinator = service(session, job_dispatcher, match_dispatcher)
    coordinator.execute(identifier)
    if not invalid_game:
        from app.workers.analysis_tasks import write_terminal_failure, TerminalFailure

        job = session.scalar(select(AnalysisJob))
        write_terminal_failure(
            job.id,
            TerminalFailure(
                "analysis_internal_error",
                "Analysis failed unexpectedly. Please retry.",
                True,
            ),
            session_factory=coordinator.sessions,
            clock=lambda: datetime.now(UTC) + timedelta(seconds=1),
        )
        coordinator.execute(identifier)
    detail = auth_client.get(
        f"/api/v1/discover/{discovery.id}/analysis-batches/{identifier}"
    ).json()
    assert detail["status"] == "blocked"
    assert detail["error"]["code"] == (
        "game_profile_unusable" if invalid_game else "no_eligible_creators"
    )
    assert session.scalar(select(func.count()).select_from(MatchTask)) == 0


def test_publication_recovery_keeps_analysis_and_match_ids(
    auth_client, session, job_dispatcher, match_dispatcher
):
    discovery, candidates = seed(session, 940)
    response = submit_batch(
        auth_client, discovery, candidates, mode="analyze_and_match"
    )
    assert response.status_code == 202
    identifier = UUID(response.json()["id"])
    coordinator = service(session, job_dispatcher, match_dispatcher)
    now = datetime.now(UTC)
    coordinator.clock = lambda: now
    job_dispatcher.error = RuntimeError("broker offline")
    coordinator.execute(identifier)
    analysis_id = session.scalar(select(AnalysisJob.id))
    now += timedelta(minutes=3)
    job_dispatcher.error = None
    coordinator.execute(identifier)
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1
    assert job_dispatcher.calls == [analysis_id, analysis_id]
    # A usable profile resolves the outstanding selection without another Analysis.
    creator = _creator(940)
    creator.last_analyzed_at = now
    session.add(creator)
    session.flush()
    match_dispatcher.error = RuntimeError("ambiguous broker delivery")
    coordinator.execute(identifier)
    match_id = session.scalar(select(MatchTask.id))
    assert match_id is not None
    now += timedelta(minutes=3)
    match_dispatcher.error = None
    from app.workers.discover_batch_tasks import sweep_discover_batches

    published = []
    assert (
        sweep_discover_batches(
            session_factory=coordinator.sessions,
            dispatch=published.append,
            clock=lambda: now,
        )
        == 1
    )
    assert published == [str(identifier)]
    coordinator.execute(identifier)
    assert session.scalar(select(func.count()).select_from(MatchTask)) == 1
    assert [call[1] for call in match_dispatcher.calls] == [match_id, match_id]
