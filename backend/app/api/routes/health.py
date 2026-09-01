from collections.abc import Callable

from fastapi import APIRouter, Response, status
from redis import Redis
from sqlalchemy import create_engine, text

from app.core.config import Settings, get_settings


class ReadinessProbe:
    def __init__(
        self,
        database_check: Callable[[], bool],
        redis_check: Callable[[], bool],
    ) -> None:
        self._database_check = database_check
        self._redis_check = redis_check

    def is_ready(self) -> bool:
        return self._run(self._database_check) and self._run(self._redis_check)

    @staticmethod
    def _run(check: Callable[[], bool]) -> bool:
        try:
            return check()
        except Exception:
            return False


def _check_database(settings: Settings) -> bool:
    engine = create_engine(
        settings.database_url,
        connect_args={"connect_timeout": 1},
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()
    return True


def _check_redis(settings: Settings) -> bool:
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        return bool(client.ping())
    finally:
        client.close()


def default_readiness_probe() -> ReadinessProbe:
    settings = get_settings()
    return ReadinessProbe(
        database_check=lambda: _check_database(settings),
        redis_check=lambda: _check_redis(settings),
    )


def create_router(readiness_probe: ReadinessProbe | None = None) -> APIRouter:
    probe = readiness_probe or default_readiness_probe()
    router = APIRouter(prefix="/health", tags=["health"])

    @router.get("/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/ready")
    def ready(response: Response) -> dict[str, str]:
        if probe.is_ready():
            return {"status": "ok"}
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}

    return router

router = create_router()
