from app.core.rate_limit import FixedWindowRateLimiter
from app.core.security import (
    hash_workspace_key,
    workspace_key_digest,
    verify_workspace_key,
)


class RecordingCounter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.keys: list[str] = []

    def increment(self, key: str, window_seconds: int) -> int:
        self.keys.append(key)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


def test_workspace_key_round_trip_uses_argon2id() -> None:
    encoded = hash_workspace_key("demo-key")

    assert encoded.startswith("$argon2id$")
    assert verify_workspace_key("demo-key", encoded)
    assert not verify_workspace_key("wrong", encoded)


def test_workspace_key_verification_rejects_malformed_hash() -> None:
    assert not verify_workspace_key("demo-key", "not-an-argon2-hash")


def test_workspace_key_digest_is_deterministic_and_one_way() -> None:
    first = workspace_key_digest("demo-key")

    assert first == workspace_key_digest("demo-key")
    assert first != workspace_key_digest("different-key")
    assert "demo-key" not in first


def test_fixed_window_rate_limit_uses_only_secret_safe_counter_keys() -> None:
    counter = RecordingCounter()
    limiter = FixedWindowRateLimiter(
        counter=counter,
        limit=2,
        window_seconds=60,
        clock=lambda: 125.0,
    )
    raw_key = "never-store-this-workspace-key"
    digest = workspace_key_digest(raw_key)

    assert limiter.allow(digest, "198.51.100.7")
    assert limiter.allow(digest, "198.51.100.7")
    assert not limiter.allow(digest, "198.51.100.7")
    assert limiter.allow(digest, "198.51.100.8")
    assert all(raw_key not in key for key in counter.keys)
    assert all(digest in key for key in counter.keys)
    assert counter.keys[0] == counter.keys[1] == counter.keys[2]
    assert counter.keys[3] != counter.keys[0]
