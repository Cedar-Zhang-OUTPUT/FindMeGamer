from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from contextlib import asynccontextmanager

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent
EXPORTER = BACKEND_ROOT / "scripts" / "export_openapi.py"
COMMITTED_SCHEMA = BACKEND_ROOT / "openapi.json"

EXPECTED_OPERATIONS = {
    ("GET", "/health/live"): "checkLiveness",
    ("GET", "/health/ready"): "checkReadiness",
    ("GET", "/api/v1/session"): "validateSession",
    ("GET", "/api/v1/settings/reanalysis"): "getReanalysisSettings",
    ("PATCH", "/api/v1/settings/reanalysis"): "updateReanalysisSettings",
    (
        "GET",
        "/api/v1/settings/connections/{service}",
    ): "getConnectionStatus",
    (
        "PUT",
        "/api/v1/settings/connections/{service}",
    ): "replaceConnectionSecret",
    (
        "POST",
        "/api/v1/settings/connections/{service}",
    ): "testConnection",
    ("GET", "/api/v1/profiles/games"): "listGameProfiles",
    ("GET", "/api/v1/profiles/creators"): "listCreatorProfiles",
    (
        "PATCH",
        "/api/v1/profiles/creators/{profile_id}/manual",
    ): "updateCreatorManual",
    (
        "GET",
        "/api/v1/profiles/{profile_type}/{profile_id}",
    ): "getProfile",
    (
        "PATCH",
        "/api/v1/profiles/{profile_type}/{profile_id}/favorite",
    ): "setProfileFavorite",
    ("GET", "/api/v1/profiles/{profile_type}"): "rejectUnknownProfileType",
    ("GET", "/api/v1/jobs"): "listJobs",
    ("GET", "/api/v1/jobs/{job_id}"): "getAnalysisJob",
    ("POST", "/api/v1/jobs/analysis"): "createAnalysisJob",
    (
        "POST",
        "/api/v1/jobs/analysis/{job_id}/retry",
    ): "retryAnalysisJob",
    ("POST", "/api/v1/matches"): "createMatch",
    ("GET", "/api/v1/matches"): "listMatches",
    ("GET", "/api/v1/matches/{match_task_id}"): "getMatch",
    ("POST", "/api/v1/matches/{match_task_id}/retry"): "retryMatch",
}
HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


def _actual_operations(schema: dict[str, object]) -> dict[tuple[str, str], str]:
    paths = schema["paths"]
    assert isinstance(paths, dict)
    return {
        (method.upper(), path): operation["operationId"]
        for path, path_item in paths.items()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    }


def _operation(schema: dict[str, object], method: str, path: str) -> dict:
    return schema["paths"][path][method.casefold()]


def _referenced_response_components(schema: dict[str, object]) -> set[str]:
    components = schema["components"]["schemas"]
    pending: list[object] = [
        operation.get("responses", {})
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    ]
    names: set[str] = set()
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith(
                "#/components/schemas/"
            ):
                name = reference.rsplit("/", 1)[-1]
                if name not in names:
                    names.add(name)
                    pending.append(components[name])
            pending.extend(item for key, item in value.items() if key != "$ref")
    return names


def test_openapi_has_exact_stable_unique_camel_case_operations(client) -> None:
    schema = client.app.openapi()

    actual = _actual_operations(schema)

    assert actual == EXPECTED_OPERATIONS
    assert len(actual.values()) == len(set(actual.values()))
    assert all(re.fullmatch(r"[a-z][A-Za-z0-9]*", value) for value in actual.values())


def test_openapi_retains_bearer_auth_and_required_idempotency_headers(client) -> None:
    schema = client.app.openapi()

    assert schema["components"]["securitySchemes"] == {
        "HTTPBearer": {"type": "http", "scheme": "bearer"}
    }
    for (method, path), _operation_id in EXPECTED_OPERATIONS.items():
        operation = _operation(schema, method, path)
        if path.startswith("/api/v1/"):
            assert operation["security"] == [{"HTTPBearer": []}]

    for method, path in (
        ("POST", "/api/v1/jobs/analysis"),
        ("POST", "/api/v1/jobs/analysis/{job_id}/retry"),
        ("POST", "/api/v1/matches"),
        ("POST", "/api/v1/matches/{match_task_id}/retry"),
    ):
        parameters = _operation(schema, method, path)["parameters"]
        idempotency = [
            value
            for value in parameters
            if value.get("in") == "header" and value.get("name") == "Idempotency-Key"
        ]
        assert len(idempotency) == 1
        assert idempotency[0]["required"] is True


