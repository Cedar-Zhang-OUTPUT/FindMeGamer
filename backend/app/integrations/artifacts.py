from collections.abc import Mapping
import json
import math
import re
from uuid import UUID

from app.integrations.errors import PermanentIntegrationError

ARTIFACT_PREFIX = "acquisition"
MAX_ARTIFACT_JSON_BYTES = 5_000_000
_artifact_name = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")


def artifact_key(job_id: UUID, name: str) -> str:
    if not isinstance(job_id, UUID) or job_id.int == 0:
        raise PermanentIntegrationError("artifact_job_id_invalid")
    if (
        not isinstance(name, str)
        or not name.isascii()
        or not _artifact_name.fullmatch(name)
        or ".." in name
    ):
        raise PermanentIntegrationError("artifact_name_invalid")
    return f"{ARTIFACT_PREFIX}/{job_id}/{name}"


def serialize_artifact_payload(payload: object, *, max_bytes: int) -> bytes:
    validate_max_json_bytes(max_bytes)
    if not isinstance(payload, Mapping):
        raise PermanentIntegrationError("artifact_payload_invalid")
    try:
        normalized = _strict_json_value(payload, depth=0)
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise PermanentIntegrationError("artifact_payload_invalid") from None
    if len(encoded) > max_bytes:
        raise PermanentIntegrationError("artifact_payload_too_large")
    return encoded


def validate_max_json_bytes(max_json_bytes: object) -> None:
    if (
        isinstance(max_json_bytes, bool)
        or not isinstance(max_json_bytes, int)
        or not 1 <= max_json_bytes <= 100_000_000
    ):
        raise PermanentIntegrationError("artifact_configuration_invalid")


def _strict_json_value(value: object, *, depth: int) -> object:
    if depth > 64:
        raise ValueError("JSON nesting is too deep")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            result[key] = _strict_json_value(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_strict_json_value(item, depth=depth + 1) for item in value]
    raise TypeError("unsupported JSON value")
