#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
launcher="${repository_root}/script/local_real.sh"
local_compose="${repository_root}/compose.local.yaml"

[[ -x "$launcher" ]] || { echo "missing executable script/local_real.sh" >&2; exit 1; }
[[ -f "$local_compose" ]] || { echo "missing compose.local.yaml" >&2; exit 1; }
grep -Fqx '/.local/' "${repository_root}/.gitignore"

python3 - "$repository_root" "$launcher" "$local_compose" <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


root, launcher, local_compose = map(Path, sys.argv[1:])
base_compose = root / "compose.yaml"


def run(
    arguments: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(launcher), *arguments],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )


def calls(log: Path) -> list[dict[str, object]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


fake_docker = r'''#!/usr/bin/env python3
import json, os, pathlib, sys

arguments = sys.argv[1:]
record = {"args": arguments}
if "run" in arguments and any("hash_workspace_key" in item for item in arguments):
    supplied = sys.stdin.read()
    if supplied != os.environ["FMG_EXPECTED_WORKSPACE_KEY"]:
        raise SystemExit(42)
    record["stdin_bytes"] = len(supplied.encode("utf-8"))
with pathlib.Path(os.environ["FMG_LOCAL_FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record) + "\n")
if "run" in arguments and any("hash_workspace_key" in item for item in arguments):
    print(os.environ["FMG_FAKE_WORKSPACE_HASH"])
raise SystemExit(0)
'''

fake_openssl = r'''#!/usr/bin/env python3
import os, pathlib, sys

counter_path = pathlib.Path(os.environ["FMG_OPENSSL_COUNTER"])
counter = int(counter_path.read_text(encoding="utf-8")) if counter_path.exists() else 0
counter_path.write_text(str(counter + 1), encoding="utf-8")
if sys.argv[1:] == ["rand", "-base64", "32"]:
    print(os.environ["FMG_FAKE_MASTER_KEY"], end="")
elif sys.argv[1:] == ["rand", "-hex", "24"]:
    value = (
        os.environ["FMG_EXPECTED_WORKSPACE_KEY"]
        if counter == 1
        else os.environ["FMG_FAKE_POSTGRES_PASSWORD"]
    )
    print(value, end="")
else:
    raise SystemExit(43)
'''

workspace_key = "111111111111111111111111111111111111111111111111"
master_key = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
postgres_password = "222222222222222222222222222222222222222222222222"
workspace_hash = (
    "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0c2FsdA$"
    "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE"
)

with tempfile.TemporaryDirectory(prefix="fmg-local-real-test.") as temporary:
    test_root = Path(temporary)
    tools = test_root / "tools"
    tools.mkdir()
    docker = tools / "docker"
    docker.write_text(fake_docker, encoding="utf-8")
    docker.chmod(0o700)
    openssl = tools / "openssl"
    openssl.write_text(fake_openssl, encoding="utf-8")
    openssl.chmod(0o700)

    state = test_root / "state"
    log = test_root / "docker.log"
    counter = test_root / "openssl.count"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{tools}:{environment['PATH']}",
            "FMG_LOCAL_TEST_MODE": "1",
            "FMG_LOCAL_TEST_STATE_DIR": str(state),
            "FMG_LOCAL_FAKE_LOG": str(log),
            "FMG_OPENSSL_COUNTER": str(counter),
            "FMG_EXPECTED_WORKSPACE_KEY": workspace_key,
            "FMG_FAKE_MASTER_KEY": master_key,
            "FMG_FAKE_POSTGRES_PASSWORD": postgres_password,
            "FMG_FAKE_WORKSPACE_HASH": workspace_hash,
            "WORKSPACE_ACCESS_KEY": "inherited-workspace-secret-must-be-ignored",
            "POSTGRES_PASSWORD": "inherited-postgres-secret-must-be-ignored",
            "AWS_SECRET_ACCESS_KEY": "inherited-aws-secret-must-be-ignored",
        }
    )

    started = run(["start"], environment)
    assert started.returncode == 0, started.stderr
    observable = started.stdout + started.stderr + log.read_text(encoding="utf-8")
    for secret in (
        workspace_key,
        master_key,
        postgres_password,
        environment["WORKSPACE_ACCESS_KEY"],
        environment["POSTGRES_PASSWORD"],
        environment["AWS_SECRET_ACCESS_KEY"],
    ):
        assert secret not in observable

    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    expected_files = {
        "compose.env",
        "master.key",
        "workspace.key",
        "workspace.hash",
        "postgres.password",
    }
    assert {path.name for path in state.iterdir()} == expected_files
    for name in expected_files:
        assert stat.S_IMODE((state / name).stat().st_mode) == 0o600
    assert (state / "workspace.key").read_text(encoding="utf-8") == workspace_key
    assert (state / "master.key").read_text(encoding="utf-8") == master_key
    env_text = (state / "compose.env").read_text(encoding="utf-8")
    assert "ARTIFACT_STORE=filesystem\n" in env_text
    assert "ARTIFACT_DIRECTORY=/var/lib/find-me-gamer/artifacts\n" in env_text
    assert f"WORKSPACE_ACCESS_KEY_HASH='{workspace_hash}'\n" in env_text
    assert workspace_key not in env_text and master_key not in env_text

    recorded = calls(log)
    common = [
        "compose",
        "--project-name",
        "find-me-gamer-local",
        "--project-directory",
        str(root),
        "--env-file",
        str(state / "compose.env"),
        "-f",
        str(base_compose),
        "-f",
        str(local_compose),
    ]
    assert recorded
    assert all(call["args"][: len(common)] == common for call in recorded)
    build_index = next(i for i, call in enumerate(recorded) if "build" in call["args"])
    database_up_index = next(
        i
        for i, call in enumerate(recorded)
        if "up" in call["args"]
        and call["args"][-2:] == ["postgres", "redis"]
    )
    migration_index = next(
        i
        for i, call in enumerate(recorded)
        if "run" in call["args"] and call["args"][-3:] == ["alembic", "upgrade", "head"]
    )
    application_up_index = next(
        i
        for i, call in enumerate(recorded)
        if "up" in call["args"] and call["args"][-4:] == ["api", "worker", "postgres", "redis"]
    )
    assert build_index < database_up_index < migration_index < application_up_index
    application_up = recorded[application_up_index]["args"]
    assert "proxy" not in application_up and "beat" not in application_up
    hash_calls = [
        call
        for call in recorded
        if "run" in call["args"]
        and any("hash_workspace_key" in arg for arg in call["args"])
    ]
    assert len(hash_calls) == 1
    assert hash_calls[0]["stdin_bytes"] == len(workspace_key.encode("utf-8"))

    first_openssl_count = int(counter.read_text(encoding="utf-8"))
    second = run(["start"], environment)
    assert second.returncode == 0, second.stderr
    assert int(counter.read_text(encoding="utf-8")) == first_openssl_count
    assert len(
        [
            call
            for call in calls(log)
            if "run" in call["args"]
            and any("hash_workspace_key" in arg for arg in call["args"])
        ]
    ) == 1

    beat_log_start = len(calls(log))
    beat = run(["start", "--beat"], environment)
    assert beat.returncode == 0, beat.stderr
    beat_calls = calls(log)[beat_log_start:]
    assert all("--profile" in call["args"] and "beat" in call["args"] for call in beat_calls)
    beat_up = next(call["args"] for call in beat_calls if "up" in call["args"] and "api" in call["args"])
    assert beat_up[-5:] == ["api", "worker", "beat", "postgres", "redis"]
    assert "proxy" not in beat_up

    assert run(["status"], environment).returncode == 0
    assert run(["logs", "worker"], environment).returncode == 0
    assert run(["stop"], environment).returncode == 0
    final_calls = calls(log)
    assert any("ps" in call["args"] for call in final_calls)
    assert any("logs" in call["args"] and call["args"][-1] == "worker" for call in final_calls)
    assert any("down" in call["args"] and "--remove-orphans" in call["args"] for call in final_calls)

    shown_key = run(["key"], environment)
    assert shown_key.returncode == 0, shown_key.stderr
    assert shown_key.stdout == workspace_key + "\n"

