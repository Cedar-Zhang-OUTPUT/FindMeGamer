#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
smoke_script="${repository_root}/ops/smoke_test.sh"
seed_script="${repository_root}/ops/seed_initial_creators.sh"
fixture="${repository_root}/ops/tests/fixtures/creator-seed-100.csv"
template="${repository_root}/docs/creator-seed-format.csv"

[[ -x "$smoke_script" ]] || { echo "missing executable ops/smoke_test.sh" >&2; exit 1; }
[[ -x "$seed_script" ]] || { echo "missing executable ops/seed_initial_creators.sh" >&2; exit 1; }

python3 - "$fixture" "$template" <<'PY'
import csv
from pathlib import Path
import sys

fixture, template = map(Path, sys.argv[1:])
expected = ["youtube_url", "contact_email", "notes"]
assert template.read_text(encoding="utf-8") == ",".join(expected) + "\n"
with fixture.open(encoding="utf-8", newline="") as stream:
    rows = list(csv.reader(stream))
assert rows[0] == expected
assert len(rows[1:]) == 100
urls = [row[0] for row in rows[1:]]
assert all(len(row) == 3 and row[0] and row[1:] == ["", ""] for row in rows[1:])
assert len(set(urls)) == 100
assert all(url.startswith("https://www.youtube.com/channel/UC") for url in urls)
print("PASS: exact 100-row synthetic Creator fixture")
PY

rg -Fq 'python -m app.cli.seed_creators' "$seed_script"
rg -Fq 'the checked-in synthetic fixture cannot be used live' "$seed_script"
rg -Fq -- '--env-file "$env_file"' "$seed_script"
! rg -n 'source[[:space:]]+.*app\.env|(^|[[:space:]])\.[[:space:]]+.*app\.env|eval' "$seed_script"

python3 - "$repository_root" "$smoke_script" "$seed_script" "$fixture" <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


root, smoke_script, seed_script, fixture = map(Path, sys.argv[1:])


def run(command: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )


fake_curl_source = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
arguments = sys.argv[1:]
log = pathlib.Path(os.environ["FMG_FAKE_CURL_LOG"])
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(arguments) + "\n")
if not arguments or arguments[0] not in ("--disable", "-q"):
    raise SystemExit(88)
if "--request" not in arguments or arguments[arguments.index("--request") + 1] != "GET":
    raise SystemExit(89)
if "--proto" not in arguments or arguments[arguments.index("--proto") + 1] != "=https":
    raise SystemExit(90)
if "--max-redirs" not in arguments or arguments[arguments.index("--max-redirs") + 1] != "0":
    raise SystemExit(91)
if "--location" in arguments or "-L" in arguments or "POST" in arguments:
    raise SystemExit(92)
output = pathlib.Path(arguments[arguments.index("--output") + 1])
url = arguments[-1]
path = url.split("smoke.test", 1)[-1]
mode = os.environ.get("FMG_FAKE_CURL_MODE", "ok")
status = 200
if path == "/health/live" or path == "/health/ready":
    body = {"status": "ok"}
elif path == "/api/v1/session":
    body = {"workspace_name": "Demo", "api_version": "v1", "service_connections": {}}
elif path == "/api/v1/settings/reanalysis":
    body = {"creator_interval_days": 30, "game_interval_days": 30}
elif path.startswith("/api/v1/settings/connections/"):
    body = {"configured": False, "last_test_status": None, "last_tested_at": None}
elif path == "/api/v1/outreach/smtp":
    body = {"configured": False, "host": None, "port": None, "encryption": None, "username": None, "from_name": None, "reply_to": None, "emails_per_minute": 10, "last_test_status": None, "last_tested_at": None}
elif path in ("/api/v1/profiles/games", "/api/v1/profiles/creators"):
    body = {"items": [], "next_cursor": None}
elif path in ("/api/v1/matches", "/api/v1/outreach/campaigns"):
    body = {"items": [], "cursor": None, "has_more": False}
elif path.startswith("/api/v1/jobs"):
    body = {"items": [], "cursor": "opaque +/cursor==", "has_more": False, "affected_profile_ids": []}
elif path == "/r/not-a-capability?choice=accepted":
    status = 404
    body = "<!doctype html><title>Response link not found</title>"
else:
    status = 500
    body = {"error": {"code": "fake_route_missing", "message": "Fake route missing."}}
