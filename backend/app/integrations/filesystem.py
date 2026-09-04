from collections.abc import Mapping
from contextlib import suppress
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import UUID

from app.integrations.artifacts import (
    MAX_ARTIFACT_JSON_BYTES,
    artifact_key,
    serialize_artifact_payload,
    validate_max_json_bytes,
)
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError


class FilesystemArtifactStore:
    """Atomically store analysis artifacts beneath a local absolute directory."""

    def __init__(
        self,
        *,
        directory: Path,
        max_json_bytes: int = MAX_ARTIFACT_JSON_BYTES,
    ) -> None:
        try:
            configured_directory = Path(directory)
        except TypeError:
            raise PermanentIntegrationError("artifact_configuration_invalid") from None
        if not configured_directory.is_absolute():
            raise PermanentIntegrationError("artifact_configuration_invalid")
        validate_max_json_bytes(max_json_bytes)
        self._directory = configured_directory
        self._max_json_bytes = max_json_bytes

    def close(self) -> None:
        pass

    def __enter__(self) -> "FilesystemArtifactStore":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def put_json(
        self,
        job_id: UUID,
        name: str,
        payload: Mapping[str, Any],
    ) -> str:
        key = artifact_key(job_id, name)
        body = serialize_artifact_payload(payload, max_bytes=self._max_json_bytes)
        destination = self._directory / key
        temporary: Path | None = None
        descriptor: int | None = None
        try:
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{name}.", suffix=".tmp", dir=destination.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            temporary = None
        except OSError:
            raise TransientIntegrationError("artifact_unavailable") from None
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink()
        return key
