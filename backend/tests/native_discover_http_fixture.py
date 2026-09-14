"""Dedicated loopback acceptance: real API/DB/worker entry points, simulated upstreams.

The explicit step endpoint substitutes for broker delivery only. It never resets a
database, contacts providers, reads real secrets, or permits SMTP routes.
"""
import os
from sqlalchemy.engine import make_url


def validate_database(raw):
    url = make_url(raw)
    if (url.drivername != "postgresql+psycopg" or url.host != "postgres-test"
            or url.database != "find_me_gamer_discover_http_acceptance"):
        raise ValueError("Use the dedicated Discover acceptance database")


def create_fixture_app():
    validate_database(os.environ["DATABASE_URL"])
    from contextlib import contextmanager
    from datetime import UTC, datetime, timedelta
    from uuid import UUID
    from alembic import command
    from alembic.config import Config
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from sqlalchemy import select, func
    from sqlalchemy.orm import sessionmaker
    from tests.conftest import (
        WORKSPACE_ACCESS_KEY, FakeRateLimitCounter, FakeJobDispatcher,
        FakeMatchDispatcher, FakeSMTPGateway, FakeSMTPRateLimiter,
        FakeOutreachBatchDispatcher, FakeConnectionProbe,
    )
    from app.core.database import engine
    from app.core.crypto import SecretCipher
    from app.core.rate_limit import FixedWindowRateLimiter
    from app.core.security import hash_workspace_key
    from app.main import create_app
    from app.db.models.profiles import CreatorProfile
    from app.db.models.settings import ServiceSecret
    from app.db.models.jobs import AnalysisJob
    from app.db.models.discover import DiscoverJob
    from app.db.models.discover_batch import DiscoverAnalysisBatch
    from app.db.models.match import MatchTask, MatchCandidateInput
    from app.db.models.enums import TargetType, JobStatus, JobMode
    from app.discovery.service import DiscoverService
    from app.discovery.batches import DiscoverBatchService
    from app.discovery.planning import HomepageCandidate
    from app.workers import analysis_tasks, discover_tasks, discover_batch_tasks, match_tasks
    from app.api.routes import discover as discover_routes
    from tests.integration.test_match_input_lock import _creator
    from tests.integration.test_creator_analysis_commit import _pipeline as creator_pipeline
    from tests.integration.test_game_analysis_commit import Steam, Artifacts, AI
    from app.analysis.game_pipeline import GameAnalysisPipeline
    from app.analysis.service import GameAnalysisService
    from tests.integration.test_x_creator_analysis import pipeline as x_pipeline
    from tests.unit.analysis.test_creator_pipeline import _source
    from tests.unit.analysis.test_prompts import sample_game_source
    from app.integrations.errors import PermanentIntegrationError

    command.upgrade(Config("alembic.ini"), "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    old_id, reused_id, seed_id = [UUID(int=700000 + n) for n in range(3)]
    now = lambda: datetime.now(UTC)
    with factory.begin() as session:
        for identifier, number in [(old_id, 7000), (reused_id, 7001), (seed_id, 7002)]:
            if session.get(CreatorProfile, identifier) is None:
                creator = _creator(number, analyzed_at=now())
                creator.id = identifier
                creator.next_analysis_at = now() + timedelta(days=14)
                creator.manual_overrides = {"facts.title": "Preserved manual title"}
                if identifier == seed_id:
                    creator.brief = {}
                    creator.source_status = {"seed": "incomplete"}
                session.add(creator)
        for platform in ("youtube", "x"):
            if session.scalar(select(ServiceSecret).where(ServiceSecret.service == platform)) is None:
                session.add(ServiceSecret(service=platform, ciphertext=b"synthetic", nonce=b"synthetic"))

    jobs, matches, smtp = FakeJobDispatcher(), FakeMatchDispatcher(), FakeSMTPGateway()
    app = create_app(
        workspace_key_hash=hash_workspace_key(WORKSPACE_ACCESS_KEY),
        secret_cipher=SecretCipher(bytes(range(32))),
        rate_limiter=FixedWindowRateLimiter(counter=FakeRateLimitCounter(), limit=10000,
                                           window_seconds=60, clock=lambda: 0.0),
        job_session_factory=factory, job_dispatcher=jobs, match_dispatcher=matches,
        connection_probe=FakeConnectionProbe(), smtp_gateway=smtp,
        smtp_rate_limiter=FakeSMTPRateLimiter(),
        outreach_batch_dispatcher=FakeOutreachBatchDispatcher(),
    )
    discover_routes.SteamGateway.fetch_game = lambda self, app_id: sample_game_source()

    class Provider:
        def __init__(self, platform):
            self.platform = platform

        def search(self, queries, conditions, *, limit):
            rows = [(7001, "Reused"), (7003, "Joined"), (7004, "Failure"), (7005, "Unselected")]
            if self.platform == "x":
                yield [HomepageCandidate(platform="x", platform_account_id="12345",
                    display_name="X selected", canonical_url="https://x.com/i/user/12345")]
            else:
                yield [HomepageCandidate(platform="youtube", platform_account_id=f"UC{n:022d}",
                    display_name=name, canonical_url=f"https://www.youtube.com/channel/UC{n:022d}")
                    for n, name in rows]

    @contextmanager
    def providers(platform):
        yield Provider(platform)

    def discovery():
        return DiscoverService(session_factory=factory, provider_factory=providers, analysis_dispatcher=jobs)

    def batch_service():
        return DiscoverBatchService(session_factory=factory, analysis_dispatcher=jobs, match_dispatcher=matches)

    class YouTube:
        def fetch_creator(self, channel_id, video_limit=50):
            if channel_id == f"UC{7004:022d}":
                raise PermanentIntegrationError("youtube_channel_not_found")
            source = _source()
            return source.model_copy(update={"channel_id": channel_id,
                "canonical_url": "https://www.youtube.com/channel/" + channel_id,
                "videos": tuple(v.model_copy(update={"channel_id": channel_id}) for v in source.videos)})

    @contextmanager
    def pipelines(target_type):
        if target_type == TargetType.GAME:
            # Real GameAnalysisPipeline, persisted ordinary AnalysisJob; fake Steam/model/artifacts.
            yield GameAnalysisPipeline(service=GameAnalysisService(session_factory=factory),
                steam=Steam(), artifacts=Artifacts(), deepseek=AI())
        else:
            yield creator_pipeline(factory, youtube=YouTube(), clock=now)

    @contextmanager
    def xpipelines(target_type):
        yield x_pipeline(factory)

    discover_tasks.get_discover_service = discovery
    discover_batch_tasks.get_discover_batch_service = batch_service

    def observe():
        with factory() as session:
            count = lambda model: session.scalar(select(func.count()).select_from(model))
            locked = set(session.scalars(select(MatchCandidateInput.creator_id)))
            x = session.scalar(select(CreatorProfile).where(CreatorProfile.platform == "x"))
            joined = session.scalar(select(AnalysisJob).where(AnalysisJob.canonical_target_id == f"UC{7003:022d}"))
            return {
                "analysis_count": count(AnalysisJob), "creator_count": count(CreatorProfile),
                "match_count": count(MatchTask), "locked_count": len(locked),
                "old_creator_matched": old_id in locked, "fact_only_excluded": seed_id not in locked,
                "manual_preserved": session.get(CreatorProfile, old_id).manual_overrides == {"facts.title": "Preserved manual title"},
                "joined_job_preserved": joined is not None and joined.id == UUID(int=700003),
                "unselected_absent": session.scalar(select(CreatorProfile.id).where(
                    CreatorProfile.platform_account_id == f"UC{7005:022d}")) is None,
                "match_done": all(str(row.status.value) == "succeeded" for row in session.scalars(select(MatchTask))),
                "x_profile_id": str(x.id) if x else None, "smtp_count": len(smtp.sends),
            }

    def run_match(identifier):
        from app.matching.screening import ScreeningService
        from app.matching.pairwise import PairwiseService
        from app.matching.ranking import RankingService
        from app.schemas.ai_match import ScreeningOutput, PairwiseMatchBrief
        from tests.helpers.match_capacity import synthetic_pairwise_brief
        from tests.integration.test_match_capacity import LocalGraphDispatcher, _ranking_output
        with factory() as session:
            ids = list(session.scalars(select(MatchCandidateInput.creator_id).where(
                MatchCandidateInput.match_task_id == identifier)))

        class AI:
            def complete_structured(self, model, messages, schema):
                assert model == "deepseek-flash"
                if schema is ScreeningOutput:
                    return schema.model_validate({"english_language_check": True, "selected": [
                        {"creator_id": i, "screening_reason": "Synthetic accepted fit.",
                         "evidence": ["Supplied synthetic profile."]} for i in ids]})
                if schema is PairwiseMatchBrief:
                    payload = "\n".join(m.content for m in messages)
                    return synthetic_pairwise_brief(next(i for i in ids if str(i) in payload))
                return _ranking_output(ids)

        ai, dispatcher = AI(), LocalGraphDispatcher()
        @contextmanager
        def pairwise():
            yield PairwiseService(session_factory=factory, ai=ai)
        @contextmanager
        def ranking():
            yield RankingService(session_factory=factory, ai=ai)
        executor = match_tasks.MatchTaskExecutor(
            screening=ScreeningService(session_factory=factory, ai=ai),
            pairwise_factory=pairwise, ranking_factory=ranking,
            store=match_tasks.MatchTaskStore(session_factory=factory), dispatcher=dispatcher)
        match_tasks.get_match_executor = lambda: executor
        match_tasks.start_match_task.run(str(identifier))
        for task_id, creator_id in dispatcher.pairs:
            match_tasks.run_pairwise_match.run(str(task_id), str(creator_id))
        for task_id in dispatcher.advances:
            match_tasks.advance_match_task.run(str(task_id))
        for task_id in dispatcher.rankings:
            match_tasks.finalize_match_ranking.run(str(task_id))

    @app.post("/fixture/step/{phase}")
    def step(phase: str):
        if phase == "join":
            with factory.begin() as session:
                if session.get(AnalysisJob, UUID(int=700003)) is None:
                    session.add(AnalysisJob(id=UUID(int=700003), target_type=TargetType.CREATOR,
                        canonical_target_id=f"UC{7003:022d}", canonical_url=f"https://www.youtube.com/channel/UC{7003:022d}",
                        mode=JobMode.CREATE, status=JobStatus.QUEUED))
        elif phase in {"discover", "batch", "analysis", "match"}:
            model = {"discover": DiscoverJob, "batch": DiscoverAnalysisBatch,
                     "analysis": AnalysisJob, "match": MatchTask}[phase]
            with factory() as session:
                identifiers = list(session.scalars(select(model.id)))
            for identifier in identifiers:
                if phase == "discover":
                    discover_tasks.run_discover.run(str(identifier))
                elif phase == "batch":
                    discover_batch_tasks.run_discover_batch.run(str(identifier))
                elif phase == "analysis":
                    with factory() as session:
                        job = session.get(AnalysisJob, identifier)
                        use_x = job.canonical_target_id == "x:12345"
                    analysis_tasks.get_analysis_executor = lambda: analysis_tasks.AnalysisJobExecutor(
                        session_factory=factory, pipeline_factory=xpipelines if use_x else pipelines)
                    analysis_tasks.run_analysis_job.run(str(identifier))
                else:
                    run_match(identifier)
        return observe()

    @app.middleware("http")
    async def restricted_routes(request: Request, call_next):
        path = request.url.path
        permitted = path.startswith("/fixture/step/") or path.startswith("/api/v1/discover") or (
            request.method == "GET" and (path == "/api/v1/session" or path.startswith("/api/v1/profiles/")
                                         or path.startswith("/api/v1/matches/"))) or (
            request.method == "PATCH" and path.startswith("/api/v1/profiles/")
            and (path.endswith("/edit") or path.endswith("/manual")))
        if not permitted or request.headers.get("authorization") != "Bearer " + WORKSPACE_ACCESS_KEY:
            return JSONResponse(status_code=403, content={"fixture": "route disabled"})
        return await call_next(request)

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_fixture_app(), host="0.0.0.0", port=8000, access_log=False)
