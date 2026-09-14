from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID, uuid4, uuid5

import pytest

from sqlalchemy import select, func

from app.db.models.discover import DiscoverJob, DiscoverCandidate
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile
from tests.integration.test_match_input_lock import _creator, _game, NOW


def seed(session, *numbers):
    game = _game()
    session.add(game)
    session.flush()
    discovery = DiscoverJob(
        idempotency_key=str(uuid4()),
        request_hash="a" * 64,
        game_id=game.id,
        steam_url=game.canonical_url,
        game_name=game.sort_name,
        game_snapshot={"brief": game.brief},
        conditions={},
        status="done",
    )
    session.add(discovery)
    session.flush()
    candidates = []
    for number in numbers:
        account = f"UC{number:022d}"
        row = DiscoverCandidate(
            id=uuid5(discovery.id, "youtube:" + account),
            discover_id=discovery.id,
            platform="youtube",
            platform_account_id=account,
            metadata_snapshot={
                "canonical_url": "https://www.youtube.com/channel/" + account
            },
        )
        session.add(row)
        candidates.append(row)
    session.flush()
    return discovery, candidates


def submit_batch(client, discovery, candidates, *, key=None, mode="analyze"):
    return client.post(
        f"/api/v1/discover/{discovery.id}/analysis-batches",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"candidate_ids": [str(c.id) for c in candidates], "mode": mode},
    )


def service(session, job_dispatcher, match_dispatcher):
    from app.discovery.batches import DiscoverBatchService

    @contextmanager
    def sessions():
        yield session

    return DiscoverBatchService(
        session_factory=sessions,
        analysis_dispatcher=job_dispatcher,
        match_dispatcher=match_dispatcher,
        clock=lambda: NOW,
    )


def test_selected_ids_are_durable_and_idempotent(
    auth_client, session, job_dispatcher, match_dispatcher
):
    discovery, candidates = seed(session, 901, 902)
    key = str(uuid4())
    response = submit_batch(auth_client, discovery, candidates[:1], key=key)
    assert response.status_code == 202
    identifier = response.json()["id"]
    assert (
        submit_batch(auth_client, discovery, candidates[:1], key=key).json()["id"]
        == identifier
    )
    assert submit_batch(auth_client, discovery, candidates, key=key).status_code == 409
    service(session, job_dispatcher, match_dispatcher).execute(UUID(identifier))
    jobs = session.scalars(select(AnalysisJob)).all()
    assert [j.canonical_target_id for j in jobs] == ["UC0000000000000000000901"]
    assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 0
    detail = auth_client.get(
        f"/api/v1/discover/{discovery.id}/analysis-batches/{identifier}"
    ).json()
    assert detail["items"][0]["analysis_job_id"] == str(jobs[0].id)
    assert (
        len(
            auth_client.get(f"/api/v1/discover/{discovery.id}/analysis-batches").json()[
                "items"
            ]
        )
        == 1
    )


def test_reject_foreign_or_empty_selection(auth_client, session):
    discovery, candidates = seed(session, 903)
    other, foreign = seed(session, 904)
    assert submit_batch(auth_client, discovery, foreign).status_code == 422
    assert submit_batch(auth_client, discovery, []).status_code == 422


def test_reuses_usable_profile_and_joins_running_job(
    auth_client, session, job_dispatcher, match_dispatcher
):
    from app.db.models.enums import TargetType, JobMode, JobStatus

    discovery, candidates = seed(session, 905, 906)
    creator = _creator(905)
    running = AnalysisJob(
        target_type=TargetType.CREATOR,
        mode=JobMode.CREATE,
        canonical_target_id=candidates[1].platform_account_id,
        canonical_url=candidates[1].metadata_snapshot["canonical_url"],
        status=JobStatus.RUNNING,
        created_at=NOW,
        started_at=NOW,
        stage="fetching_data",
        total_units=1,
    )
    session.add_all([creator, running])
    session.flush()
    response = submit_batch(auth_client, discovery, candidates)
    assert response.status_code == 202
    service(session, job_dispatcher, match_dispatcher).execute(
        UUID(response.json()["id"])
    )
    detail = auth_client.get(
        f'/api/v1/discover/{discovery.id}/analysis-batches/{response.json()["id"]}'
    ).json()
    items = {i["candidate_id"]: i for i in detail["items"]}
    assert items[str(candidates[0].id)]["profile_id"] == str(creator.id)
    assert items[str(candidates[0].id)]["status"] == "succeeded"
    assert items[str(candidates[0].id)]["reused"] is True
    assert items[str(candidates[1].id)]["analysis_job_id"] == str(running.id)
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1


@pytest.mark.parametrize("invalid", ["stale", "seed", "brief"])
def test_unusable_existing_profile_gets_normal_reanalysis(
    auth_client, session, job_dispatcher, match_dispatcher, invalid
):
    from app.db.models.enums import JobMode

    discovery, candidates = seed(session, 950)
    creator = _creator(950)
    if invalid == "stale":
        creator.last_analyzed_at = NOW - timedelta(days=31)
    elif invalid == "seed":
        creator.source_status = {"seed": "incomplete"}
    else:
        creator.brief = {}
    session.add(creator)
    session.flush()
    response = submit_batch(auth_client, discovery, candidates)
    assert response.status_code == 202
    service(session, job_dispatcher, match_dispatcher).execute(
        UUID(response.json()["id"])
    )
    job = session.scalar(select(AnalysisJob))
    assert job.mode is JobMode.REANALYZE
    assert job.canonical_target_id == candidates[0].platform_account_id


def test_duplicate_selection_and_parallel_batch_join_one_job(
    auth_client, session, job_dispatcher, match_dispatcher
):
    discovery, candidates = seed(session, 951)
    key = str(uuid4())
    first = submit_batch(auth_client, discovery, candidates + candidates, key=key)
    assert first.status_code == 202
    assert len(first.json()["items"]) == 1
    assert (
        submit_batch(auth_client, discovery, candidates, key=key).json()["id"]
        == first.json()["id"]
    )
    second = submit_batch(auth_client, discovery, candidates)
    coordinator = service(session, job_dispatcher, match_dispatcher)
    coordinator.execute(UUID(first.json()["id"]))
    coordinator.execute(UUID(second.json()["id"]))
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1
    assert len(job_dispatcher.calls) == 1


def test_batch_sweep_is_bounded_and_recovers_broker_failure(auth_client, session):
    from app.db.models.discover_batch import DiscoverAnalysisBatch
    from app.workers.discover_batch_tasks import sweep_discover_batches

    discovery, candidates = seed(session, 952)
    session.add_all(
        [
            DiscoverAnalysisBatch(
                discover_id=discovery.id,
                idempotency_key=str(uuid4()),
                request_hash="b" * 64,
                mode="analyze",
            )
            for _ in range(21)
        ]
    )
    session.flush()

    @contextmanager
    def sessions():
        yield session

    def unavailable(identifier):
        raise RuntimeError("broker offline")

    assert (
        sweep_discover_batches(
            session_factory=sessions, dispatch=unavailable, clock=lambda: NOW
        )
        == 20
    )
    recovered = []
    assert (
        sweep_discover_batches(
            session_factory=sessions, dispatch=recovered.append, clock=lambda: NOW
        )
        == 1
    )
    assert (
        sweep_discover_batches(
            session_factory=sessions, dispatch=recovered.append, clock=lambda: NOW
        )
        == 0
    )
    assert (
        sweep_discover_batches(
            session_factory=sessions,
            dispatch=recovered.append,
            clock=lambda: NOW + timedelta(minutes=3),
        )
        == 20
    )
    assert len(set(recovered)) == 21
