from uuid import uuid4
from uuid import UUID
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, func

from app.db.models.profiles import CreatorProfile


def test_discover_creates_durable_idempotent_request_without_profiles(
    auth_client, session, monkeypatch
):
    # Losing the durable request or inserting profiles during discovery must fail.
    from app.db.models.settings import ServiceSecret

    session.add(
        ServiceSecret(service="youtube", ciphertext=b"configured", nonce=b"configured")
    )
    session.flush()
    key = str(uuid4())
    payload = {
        "steam_url": "https://store.steampowered.com/app/1245620/",
        "conditions": {"platforms": ["youtube"]},
    }
    response = auth_client.post(
        "/api/v1/discover", headers={"Idempotency-Key": key}, json=payload
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["stage"] == "preparing_game"
    replay = auth_client.post(
        "/api/v1/discover", headers={"Idempotency-Key": key}, json=payload
    )
    assert replay.json()["id"] == response.json()["id"]
    payload["conditions"]["keywords"] = "changed"
    assert (
        auth_client.post(
            "/api/v1/discover", headers={"Idempotency-Key": key}, json=payload
        ).status_code
        == 409
    )
    detail = auth_client.get("/api/v1/discover/" + response.json()["id"]).json()
    assert detail["id"] == response.json()["id"]
    summary = auth_client.get("/api/v1/discover").json()["items"][0]
    assert summary["id"] == detail["id"]
    assert summary["candidate_count"] == 0
    assert summary["issue_count"] == 0
    assert "candidates" not in summary
    assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"game_id": str(uuid4()), "steam_url": "https://store.steampowered.com/app/1"},
        {
            "steam_url": "https://store.steampowered.com/app/1",
            "conditions": {"platforms": []},
        },
        {
            "steam_url": "https://store.steampowered.com/app/1",
            "conditions": {"platforms": ["twitch"]},
        },
        {
            "steam_url": "https://store.steampowered.com/app/1",
            "conditions": {"min_followers": 10, "max_followers": 1},
        },
    ],
)
def test_discover_invalid_request(auth_client, payload):
    assert (
        auth_client.post(
            "/api/v1/discover", headers={"Idempotency-Key": str(uuid4())}, json=payload
        ).status_code
        == 422
    )


@pytest.fixture
def discover_factory(session):
    @contextmanager
    def factory():
        yield session

    return factory


def submit(auth_client, session, platforms=None):
    from app.db.models.settings import ServiceSecret

    for platform in platforms or ["youtube"]:
        if (
            session.scalar(
                select(ServiceSecret).where(ServiceSecret.service == platform)
            )
            is None
        ):
            session.add(
                ServiceSecret(
                    service=platform, ciphertext=b"configured", nonce=b"configured"
                )
            )
    session.flush()
    response = auth_client.post(
        "/api/v1/discover",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "steam_url": "https://store.steampowered.com/app/1245620",
            "conditions": {
                "platforms": platforms or ["youtube"],
                "keywords": "speedrun",
            },
        },
    )
    assert response.status_code == 202
    return UUID(response.json()["id"])


def complete_game(discover_factory, job_id, monkeypatch, *, fails=False):
    from app.analysis.game_pipeline import GameAnalysisPipeline
    from app.analysis.service import GameAnalysisService
    from app.integrations.errors import PermanentIntegrationError
    from app.workers import analysis_tasks
    from tests.integration.test_game_analysis_commit import Steam, Artifacts, AI

    @contextmanager
    def pipeline_factory(target_type):
        yield GameAnalysisPipeline(
            service=GameAnalysisService(session_factory=discover_factory),
            steam=Steam(
                failure=(
                    PermanentIntegrationError("steam_game_not_found") if fails else None
                )
            ),
            artifacts=Artifacts(),
            deepseek=AI(),
        )

    monkeypatch.setattr(
        analysis_tasks,
        "get_analysis_executor",
        lambda: analysis_tasks.AnalysisJobExecutor(
            session_factory=discover_factory, pipeline_factory=pipeline_factory
        ),
    )
    analysis_tasks.run_analysis_job.run(str(job_id))


