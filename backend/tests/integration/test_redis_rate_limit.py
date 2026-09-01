import os
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis

from app.core.rate_limit import FixedWindowRateLimiter, RedisRateLimitCounter
from app.core.security import hash_workspace_key
from app.main import create_app


@pytest.fixture
def real_redis_url() -> str:
    url = os.environ.get("REAL_REDIS_URL")
    if not url:
        pytest.skip("REAL_REDIS_URL enables the isolated real-Redis test")
    return url


def test_real_redis_counter_atomically_increments_and_preserves_first_write_ttl(
    real_redis_url: str,
) -> None:
    client = Redis.from_url(
        real_redis_url,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    counter = RedisRateLimitCounter(client)
    key = f"test:rate-limit:{uuid4()}"
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            values = list(
                executor.map(lambda _: counter.increment(key, 10), range(12))
            )

        first_ttl = client.ttl(key)
        next_value = counter.increment(key, 10)
        second_ttl = client.ttl(key)

        assert sorted(values) == list(range(1, 13))
        assert next_value == 13
        assert 1 <= second_ttl <= first_ttl <= 10
    finally:
        client.delete(key)
        client.close()


def test_unreachable_redis_fails_within_bound_and_returns_safe_envelope() -> None:
    client = Redis.from_url(
        "redis://127.0.0.1:1/0",
        socket_connect_timeout=0.15,
        socket_timeout=0.15,
    )
    limiter = FixedWindowRateLimiter(
        counter=RedisRateLimitCounter(client),
        limit=10,
        window_seconds=60,
    )
    app = create_app(
        workspace_key_hash=hash_workspace_key("unreachable-redis-test-key"),
        rate_limiter=limiter,
    )
    started = monotonic()
    try:
        with TestClient(app) as test_client:
            response = test_client.get(
                "/api/v1/session",
                headers={"Authorization": "Bearer unreachable-redis-test-key"},
            )
    finally:
        client.close()
    elapsed = monotonic() - started

    assert elapsed < 2.0
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"
    assert response.json()["error"]["retryable"] is True
    assert response.json()["error"]["correlation_id"] == response.headers[
        "x-correlation-id"
    ]
    assert "redis" not in response.text.lower()
