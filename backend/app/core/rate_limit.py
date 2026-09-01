from collections.abc import Callable
from hashlib import sha256
from time import time
from typing import Protocol

from redis import Redis


class RateLimitCounter(Protocol):
    def increment(self, key: str, window_seconds: int) -> int: ...


class RateLimiter(Protocol):
    def allow(self, workspace_digest: str, client_address: str) -> bool: ...


class RedisRateLimitCounter:
    _increment_script = """
    local value = redis.call('INCR', KEYS[1])
    if value == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    return value
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    def increment(self, key: str, window_seconds: int) -> int:
        return int(self._client.eval(self._increment_script, 1, key, window_seconds))


class FixedWindowRateLimiter:
    def __init__(
        self,
        counter: RateLimitCounter,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time,
    ) -> None:
        self._counter = counter
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock

    def allow(self, workspace_digest: str, client_address: str) -> bool:
        window = int(self._clock()) // self._window_seconds
        client_digest = sha256(client_address.encode("utf-8")).hexdigest()
        counter_key = (
            f"rate-limit:workspace:{workspace_digest}:"
            f"client:{client_digest}:window:{window}"
        )
        count = self._counter.increment(counter_key, self._window_seconds)
        return count <= self._limit