def test_game_prerequisite_joins_and_resumes_through_worker(
    auth_client, session, discover_factory, job_dispatcher, monkeypatch
):
    from app.discovery.service import DiscoverService
    from app.discovery.planning import HomepageCandidate
    from app.db.models.discover import DiscoverJob
    from app.db.models.jobs import AnalysisJob
    from app.db.models.profiles import GameProfile
    from app.workers import discover_tasks

    class Provider:
        def search(self, queries, conditions, *, limit):
            assert any("speedrun" in q for q in queries)
            yield [
                HomepageCandidate(
                    platform="youtube",
                    platform_account_id="UCaaaaaaa",
                    display_name="Author",
                    canonical_url="https://www.youtube.com/channel/UCaaaaaaa",
                )
            ]

    @contextmanager
    def providers(platform):
        yield Provider()

    def service():
        return DiscoverService(
            session_factory=discover_factory,
            provider_factory=providers,
            analysis_dispatcher=job_dispatcher,
        )

    monkeypatch.setattr(discover_tasks, "get_discover_service", service)
    first, second = submit(auth_client, session), submit(auth_client, session)
    discover_tasks.run_discover.run(str(first))
    discover_tasks.run_discover.run(str(second))
    jobs = session.scalars(select(AnalysisJob)).all()
    assert len(jobs) == 1
    assert session.get(DiscoverJob, first).game_job_id == jobs[0].id
    assert session.get(DiscoverJob, second).game_job_id == jobs[0].id
    assert session.get(DiscoverJob, first).stage == "preparing_game"
    complete_game(discover_factory, jobs[0].id, monkeypatch)
    discover_tasks.run_discover.run(str(first))
    detail = auth_client.get(f"/api/v1/discover/{first}").json()
    assert detail["status"] == "done"
    assert len(detail["candidates"]) == 1
    assert not detail["candidates"][0]["in_library"]
    assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 0
    game = session.get(GameProfile, UUID(detail["game_id"]))
    game.manual_overrides = {"facts.name": "Manual Game", "brief.genres": ["Horror"]}
    session.commit()
    third = submit(auth_client, session)
    discover_tasks.run_discover.run(str(third))
    assert session.get(DiscoverJob, third).game_snapshot["name"] == "Manual Game"
    assert session.get(DiscoverJob, third).game_snapshot["brief"]["genres"][
        "values"
    ] == ["Horror"]
    assert session.get(DiscoverJob, first).game_snapshot["name"] != "Manual Game"
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1


def test_failed_prerequisite_blocks_and_targeted_retry(
    auth_client, session, discover_factory, job_dispatcher, monkeypatch
):
    from app.discovery.service import DiscoverService
    from app.db.models.discover import DiscoverJob

    def no_providers(platform):
        raise AssertionError("Failed game must not search")

    service = DiscoverService(
        session_factory=discover_factory,
        provider_factory=no_providers,
        analysis_dispatcher=job_dispatcher,
    )
    identifier = submit(auth_client, session)
    service.execute(identifier)
    prerequisite = session.get(DiscoverJob, identifier).game_job_id
    complete_game(discover_factory, prerequisite, monkeypatch, fails=True)
    service.execute(identifier)
    assert session.get(DiscoverJob, identifier).status == "failed"
    auth_client.post(f"/api/v1/discover/{identifier}/retry")
    auth_client.post(f"/api/v1/discover/{identifier}/retry")
    service.execute(identifier)
    assert session.get(DiscoverJob, identifier).game_job_id != prerequisite


