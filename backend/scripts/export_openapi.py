"""Export the tracked OpenAPI contract without runtime services or credentials."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Iterator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "openapi.json"


def write_schema_atomically(schema: dict[str, Any], destination: Path) -> None:
    """Replace ``destination`` only after a complete durable JSON write."""

    payload = (
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
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


@contextmanager
def _isolated_configuration() -> Iterator[None]:
    """Hide ambient application configuration while importing the app graph."""

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.core.config import Settings, get_settings
    from app.core.security import hash_workspace_key

    setting_names = {name.upper() for name in Settings.model_fields}
    original_environment = {
        name: os.environ[name] for name in setting_names if name in os.environ
    }
    original_directory = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="find-me-gamer-openapi-") as directory:
        key_path = Path(directory) / "inert-master.key"
        key_path.write_bytes(base64.b64encode(bytes(range(32))))
        key_path.chmod(0o600)
        try:
            for name in setting_names:
                os.environ.pop(name, None)
            os.environ["WORKSPACE_ACCESS_KEY_HASH"] = hash_workspace_key(
                "openapi-export-inert-workspace-key"
            )
            os.environ["MASTER_KEY_FILE"] = str(key_path)
            os.chdir(directory)
            get_settings.cache_clear()
            yield
        finally:
            get_settings.cache_clear()
            os.chdir(original_directory)
            for name in setting_names:
                os.environ.pop(name, None)
            os.environ.update(original_environment)


class _AllowAllRateLimiter:
    def allow(self, workspace_digest: str, client_address: str) -> bool:
        return True


class _InertChannelResolver:
    def resolve_channel(self, target: object) -> str:
        raise AssertionError("OpenAPI generation cannot resolve a provider target")


class _InertJobDispatcher:
    def dispatch(self, job_id: object) -> None:
        raise AssertionError("OpenAPI generation cannot dispatch a job")


@contextmanager
def _inert_session_factory():
    raise AssertionError("OpenAPI generation cannot open a database session")
    yield  # pragma: no cover


async def _close_default_app(default_app: object) -> None:
    async with default_app.router.lifespan_context(default_app):
        pass


def build_schema() -> dict[str, Any]:
    with _isolated_configuration():
        from app.api.routes.health import ReadinessProbe
        from app.core.crypto import SecretCipher
        from app.main import app as default_app
        from app.main import create_app

        try:
            export_app = create_app(
                readiness_probe=ReadinessProbe(lambda: True, lambda: True),
                workspace_key_hash=os.environ["WORKSPACE_ACCESS_KEY_HASH"],
                rate_limiter=_AllowAllRateLimiter(),
                secret_cipher=SecretCipher(bytes(range(32))),
                channel_resolver=_InertChannelResolver(),
                job_session_factory=_inert_session_factory,
                job_dispatcher=_InertJobDispatcher(),
            )
            return export_app.openapi()
        finally:
            asyncio.run(_close_default_app(default_app))


def main() -> None:
    write_schema_atomically(build_schema(), SCHEMA_PATH)


if __name__ == "__main__":
    main()
