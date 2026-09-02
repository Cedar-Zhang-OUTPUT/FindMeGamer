"""Cross-process SMTP token-bucket rate limiting backed by Redis."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol


class RedisScriptClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


class SMTPRateLimitError(RuntimeError):
    """The shared SMTP limiter is temporarily unavailable."""


class SMTPRateLimiter:
    _acquire_script = """
    local now_parts = redis.call('TIME')
    local now_ms = (tonumber(now_parts[1]) * 1000) + math.floor(tonumber(now_parts[2]) / 1000)
    local rate = tonumber(ARGV[1])
    local values = redis.call('HMGET', KEYS[1], 'tokens', 'updated_ms')
    local tokens = tonumber(values[1]) or rate
    local updated_ms = tonumber(values[2]) or now_ms
    local elapsed_ms = math.max(0, now_ms - updated_ms)
    tokens = math.min(rate, tokens + (elapsed_ms * rate / 60000))
    local delay_ms = 0
    if tokens >= 1 then
        tokens = tokens - 1
    else
        delay_ms = math.ceil((1 - tokens) * 60000 / rate)
    end
    redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_ms', now_ms)
    redis.call('PEXPIRE', KEYS[1], 120000)
    return delay_ms
    """

    def __init__(self, client: RedisScriptClient) -> None:
        self._client = client

    def acquire(self, workspace: str, per_minute: int) -> float:
        if isinstance(per_minute, bool) or not 1 <= per_minute <= 60:
            raise ValueError("SMTP rate must be between 1 and 60.")
        digest = sha256(workspace.encode("utf-8")).hexdigest()
        key = f"smtp-rate-limit:{digest}"
        try:
            delay_ms = int(self._client.eval(self._acquire_script, 1, key, per_minute))
        except Exception:
            raise SMTPRateLimitError(
                "SMTP rate limiting is temporarily unavailable."
            ) from None
        return max(0.0, delay_ms / 1000.0)


__all__ = ["SMTPRateLimitError", "SMTPRateLimiter"]