def test_partial_pages_survive_retry_cap_and_expired_claim(
    auth_client, session, discover_factory, job_dispatcher, monkeypatch
):
    from app.discovery.service import DiscoverService
    from app.discovery.planning import HomepageCandidate
    from app.db.models.discover import DiscoverJob
    from app.integrations.errors import PermanentIntegrationError

    state = {"fail": True, "youtube_runs": 0}

    class Provider:
        def __init__(self, platform):
            self.platform = platform

        def search(self, queries, conditions, *, limit):
            if self.platform == "youtube":
                state["youtube_runs"] += 1
                yield [
                    HomepageCandidate(
                        platform="youtube",
                        platform_account_id=f"UCtest{i:04}",
                        display_name="Author",
                        canonical_url=f"https://www.youtube.com/channel/UCtest{i:04}",
                    )
                    for i in range(60)
                ]
            else:
                yield [
                    HomepageCandidate(
                        platform="x",
                        platform_account_id=str(i),
                        display_name="Author",
                        canonical_url=f"https://x.com/i/user/{i}",
                    )
                    for i in range(1, 11)
                ]
                if state["fail"]:
                    raise PermanentIntegrationError("x_payment_required")
                yield [
                    HomepageCandidate(
                        platform="x",
                        platform_account_id=str(i),
                        display_name="Author",
                        canonical_url=f"https://x.com/i/user/{i}",
                    )
                    for i in range(1, 100)
                ]

    @contextmanager
    def providers(platform):
        yield Provider(platform)

    service = DiscoverService(
        session_factory=discover_factory,
        provider_factory=providers,
        analysis_dispatcher=job_dispatcher,
    )
    identifier = submit(auth_client, session, ["youtube", "x"])
    service.execute(identifier)
    complete_game(
        discover_factory, session.get(DiscoverJob, identifier).game_job_id, monkeypatch
    )
    service.execute(identifier)
    response = auth_client.get(f"/api/v1/discover/{identifier}").json()
    assert response["status"] == "partial"
    assert len(response["candidates"]) == 30
    ids = {c["id"] for c in response["candidates"]}
    assert response["issues"][0]["code"] == "x_payment_required"
    state["fail"] = False
    auth_client.post(f"/api/v1/discover/{identifier}/retry")
    row = session.get(DiscoverJob, identifier)
    row.lease_token = uuid4()
    row.lease_until = datetime.now(UTC) + timedelta(minutes=1)
    session.commit()
    service.execute(identifier)
    assert row.status == "queued"
    row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    # A new coordinator instance resumes the persisted partial request.
    DiscoverService(
        session_factory=discover_factory,
        provider_factory=providers,
        analysis_dispatcher=job_dispatcher,
    ).execute(identifier)
    response = auth_client.get(f"/api/v1/discover/{identifier}").json()
    assert response["status"] == "done"
    assert len(response["candidates"]) == 40
    assert sum(c["platform"] == "youtube" for c in response["candidates"]) == 20
    assert sum(c["platform"] == "x" for c in response["candidates"]) == 20
    assert ids <= {c["id"] for c in response["candidates"]}
    assert state["youtube_runs"] == 1
    service.execute(identifier)
    assert (
        len(auth_client.get(f"/api/v1/discover/{identifier}").json()["candidates"])
        == 40
    )


@pytest.mark.parametrize("platforms", [["x", "youtube"], ["youtube", "x"], ["youtube"]])
def test_platform_limits_exclude_library_and_fill_from_later_pages(
    auth_client, session, discover_factory, job_dispatcher, monkeypatch, platforms
):
    # A shared cap, counting Library hits, or stopping at the first page loses
    # new candidates. Use real persistence/API and only fake the external search.
    from app.discovery.service import DiscoverService
    from app.discovery.planning import HomepageCandidate
    from app.db.models.discover import DiscoverJob

    def candidate(platform, i):
        identity = f"UCtest{i:04}" if platform == "youtube" else str(i + 1)
        url = (
            f"https://www.youtube.com/channel/{identity}"
            if platform == "youtube"
            else f"https://x.com/i/user/{identity}"
        )
        return HomepageCandidate(
            platform=platform, platform_account_id=identity,
            display_name=f"Author {i}", canonical_url=url,
        )

    for platform in platforms:
        for i in range(25):
            c = candidate(platform, i)
            session.add(CreatorProfile(
                platform=platform, platform_account_id=c.platform_account_id,
                canonical_url=c.canonical_url, sort_name=c.display_name,
            ))
    session.commit()

    class Provider:
        def __init__(self, platform):
            self.platform = platform

        def search(self, queries, conditions, *, limit):
            yield [candidate(self.platform, i) for i in range(25)]
            # Repeated Library hits and repeated new accounts must not use slots.
            yield [candidate(self.platform, i) for i in range(20, 31)] * 2
            yield [candidate(self.platform, i) for i in range(30, 70)]

    @contextmanager
    def providers(platform):
        yield Provider(platform)

    service = DiscoverService(
        session_factory=discover_factory, provider_factory=providers,
        analysis_dispatcher=job_dispatcher,
    )
    identifier = submit(auth_client, session, platforms)
    service.execute(identifier)
    complete_game(discover_factory, session.get(DiscoverJob, identifier).game_job_id, monkeypatch)
    service.execute(identifier)
    response = auth_client.get(f"/api/v1/discover/{identifier}").json()
    assert response["status"] == "done"
    assert response["issues"] == []
    for platform in platforms:
        results = [c for c in response["candidates"] if c["platform"] == platform]
        assert len(results) == 20
        assert {c["platform_account_id"] for c in results} == {
            candidate(platform, i).platform_account_id for i in range(25, 45)
        }
        assert all(not c["in_library"] for c in results)
    assert session.scalar(select(func.count()).select_from(CreatorProfile)) == 25 * len(platforms)