with tempfile.TemporaryDirectory(prefix="fmg-local-compose-test.") as temporary:
    test_root = Path(temporary)
    master = test_root / "master.key"
    master.write_text(master_key, encoding="utf-8")
    master.chmod(0o600)
    env_file = test_root / "compose.env"
    env_file.write_text(
        "\n".join(
            (
                "SERVICE_DOMAIN=localhost",
                "BACKEND_SUBNET=172.31.249.0/24",
                "POSTGRES_DB=find_me_gamer_local",
                "POSTGRES_USER=find_me_gamer",
                f"POSTGRES_PASSWORD={postgres_password}",
                f"WORKSPACE_ACCESS_KEY_HASH='{workspace_hash}'",
                "FMG_AWS_REGION=us-east-1",
                "FMG_S3_BUCKET=find-me-gamer-local-artifacts",
                "ARTIFACT_STORE=filesystem",
                "ARTIFACT_DIRECTORY=/var/lib/find-me-gamer/artifacts",
                f"FMG_LOCAL_MASTER_KEY={master}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            "find-me-gamer-local-contract",
            "--project-directory",
            str(root),
            "--env-file",
            str(env_file),
            "-f",
            str(base_compose),
            "-f",
            str(local_compose),
            "--profile",
            "*",
            "config",
            "--format",
            "json",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    config = json.loads(completed.stdout)
    services = config["services"]
    assert services["proxy"]["profiles"] == ["proxy"]
    assert services["beat"]["profiles"] == ["beat"]
    api_ports = services["api"]["ports"]
    assert api_ports == [
        {
            "mode": "ingress",
            "target": 8000,
            "published": "8000",
            "protocol": "tcp",
            "host_ip": "127.0.0.1",
        }
    ]
    for service_name in ("api", "worker"):
        service = services[service_name]
        assert service["environment"]["ARTIFACT_STORE"] == "filesystem"
        assert service["environment"]["ARTIFACT_DIRECTORY"] == "/var/lib/find-me-gamer/artifacts"
        mounts = {mount["target"]: mount for mount in service["volumes"]}
        assert mounts["/var/lib/find-me-gamer/artifacts"]["type"] == "volume"
        assert mounts["/etc/find-me-gamer/master.key"]["source"] == str(master)
        assert mounts["/etc/find-me-gamer/master.key"]["read_only"] is True
    assert config["volumes"]["artifacts"]["name"] == "find-me-gamer-local-artifacts"
    assert config["volumes"]["postgres_data"]["name"] == "find-me-gamer-local-postgres-data"
    assert config["volumes"]["redis_data"]["name"] == "find-me-gamer-local-redis-data"
    assert config["networks"]["backend"]["name"] == "find-me-gamer-local-backend"
    assert not config["networks"]["backend"].get("ipam", {}).get("config")

launcher_text = launcher.read_text(encoding="utf-8")
assert "set -x" not in launcher_text
assert "source " not in launcher_text
assert "eval " not in launcher_text
assert "WORKSPACE_ACCESS_KEY=" not in launcher_text
PY

echo "PASS: local real Docker launcher contract"
