"""Create the deterministic Swift OpenAPI nullable-compatibility derivative."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


SOURCE_DIGEST_EXTENSION = "x-find-me-gamer-source-sha256"


def _is_null_schema(value: object) -> bool:
    return isinstance(value, dict) and value == {"type": "null"}


def normalize_nullable_schemas(value: Any) -> Any:
    """Translate only `anyOf: [value, null]` into OpenAPI nullable form."""

    if isinstance(value, list):
        return [normalize_nullable_schemas(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {key: normalize_nullable_schemas(item) for key, item in value.items()}
    alternatives = normalized.get("anyOf")
    if not isinstance(alternatives, list) or len(alternatives) != 2:
        return normalized

    null_alternatives = [item for item in alternatives if _is_null_schema(item)]
    non_null_alternatives = [item for item in alternatives if not _is_null_schema(item)]
    if len(null_alternatives) != 1 or len(non_null_alternatives) != 1:
        return normalized

    non_null = non_null_alternatives[0]
    if not isinstance(non_null, dict):
        return normalized

    siblings = {key: item for key, item in normalized.items() if key != "anyOf"}
    if "$ref" in non_null:
        return {**siblings, "allOf": [non_null], "nullable": True}

    conflicting_keys = siblings.keys() & non_null.keys()
    if any(siblings[key] != non_null[key] for key in conflicting_keys):
        raise ValueError("nullable schema contains conflicting wrapper constraints")
    return {**non_null, **siblings, "nullable": True}


def normalized_document_bytes(source_bytes: bytes) -> bytes:
    document = json.loads(source_bytes)
    if SOURCE_DIGEST_EXTENSION in document:
        raise ValueError(f"source already defines {SOURCE_DIGEST_EXTENSION}")
    normalized = normalize_nullable_schemas(document)
    normalized[SOURCE_DIGEST_EXTENSION] = hashlib.sha256(source_bytes).hexdigest()
    return (
        json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def write_atomically(payload: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: normalize_openapi_for_swift.py SOURCE DESTINATION")
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    write_atomically(normalized_document_bytes(source.read_bytes()), destination)


if __name__ == "__main__":
    main()
