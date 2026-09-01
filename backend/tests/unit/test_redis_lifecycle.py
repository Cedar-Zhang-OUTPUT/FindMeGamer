from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import hash_workspace_key
from app.main import create_app


class RecordingRedisClient:
    def __init__(self) -> None:
        self.close_calls = 0

    def eval(self, script: str, key_count: int, key: str, ttl: int) -> int:
        return 1

    def close(self) -> None:
        self.close_calls += 1


def test_owned_redis_client_uses_bounded_timeouts_and_closes_on_shutdown(
    monkeypatch,
) -> None:
    redis_client = RecordingRedisClient()
    construction: dict[str, object] = {}

    class RecordingRedis:
        @classmethod
        def from_url(cls, url: str, **options):
            construction["url"] = url
            construction["options"] = options
            return redis_client

    settings = Settings(
        _env_file=None,
        workspace_access_key_hash=hash_workspace_key("redis-lifecycle-test-key"),
        redis_url="redis://redis.internal:6379/4",
        redis_connect_timeout_seconds=0.25,
        redis_read_timeout_seconds=0.75,
    )
    monkeypatch.setattr("app.main.Redis", RecordingRedis)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    app = create_app()
    with TestClient(app):
        assert redis_client.close_calls == 0

    assert construction == {
        "url": "redis://redis.internal:6379/4",
        "options": {
            "socket_connect_timeout": 0.25,
            "socket_timeout": 0.75,
        },
    }
    assert redis_client.close_calls == 1