def test_openapi_secret_is_write_only_request_only_and_responses_are_sanitized(
    client,
) -> None:
    schema = client.app.openapi()
    components = schema["components"]["schemas"]
    secret_update = components["ConnectionSecretUpdate"]

    assert secret_update["required"] == ["secret"]
    assert secret_update["properties"]["secret"]["writeOnly"] is True

    response_components = _referenced_response_components(schema)
    assert "ConnectionSecretUpdate" not in response_components
    forbidden_properties = {
        "secret",
        "ciphertext",
        "nonce",
        "workspace_access_key_hash",
        "workspace_key_hash",
        "workspace_key_digest",
        "result_payload",
        "error_message",
        "broker_url",
        "broker_metadata",
        "task_metadata",
        "token_digest",
        "database_url",
    }
    exposed_properties = {
        property_name.casefold()
        for component_name in response_components
        for property_name in components[component_name].get("properties", {})
    }
    assert exposed_properties.isdisjoint(forbidden_properties)


def _guarded_export_environment(tmp_path: Path, hash_seed: str) -> dict[str, str]:
    guard = tmp_path / f"network-guard-{hash_seed}"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        """
import socket

def blocked(*args, **kwargs):
    raise AssertionError("OpenAPI export attempted network access")

class GuardedSocket(socket.socket):
    def connect(self, *args, **kwargs):
        blocked()
    def connect_ex(self, *args, **kwargs):
        blocked()

socket.socket = GuardedSocket
socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.gethostbyname = blocked
socket.gethostbyname_ex = blocked
""".lstrip(),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    for name in (
        "WORKSPACE_ACCESS_KEY_HASH",
        "MASTER_KEY_FILE",
        "DATABASE_URL",
        "REDIS_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ):
        environment.pop(name, None)
    environment["PYTHONHASHSEED"] = hash_seed
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(guard), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    return environment


def _run_export(cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess:
    script = EXPORTER if cwd == REPOSITORY_ROOT else Path("scripts/export_openapi.py")
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_exporter_is_offline_credential_free_deterministic_and_committed(
    tmp_path: Path,
) -> None:
    original = COMMITTED_SCHEMA.read_bytes() if COMMITTED_SCHEMA.exists() else None
    generated: list[bytes] = []
    try:
        for cwd, seed in (
            (REPOSITORY_ROOT, "1"),
            (BACKEND_ROOT, "777"),
            (REPOSITORY_ROOT, "2147483647"),
        ):
            result = _run_export(
                cwd,
                _guarded_export_environment(tmp_path, seed),
            )
            assert result.returncode == 0, result.stderr
            generated.append(COMMITTED_SCHEMA.read_bytes())

        assert generated[0] == generated[1] == generated[2]
        assert generated[0].endswith(b"\n")
        assert not generated[0].endswith(b"\n\n")
        assert json.loads(generated[0])
        assert original is not None
        assert generated[0] == original
    finally:
        if original is None:
            COMMITTED_SCHEMA.unlink(missing_ok=True)
        else:
            COMMITTED_SCHEMA.write_bytes(original)


def test_atomic_export_failure_preserves_previous_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location("task14_export_openapi", EXPORTER)
    assert spec is not None and spec.loader is not None
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    destination = tmp_path / "openapi.json"
    destination.write_bytes(b'{"stable": true}\n')

    def fail_replace(source: object, target: object) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(exporter.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated atomic replace failure"):
        exporter.write_schema_atomically({"new": True}, destination)

    assert destination.read_bytes() == b'{"stable": true}\n'
    assert list(tmp_path.iterdir()) == [destination]


def test_schema_failure_still_closes_import_created_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = importlib.util.spec_from_file_location("task14_export_failure", EXPORTER)
    assert spec is not None and spec.loader is not None
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    events: list[str] = []

    class FakeRouter:
        @asynccontextmanager
        async def lifespan_context(self, app: object):
            events.append("entered")
            try:
                yield
            finally:
                events.append("closed")

    class FakeDefaultApp:
        router = FakeRouter()

    class FailingExportApp:
        def openapi(self) -> dict[str, object]:
            raise RuntimeError("schema generation failed")

    monkeypatch.setattr("app.main.app", FakeDefaultApp())
    monkeypatch.setattr("app.main.create_app", lambda **kwargs: FailingExportApp())

    with pytest.raises(RuntimeError, match="schema generation failed"):
        exporter.build_schema()

    assert events == ["entered", "closed"]
