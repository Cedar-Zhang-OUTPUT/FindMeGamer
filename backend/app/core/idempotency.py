import hashlib
import json
import re
from typing import Any


_idempotency_key = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class InvalidIdempotencyKey(ValueError):
    pass


def validate_idempotency_key(value: str | None) -> str:
    if value is None or _idempotency_key.fullmatch(value) is None:
        raise InvalidIdempotencyKey
    return value


def request_hash(
    *, method: str, path: str, canonical_request: dict[str, Any]
) -> str:
    payload = {
        "method": method.upper(),
        "path": path,
        "request": canonical_request,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