def test_sweep_recovers_uncertain_publication_without_duplicate_immediate_publish(
    auth_client, session, discover_factory
):
    from app.workers.discover_tasks import sweep_discover
    from app.db.models.discover import DiscoverJob

    identifier = submit(auth_client, session)
    now = datetime.now(UTC)

    def unavailable(identifier):
        raise RuntimeError("broker unavailable")

    assert (
        sweep_discover(
            session_factory=discover_factory, dispatch=unavailable, clock=lambda: now
        )
        == 1
    )
    assert session.get(DiscoverJob, identifier).status == "queued"
    assert (
        sweep_discover(
            session_factory=discover_factory, dispatch=unavailable, clock=lambda: now
        )
        == 0
    )
    delivered = []
    assert (
        sweep_discover(
            session_factory=discover_factory,
            dispatch=delivered.append,
            clock=lambda: now + timedelta(minutes=3),
        )
        == 1
    )
    assert delivered == [str(identifier)]


def test_resolve_game_uses_public_metadata_no_analysis(
    auth_client, session, monkeypatch
):
    from app.api.routes.discover import SteamGateway
    from app.db.models.jobs import AnalysisJob
    from tests.unit.analysis.test_prompts import sample_game_source

    monkeypatch.setattr(
        SteamGateway, "fetch_game", lambda self, app_id: sample_game_source()
    )
    response = auth_client.post(
        "/api/v1/discover/resolve-game",
        json={
            "steam_url": "https://store.steampowered.com/app/1245620/Elden_Ring/?x=1"
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == sample_game_source().name
    assert (
        response.json()["canonical_url"] == "https://store.steampowered.com/app/1245620"
    )
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 0
    assert (
        auth_client.post(
            "/api/v1/discover/resolve-game",
            json={"steam_url": "https://example.org/app/1"},
        ).status_code
        == 422
    )


def test_capabilities_and_unconfigured_platform_are_honest(auth_client):
    response = auth_client.get("/api/v1/discover/capabilities").json()
    assert all(not platform["available"] for platform in response["platforms"])
    assert {platform["platform"] for platform in response["platforms"]} == {
        "youtube",
        "x",
        "twitch",
        "instagram",
    }
    assert (
        auth_client.post(
            "/api/v1/discover",
            headers={"Idempotency-Key": str(uuid4())},
            json={"steam_url": "https://store.steampowered.com/app/1"},
        ).status_code
        == 422
    )


def test_joining_fresh_analysis_does_not_publish_it_twice(
    auth_client, session, discover_factory, job_dispatcher
):
    from app.analysis.targets import canonicalize_target
    from app.db.models.enums import TargetType, JobMode
    from app.repositories.jobs import JobsRepository
    from app.discovery.service import DiscoverService

    target = canonicalize_target(
        TargetType.GAME, "https://store.steampowered.com/app/1245620"
    )
    analysis = (
        JobsRepository(session)
        .create_or_reuse_job(target, mode=JobMode.CREATE, correlation_id=None)
        .job
    )
    session.commit()
    identifier = submit(auth_client, session)
    service = DiscoverService(
        session_factory=discover_factory,
        provider_factory=lambda platform: None,
        analysis_dispatcher=job_dispatcher,
    )
    service.execute(identifier)
    assert job_dispatcher.calls == []
    # A queued job with an uncertain old publication is recoverable, not abandoned.
    service = DiscoverService(
        session_factory=discover_factory,
        provider_factory=lambda platform: None,
        analysis_dispatcher=job_dispatcher,
        clock=lambda: datetime.now(UTC) + timedelta(minutes=3),
    )
    service.execute(identifier)
    assert job_dispatcher.calls == [analysis.id]
