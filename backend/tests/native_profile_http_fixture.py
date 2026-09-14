"""Opt-in local HTTP fixture. Never reads credentials or dispatches real work.

Run inside the fmg-native-edit Compose network, publishing only host loopback.
The dedicated database must be created explicitly; this module never resets it.
"""
import os

from sqlalchemy.engine import make_url


def validate_database(raw: str) -> None:
    url = make_url(raw)
    if (url.drivername != "postgresql+psycopg" or url.host != "postgres-test"
            or url.database != "find_me_gamer_native_http_acceptance"):
        raise ValueError("Use the dedicated acceptance database on postgres-test")


def create_fixture_app():
    validate_database(os.environ["DATABASE_URL"])
    # conftest uses a temporary synthetic master key and an inert workspace key.
    from tests.conftest import (
        WORKSPACE_ACCESS_KEY, FakeRateLimitCounter, FakeJobDispatcher,
        FakeMatchDispatcher, FakeSMTPGateway, FakeSMTPRateLimiter,
        FakeOutreachBatchDispatcher, FakeConnectionProbe,
    )
    from alembic import command
    from alembic.config import Config
    from fastapi.responses import JSONResponse
    from sqlalchemy.orm import sessionmaker
    from uuid import UUID
    from datetime import UTC, datetime, timedelta
    from app.core.database import engine
    from app.core.crypto import SecretCipher
    from app.core.rate_limit import FixedWindowRateLimiter
    from app.core.security import hash_workspace_key
    from app.main import create_app
    from app.db.models.profiles import GameProfile, CreatorProfile
    from tests.integration.test_match_input_lock import _game, _creator

    command.upgrade(Config("alembic.ini"), "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        game_id = UUID("a4000000-0000-4000-8000-000000000001")
        creator_id = UUID("a4000000-0000-4000-8000-000000000002")
        if session.get(GameProfile, game_id) is None:
            game = _game()
            game.id = game_id
            game.steam_app_id = "400040004"
            session.add(game)
        if session.get(CreatorProfile, creator_id) is None:
            creator = _creator(400040004)
            creator.id = creator_id
            creator.last_analyzed_at = datetime.now(UTC)
            creator.next_analysis_at = datetime.now(UTC) + timedelta(days=14)
            session.add(creator)
    app = create_app(
        workspace_key_hash=hash_workspace_key(WORKSPACE_ACCESS_KEY),
        secret_cipher=SecretCipher(bytes(range(32))),
        rate_limiter=FixedWindowRateLimiter(counter=FakeRateLimitCounter(), limit=10000,
                                           window_seconds=60, clock=lambda: 0.0),
        job_session_factory=factory, job_dispatcher=FakeJobDispatcher(),
        match_dispatcher=FakeMatchDispatcher(), connection_probe=FakeConnectionProbe(),
        smtp_gateway=FakeSMTPGateway(), smtp_rate_limiter=FakeSMTPRateLimiter(),
        outreach_batch_dispatcher=FakeOutreachBatchDispatcher(),
    )

    @app.middleware("http")
    async def fixture_routes_only(request, call_next):
        path = request.url.path
        allowed = (request.method == "GET" and (
            path == "/api/v1/session" or path.startswith("/api/v1/profiles/")
            or path.startswith("/api/v1/matches/"))) or (
            request.method == "PATCH" and path.startswith("/api/v1/profiles/")
            and (path.endswith("/edit") or path.endswith("/manual"))) or (
            request.method == "POST" and path == "/api/v1/matches")
        if not allowed:
            return JSONResponse(status_code=403, content={"fixture": "route disabled"})
        return await call_next(request)

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_fixture_app(), host="0.0.0.0", port=8000, access_log=False)