if mode == "malformed" and path == "/api/v1/session":
    body = "not-json"
if mode == "unhealthy" and path == "/health/ready":
    status = 503
    body = {"status": "unavailable", "private": "BODY-CANARY"}
output.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
sys.stdout.write(str(status))
'''

fake_docker_source = r'''#!/usr/bin/env python3
import csv, hashlib, json, os, pathlib, shutil, subprocess, sys
arguments = sys.argv[1:]
state = pathlib.Path(os.environ["FMG_FAKE_DOCKER_STATE"])
state.mkdir(parents=True, exist_ok=True)
with (state / "calls.log").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(arguments) + "\n")
mode = os.environ.get("FMG_FAKE_DOCKER_MODE", "ok")
if mode == "docker-failure":
    raise SystemExit(7)
if "ps" in arguments:
    print(json.dumps({"Service": "api", "State": "running", "Health": "healthy"}))
    worker_health = "unhealthy" if mode == "unhealthy" else "healthy"
    print(json.dumps({"Service": "worker", "State": "running", "Health": worker_health}))
    raise SystemExit(0)
if "cp" in arguments:
    index = arguments.index("cp")
    source, destination = arguments[index + 1:index + 3]
    if mode == "copy-failure":
        raise SystemExit(8)
    if destination.startswith("api:"):
        shutil.copyfile(source, state / pathlib.Path(destination[4:]).name)
    elif source.startswith("api:"):
        shutil.copyfile(state / pathlib.Path(source[4:]).name, destination)
    else:
        raise SystemExit(9)
    raise SystemExit(0)
