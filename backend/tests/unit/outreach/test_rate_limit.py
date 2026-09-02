import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from uuid import uuid4

import pytest
from redis import Redis

from app.outreach.rate_limit import SMTPRateLimitError, SMTPRateLimiter


class FakeRedis:
    def __init__(self, result: int = 0, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, int, str, int]] = []

    def eval(self, script: str, key_count: int, key: str, rate: int) -> int:
        self.calls.append((script, key_count, key, rate))
        if self.error is not None:
            raise self.error
        return self.result


def test_limiter_uses_one_atomic_lua_operation_and_hashes_workspace() -> None:
    redis = FakeRedis()

    delay = SMTPRateLimiter(redis).acquire("company-workspace", 10)

    assert delay == 0.0
    assert len(redis.calls) == 1
    script, key_count, key, rate = redis.calls[0]
    assert "redis.call('TIME')" in script
    assert key_count == 1
    assert key.startswith("smtp-rate-limit:")
    assert "company-workspace" not in key
    assert rate == 10


def test_limiter_returns_non_negative_delay_seconds() -> None:
    redis = FakeRedis(result=1_250)

    delay = SMTPRateLimiter(redis).acquire("workspace", 5)

    assert delay == 1.25


@pytest.mark.parametrize("rate", [0, 61, -1, True])
def test_limiter_rejects_rates_outside_one_to_sixty(rate: int) -> None:
    redis = FakeRedis()

    with pytest.raises(ValueError, match="between 1 and 60"):
        SMTPRateLimiter(redis).acquire("workspace", rate)

    assert redis.calls == []


def test_redis_failure_is_a_safe_retryable_limiter_error() -> None:
    redis = FakeRedis(error=RuntimeError("redis detail must not escape"))

    with pytest.raises(SMTPRateLimitError) as caught:
        SMTPRateLimiter(redis).acquire("workspace", 10)

    assert str(caught.value) == "SMTP rate limiting is temporarily unavailable."
    assert "redis" not in str(caught.value).casefold()


def test_real_redis_atomically_limits_a_cross_process_burst() -> None:
    redis_url = os.environ.get("REAL_REDIS_URL")
    if not redis_url:
        pytest.skip("REAL_REDIS_URL enables the isolated real-Redis test")
    client = Redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
    workspace = f"smtp-limiter-test-{uuid4()}"
    key = f"smtp-rate-limit:{sha256(workspace.encode()).hexdigest()}"
    limiter = SMTPRateLimiter(client)
    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            delays = list(
                executor.map(lambda _: limiter.acquire(workspace, 5), range(12))
            )

        assert sum(delay == 0 for delay in delays) == 5
        assert all(delay > 0 for delay in delays if delay != 0)
        assert client.pttl(key) > 0
    finally:
        client.delete(key)
        client.close()