if "exec" in arguments:
    if "mkdir" in arguments:
        raise SystemExit(0)
    if "rm" in arguments or "rmdir" in arguments:
        if mode == "cleanup-failure" and any(value.endswith("creators.csv") for value in arguments):
            raise SystemExit(13)
        raise SystemExit(0)
    if "-m" in arguments and "app.cli.seed_creators" in arguments:
        csv_name = pathlib.Path(arguments[arguments.index("app.cli.seed_creators") + 1]).name
        report_name = pathlib.Path(arguments[arguments.index("--report") + 1]).name
        raw = (state / csv_name).read_bytes()
        rows = list(csv.reader(raw.decode().splitlines()))[1:]
        failed = mode == "failed-rows"
        report = {
            "format_version": 1,
            "source_fingerprint": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "counts": {"queued": 0 if failed else 100, "duplicate": 0, "failed": 100 if failed else 0},
            "rows": [
                {"row_number": number, "youtube_url": row[0], "contact_email": None, "notes": None, "status": "failed" if failed else "queued", "canonical_channel_id": None, "canonical_url": None, "job_id": None, "profile_id": None, "error": {"code": "safe", "message": "Safe failure."} if failed else None}
                for number, row in enumerate(rows, start=2)
            ],
        }
        report_text = "not-json" if mode == "malformed-report" else json.dumps(report)
        (state / report_name).write_text(report_text, encoding="utf-8")
        print(json.dumps(report["counts"]))
        raise SystemExit(1 if failed or mode == "cli-failure" else 0)
    if "load_seed_report" in " ".join(arguments):
        report_name = pathlib.Path(arguments[-1]).name
        try:
            report = json.loads((state / report_name).read_text(encoding="utf-8"))
            counts = report["counts"]
            rows = report["rows"]
            assert report["format_version"] == 1 and len(rows) == 100
            incomplete = sum(row["status"] == "incomplete" for row in rows)
            print(counts["queued"], counts["duplicate"], counts["failed"], incomplete)
            raise SystemExit(0)
        except Exception:
            raise SystemExit(10)
    if "seed CSV must contain exactly 100 rows" in " ".join(arguments):
        csv_name = pathlib.Path(arguments[-1]).name
        program = arguments[arguments.index("-c") + 1]
        completed = subprocess.run(
            [sys.executable, "-c", program, str(state / csv_name)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        raise SystemExit(completed.returncode)
raise SystemExit(12)
'''


with tempfile.TemporaryDirectory(prefix="fmg-task7-test.") as temporary:
    test_root = Path(temporary)
    fake_curl = test_root / "curl"
    fake_docker = test_root / "docker"
    fake_curl.write_text(fake_curl_source, encoding="utf-8")
    fake_docker.write_text(fake_docker_source, encoding="utf-8")
    fake_curl.chmod(0o700)
    fake_docker.chmod(0o700)

    key = "WORKSPACE-PLAINTEXT-CANARY"
    key_file = test_root / "workspace.key"
    key_file.write_text(key + "\n", encoding="utf-8")
    key_file.chmod(0o600)
    (test_root / ".curlrc").write_text(
        'fail\nrequest = "POST"\nheader = "Authorization: Bearer CURLRC-CANARY"\n',
        encoding="utf-8",
    )
    curl_log = test_root / "curl.log"
    smoke_environment = os.environ.copy()
    smoke_environment.update(
        {
            "FMG_OPERATOR_TEST_MODE": "1",
            "FMG_CURL_BIN": str(fake_curl),
            "FMG_FAKE_CURL_LOG": str(curl_log),
            "FMG_WORKSPACE_KEY_FILE": str(key_file),
            "HOME": str(test_root),
        }
    )
    smoke = run([str(smoke_script), "https://smoke.test"], smoke_environment)
    assert smoke.returncode == 0, smoke.stderr
    observable = smoke.stdout + smoke.stderr + curl_log.read_text(encoding="utf-8")
    assert key not in observable
    calls = [json.loads(line) for line in curl_log.read_text().splitlines()]
    assert calls and all(call[0] in ("--disable", "-q") for call in calls)
    assert all("--request" in call and call[call.index("--request") + 1] == "GET" for call in calls)
    assert all("--proto" in call and call[call.index("--proto") + 1] == "=https" for call in calls)
    assert all("--max-redirs" in call and call[call.index("--max-redirs") + 1] == "0" for call in calls)
    assert all("--location" not in call and "-L" not in call and "POST" not in call for call in calls)
    assert all(key not in argument for call in calls for argument in call)
    public = [call for call in calls if call[-1].endswith("/r/not-a-capability?choice=accepted")]
    assert len(public) == 1 and "--config" not in public[0]
    assert not any("authorization" in argument.casefold() for argument in public[0])
    authenticated = [call for call in calls if "/api/v1/" in call[-1]]
    assert authenticated and all("--config" in call for call in authenticated)
    header_paths = {call[call.index("--config") + 1] for call in authenticated}
    assert len(header_paths) == 1 and not Path(header_paths.pop()).exists()
    assert sum(call[-1].endswith("/api/v1/outreach/campaigns") for call in calls) == 2
    assert any("changed_after=opaque%20%2B%2Fcursor%3D%3D" in call[-1] for call in calls)

    def smoke_failure(environment: dict[str, str], base: str = "https://smoke.test") -> None:
        result = run([str(smoke_script), base], environment)
        assert result.returncode != 0
        assert key not in result.stdout + result.stderr
        assert "BODY-CANARY" not in result.stdout + result.stderr

    unsafe_key = test_root / "unsafe.key"
    unsafe_key.write_text(key + "\n", encoding="utf-8")
    unsafe_key.chmod(0o644)
    unsafe_environment = smoke_environment | {"FMG_WORKSPACE_KEY_FILE": str(unsafe_key)}
    smoke_failure(unsafe_environment)
    missing_key_environment = smoke_environment.copy()
    missing_key_environment.pop("FMG_WORKSPACE_KEY_FILE")
    smoke_failure(missing_key_environment)
    symlink_key = test_root / "linked.key"
    symlink_key.symlink_to(key_file)
    smoke_failure(smoke_environment | {"FMG_WORKSPACE_KEY_FILE": str(symlink_key)})
    multiline_key = test_root / "multiline.key"
    multiline_key.write_text(key + "\nsecond-line\n", encoding="utf-8")
    multiline_key.chmod(0o600)
    smoke_failure(smoke_environment | {"FMG_WORKSPACE_KEY_FILE": str(multiline_key)})
    smoke_failure(smoke_environment, "http://smoke.test")
    smoke_failure(smoke_environment, "https://smoke.test/path")
    smoke_failure(smoke_environment, "https://user@smoke.test")
    smoke_failure(smoke_environment, "https://127.0.0.1")
    smoke_failure(smoke_environment, "https://localhost")
    smoke_failure(smoke_environment, "https://operator.invalid")
    smoke_failure(smoke_environment, "https://smoke.test:70000")
    smoke_failure(smoke_environment | {"FMG_FAKE_CURL_MODE": "malformed"})
    smoke_failure(smoke_environment | {"FMG_FAKE_CURL_MODE": "unhealthy"})

    csv_path = test_root / "creators.csv"
    shutil.copyfile(fixture, csv_path)
    csv_path.chmod(0o600)
    env_file = test_root / "app.env"
    env_file.write_text("POSTGRES_PASSWORD=ENV-SECRET-CANARY\nWORKSPACE_ACCESS_KEY_HASH='HASH-CANARY'\n", encoding="utf-8")
    env_file.chmod(0o600)
    docker_state = test_root / "docker-state"
    docker_state.mkdir()
    seed_environment = os.environ.copy()
    seed_environment.update(
        {
            "FMG_OPERATOR_TEST_MODE": "1",
            "FMG_SEED_REPO_ROOT": str(root),
            "FMG_SEED_ENV_FILE": str(env_file),
            "FMG_DOCKER_BIN": str(fake_docker),
            "FMG_FAKE_DOCKER_STATE": str(docker_state),
            "POSTGRES_PASSWORD": "ARGV-SECRET-CANARY",
            "WORKSPACE_ACCESS_KEY_HASH": "ARGV-HASH-CANARY",
        }
    )
    seeded = run([str(seed_script), str(csv_path)], seed_environment)
    assert seeded.returncode == 0, seeded.stderr
    report_path = Path(str(csv_path) + ".report.json")
    assert report_path.is_file() and stat.S_IMODE(report_path.stat().st_mode) == 0o600
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["counts"] == {"queued": 100, "duplicate": 0, "failed": 0}
    docker_log = (docker_state / "calls.log").read_text(encoding="utf-8")
    assert "ARGV-SECRET-CANARY" not in docker_log
    assert "ARGV-HASH-CANARY" not in docker_log
    calls = [json.loads(line) for line in docker_log.splitlines()]
    assert calls and all("--env-file" in call and str(env_file) in call for call in calls)
    assert any(
        any(call[index : index + 3] == ["python", "-m", "app.cli.seed_creators"] for index in range(len(call) - 2))
        for call in calls
    )
    assert not any("prune" in call for call in calls)
    cleanup_calls = [call for call in calls if "rm" in call or "rmdir" in call]
    assert len(cleanup_calls) == 3
    assert all("/tmp/find-me-gamer-seed-" in " ".join(call) for call in cleanup_calls)

    target_csv = test_root / "supported-targets.csv"
    target_rows = fixture.read_text(encoding="utf-8").splitlines()
    target_rows[1] = "https://youtube.com/@Creator.demo_123,,"
    target_rows[2] = "https://www.youtube.com/@other-handle/,,"
    target_rows[3] = "https://youtube.com/channel/UCabcdef/,,"
    target_csv.write_text("\n".join(target_rows) + "\n", encoding="utf-8")
    target_csv.chmod(0o600)
    supported_targets = run([str(seed_script), str(target_csv)], seed_environment)
    assert supported_targets.returncode == 0, supported_targets.stderr

    for invalid_target in (
        "https://user@youtube.com/@creator",
        "https://youtube.com:443/@creator",
        "https://youtube.com/@creator?view=1",
        "https://youtube.com/@creator#section",
    ):
        invalid_target_csv = test_root / ("invalid-target-" + hashlib.sha256(invalid_target.encode()).hexdigest()[:8] + ".csv")
        invalid_target_rows = target_rows.copy()
        invalid_target_rows[1] = invalid_target + ",,"
        invalid_target_csv.write_text("\n".join(invalid_target_rows) + "\n", encoding="utf-8")
        invalid_target_csv.chmod(0o600)
        assert run([str(seed_script), str(invalid_target_csv)], seed_environment).returncode != 0

    rerun = run([str(seed_script), str(csv_path)], seed_environment)
    assert rerun.returncode == 0, rerun.stderr
    rerun_calls = [json.loads(line) for line in (docker_state / "calls.log").read_text().splitlines()]
    assert any(str(report_path) in call and any(value.endswith("report.json") for value in call) for call in rerun_calls)

    saved_report = report_path.read_bytes()
    report_path.chmod(0o644)
    assert run([str(seed_script), str(csv_path)], seed_environment).returncode != 0
    report_path.chmod(0o600)
    report_path.unlink()
    report_path.symlink_to(key_file)
    assert run([str(seed_script), str(csv_path)], seed_environment).returncode != 0
    report_path.unlink()
    report_path.write_bytes(saved_report)
    report_path.chmod(0o600)

    invalid_csv = test_root / "invalid.csv"
    invalid_csv.write_text("wrong,header\nvalue,\n", encoding="utf-8")
    invalid_csv.chmod(0o600)
    invalid = run([str(seed_script), str(invalid_csv)], seed_environment)
    assert invalid.returncode != 0 and "value" not in invalid.stdout + invalid.stderr
    unsafe_csv = test_root / "unsafe.csv"
    shutil.copyfile(fixture, unsafe_csv)
    unsafe_csv.chmod(0o644)
    assert run([str(seed_script), str(unsafe_csv)], seed_environment).returncode != 0
    assert run([str(seed_script), str(test_root / "missing.csv")], seed_environment).returncode != 0
    duplicate_csv = test_root / "duplicate.csv"
    duplicate_rows = fixture.read_text(encoding="utf-8").splitlines()
    duplicate_rows[-1] = duplicate_rows[1]
    duplicate_csv.write_text("\n".join(duplicate_rows) + "\n", encoding="utf-8")
    duplicate_csv.chmod(0o600)
    assert run([str(seed_script), str(duplicate_csv)], seed_environment).returncode != 0
    short_csv = test_root / "short.csv"
    short_csv.write_text("\n".join(duplicate_rows[:10]) + "\n", encoding="utf-8")
    short_csv.chmod(0o600)
    assert run([str(seed_script), str(short_csv)], seed_environment).returncode != 0
    linked_csv = test_root / "linked.csv"
    linked_csv.symlink_to(csv_path)
    assert run([str(seed_script), str(linked_csv)], seed_environment).returncode != 0
    failed_rows = run(
        [str(seed_script), str(csv_path)],
        seed_environment | {"FMG_FAKE_DOCKER_MODE": "failed-rows"},
    )
    assert failed_rows.returncode != 0 and "Safe failure" not in failed_rows.stdout + failed_rows.stderr
    for failure_mode in ("unhealthy", "cli-failure", "copy-failure", "malformed-report"):
        failed = run(
            [str(seed_script), str(csv_path)],
            seed_environment | {"FMG_FAKE_DOCKER_MODE": failure_mode},
        )
        assert failed.returncode != 0, failure_mode
        assert "Safe failure" not in failed.stdout + failed.stderr
    docker_failure = run(
        [str(seed_script), str(csv_path)],
        seed_environment | {"FMG_FAKE_DOCKER_MODE": "docker-failure"},
    )
    assert docker_failure.returncode != 0

    cleanup_start = len((docker_state / "calls.log").read_text().splitlines())
    cleanup_failure = run(
        [str(seed_script), str(csv_path)],
        seed_environment | {"FMG_FAKE_DOCKER_MODE": "cleanup-failure"},
    )
    assert cleanup_failure.returncode != 0
    assert "queued=100" in cleanup_failure.stdout and report_path.is_file()
    assert "temporary container cleanup failed" in cleanup_failure.stderr
    cleanup_failure_calls = [
        json.loads(line)
        for line in (docker_state / "calls.log").read_text().splitlines()[cleanup_start:]
    ]
    failed_cleanup_calls = [call for call in cleanup_failure_calls if "rm" in call or "rmdir" in call]
    assert len(failed_cleanup_calls) == 3
    assert all("/tmp/find-me-gamer-seed-" in " ".join(call) for call in failed_cleanup_calls)
    assert not any("prune" in call for call in failed_cleanup_calls)

    dry_run = run(
        [str(seed_script), str(fixture)],
        os.environ | {"FMG_DRY_RUN": "1"},
    )
    assert dry_run.returncode == 0, dry_run.stderr
    assert "synthetic" in dry_run.stdout.casefold()
    assert "python -m app.cli.seed_creators" in dry_run.stdout

print("PASS: fake-backed smoke secrecy and resumable seed workflow")
PY

if rg -n 'python3' "$smoke_script" "$seed_script"; then
  echo "production operator scripts must not require host python3" >&2
  exit 1
fi
