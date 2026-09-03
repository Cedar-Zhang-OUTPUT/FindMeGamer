#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
checklist="${repository_root}/docs/release-checklist.md"
recorder="${repository_root}/ops/record_release_evidence.sh"

[[ -f "$checklist" ]] || { echo "missing docs/release-checklist.md" >&2; exit 1; }
[[ -x "$recorder" ]] || { echo "missing executable ops/record_release_evidence.sh" >&2; exit 1; }

python3 - "$checklist" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
ids = [
    "workspace-key", "steam-analyze", "youtube-analyze", "library",
    "reanalyze", "creator-seed", "three-stage-match", "outreach",
    "accepted", "declined", "duplicate-send", "cloud-continuation",
    "offline-reconnect", "macos-14", "macos-26", "backup-restore",
    "master-key-recovery",
]
found = re.findall(r"(?m)^- id: ([a-z0-9-]+)$", text)
assert found == ids, (found, ids)
assert len(found) == len(set(found)) == 17
sections = re.split(r"(?m)^## Scenario: ", text)[1:]
assert len(sections) == 17
required = [
    "Responsible operator", "UTC timestamp", "Environment/device/OS",
    "Prerequisites/test data", "Steps", "Expected outcome", "Actual outcome",
    "Evidence filenames",
]
for expected_id, section in zip(ids, sections):
    assert section.startswith(expected_id + "\n")
    assert f"- id: {expected_id}\n" in section
    for field in required:
        assert section.count(f"- {field}:") == 1, (expected_id, field)
    assert section.count("- [ ] PASS") == 1
    assert section.count("- [ ] FAIL") == 1
    assert "- [x] PASS" not in section.lower()
    assert "- [x] FAIL" not in section.lower()

for field in [
    "Release version", "Immutable deployed commit", "Service HTTPS origin",
    "Release artifact", "Release checksum", "EC2 environment label",
    "UTC start time", "UTC completion time", "Primary operator",
    "Independent witness", "Final release decision",
]:
    assert text.count(f"- {field}:") == 1, field

assert "- [ ] Primary operator approval" in text
assert "- [ ] Independent witness approval" in text
assert not re.search(r"(?mi)^\s*- \[[xX]\]", text)
required_phrases = [
    "exactly 100", "zero unresolved", "Steam", "YouTube", "three-stage",
    "coarse screening", "deep comparisons", "final ordering",
    "numeric rank", "numeric score", "cloud continuation", "NetEase",
    "individual", "batch", "Accepted", "Declined", "duplicate",
    "controlled company/test mailboxes", "macOS 14", "macOS 26",
    "Liquid Glass", "Alembic", "required tables", "password manager",
    "not S3", "no coworker distribution",
]
for phrase in required_phrases:
    assert phrase in text, phrase
assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
print("PASS: exact unchecked 17-scenario checklist contract")
PY

rg -Fq -- '--env-file /etc/find-me-gamer/app.env' "$recorder"
! rg -n 'source[[:space:]]+|(^|[[:space:]])\.[[:space:]]+/etc/find-me-gamer/app\.env|eval[[:space:]]' "$recorder"
for forbidden in backup_postgres restore_rehearsal seed_initial_creators smoke_test \
  '/api/v1/analyze' '/api/v1/matches' '/api/v1/outreach' 'POST'; do
  ! rg -Fq "$forbidden" "$recorder"
done

dry_output="$(cd "$repository_root" && FMG_DRY_RUN=1 "$recorder" 0.1.0)"
[[ ! -e "${repository_root}/release/evidence" ]]
for name in deployed-commit.txt compose-services.json alembic-revision.txt \
  health-live.json health-ready.json release-artifact.txt \
  release-verification.json restore-summary.json release-checklist.md; do
  [[ "$(grep -Fxc "release/evidence/0.1.0/${name}" <<<"$dry_output")" -eq 1 ]]
done
[[ "$(grep -Fxc 'PLAN: read-only deployed commit, Compose status, migration revision, public health, release trust, restore summary, and checklist snapshot' <<<"$dry_output")" -eq 1 ]]
[[ "$(grep -Fxc 'PASS' <<<"$dry_output")" -eq 1 ]]

python3 - "$repository_root" "$checklist" "$recorder" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

root, checklist_source, recorder_source = map(Path, sys.argv[1:])
version = "1.2.3"
commit = "873de990d22d3d27e125c99396595965cd3e4220"
origin = "https://release.test"
host = "operator@evidence.test"
scenario_ids = [
    "workspace-key", "steam-analyze", "youtube-analyze", "library",
    "reanalyze", "creator-seed", "three-stage-match", "outreach",
    "accepted", "declined", "duplicate-send", "cloud-continuation",
    "offline-reconnect", "macos-14", "macos-26", "backup-restore",
    "master-key-recovery",
]


def run(script: Path, env: dict[str, str], *args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), *args], cwd=script.parents[1], env=env, text=True,
        capture_output=True, timeout=timeout,
    )


fake_curl = r'''#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
log = pathlib.Path(os.environ["FMG_FAKE_COMMAND_LOG"])
with log.open("a", encoding="utf-8") as stream: stream.write("curl " + json.dumps(args) + "\n")
if os.environ.get("FMG_FAKE_MODE") == "curl-failure": raise SystemExit(7)
if os.environ.get("FMG_FAKE_MODE") == "hang": time.sleep(20)
assert args[0] in ("--disable", "-q")
assert args[args.index("--request") + 1] == "GET"
assert args[args.index("--proto") + 1] == "=https"
assert args[args.index("--max-redirs") + 1] == "0"
assert "--location" not in args and "--config" not in args
output = pathlib.Path(args[args.index("--output") + 1])
if os.environ.get("FMG_FAKE_MODE") == "unsafe-health":
    output.write_text('{"status":"ok","password":"SECRET-CANARY"}', encoding="utf-8")
elif os.environ.get("FMG_FAKE_MODE") == "malformed-health":
    output.write_text('not-json', encoding="utf-8")
else:
    output.write_text('{"status":"ok"}', encoding="utf-8")
sys.stdout.write("200")
'''

fake_docker = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
log = pathlib.Path(os.environ["FMG_FAKE_COMMAND_LOG"])
with log.open("a", encoding="utf-8") as stream: stream.write("docker " + json.dumps(args) + "\n")
mode = os.environ.get("FMG_FAKE_MODE")
if mode == "compose-secret":
    for service in ["proxy", "api", "worker", "beat", "postgres", "redis"]:
        item = {"Service":service,"State":"running","Health":"healthy"}
        if service == "api": item["Password"] = "SECRET-CANARY"
        print(json.dumps(item))
    raise SystemExit(0)
if mode == "compose-malformed": print("not-json"); raise SystemExit(0)
if mode == "compose-unhealthy":
    health = "unhealthy"
else: health = "healthy"
for service in ["proxy", "api", "worker", "beat", "postgres", "redis"]:
    print(json.dumps({"Service":service,"State":"running","Health":health,"Name":"ignored"}))
'''

fake_ssh = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
log = pathlib.Path(os.environ["FMG_FAKE_COMMAND_LOG"])
with log.open("a", encoding="utf-8") as stream: stream.write("ssh " + json.dumps(args) + "\n")
mode = os.environ.get("FMG_FAKE_MODE")
if mode == "ssh-failure": raise SystemExit(8)
if mode == "hang": time.sleep(20)
remote = args[-1]
assert "source " not in remote
if "git rev-parse HEAD" in remote:
    print("BAD-COMMIT" if mode == "bad-commit" else os.environ["FMG_FAKE_COMMIT"])
elif " ps --format json " in remote:
    assert "--env-file /etc/find-me-gamer/app.env" in remote
    raise SystemExit(subprocess.run([os.environ["FMG_DOCKER_BIN"]], env=os.environ).returncode)
elif "alembic current" in remote:
    assert "--env-file /etc/find-me-gamer/app.env" in remote
    if mode == "revision-secret": print("password=SECRET-CANARY")
    elif mode == "bad-revision": print("two lines\nsecond")
    else: print("20260902_0005 (head)")
else:
    raise SystemExit(19)
'''

fake_verify = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
log = pathlib.Path(os.environ["FMG_FAKE_COMMAND_LOG"])
with log.open("a", encoding="utf-8") as stream: stream.write("verify " + json.dumps(args) + "\n")
mode = os.environ.get("FMG_FAKE_MODE")
if mode == "verify-failure": raise SystemExit(9)
if mode == "verify-secret": print("password=SECRET-CANARY"); raise SystemExit(0)
if mode == "verify-malformed": print("looks good"); raise SystemExit(0)
print("PASS checksum")
print("PASS Developer ID, Gatekeeper, and stapled ticket verification")
print("Verified: " + args[0])
'''


def complete_checklist(source: str, archive: str, digest: str) -> str:
    replacements = {
        "Release version": version,
        "Immutable deployed commit": commit,
        "Service HTTPS origin": origin,
        "Release artifact": archive,
        "Release checksum": digest,
        "EC2 environment label": "internal-production",
        "UTC start time": "2026-09-03T01:00:00Z",
        "UTC completion time": "2026-09-03T02:00:00Z",
        "Primary operator": "Operator One",
        "Independent witness": "Witness Two",
        "Final release decision": "PASS",
    }
    text = source
    for field, value in replacements.items():
        text = re.sub(rf"(?m)^- {re.escape(field)}:.*$", f"- {field}: {value}", text)
    for field, value in [
        ("Responsible operator", "Operator One"),
        ("UTC timestamp", "2026-09-03T01:30:00Z"),
        ("Environment/device/OS", "internal-production / controlled device"),
        ("Actual outcome", "Observed the expected safe outcome."),
        ("Evidence filenames", "scenario-note.txt"),
    ]:
        text = re.sub(rf"(?m)^- {re.escape(field)}:.*$", f"- {field}: {value}", text)
    text = text.replace("- [ ] PASS", "- [x] PASS")
    text = text.replace(
        "- [ ] Primary operator approval — name / UTC: ___",
        "- [x] Primary operator approval — name / UTC: Operator One / 2026-09-03T02:05:00Z",
    )
    text = text.replace(
        "- [ ] Independent witness approval — name / UTC: ___",
        "- [x] Independent witness approval — name / UTC: Witness Two / 2026-09-03T02:06:00Z",
    )
    return text


with tempfile.TemporaryDirectory(prefix="fmg-task9-test.") as temporary:
    test_root = Path(temporary)
    repo = test_root / "repo"
    for directory in ["ops", "docs", "script", "release"]:
        (repo / directory).mkdir(parents=True, exist_ok=True)
    (repo / "compose.yaml").write_text("# repository-owned synthetic fixture\n", encoding="utf-8")
    recorder = repo / "ops/record_release_evidence.sh"
    checklist = repo / "docs/release-checklist.md"
    shutil.copy2(recorder_source, recorder)
    shutil.copy2(checklist_source, checklist)
    recorder.chmod(0o700)

    tools = test_root / "tools"
    tools.mkdir()
    scripts = {"curl": fake_curl, "docker": fake_docker, "ssh": fake_ssh, "verify": fake_verify}
    for name, content in scripts.items():
        path = tools / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o700)

    archive = repo / f"release/FindMeGamer-{version}.zip"
    archive.write_bytes(b"synthetic signed release archive\n")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sidecar = archive.with_suffix(".zip.sha256")
    sidecar.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    restore = repo / f"release/restore-result-{version}.txt"
    restore.write_text("result=PASS\nalembic_revision=20260902_0005\nrequired_table_count=6\n", encoding="utf-8")
    checklist.write_text(complete_checklist(checklist.read_text(), f"release/{archive.name}", digest), encoding="utf-8")
    log = test_root / "commands.log"
    log.write_text("", encoding="utf-8")

    base_env = os.environ.copy()
    for name in [
        "WORKSPACE_ACCESS_KEY", "FMG_WORKSPACE_ACCESS_KEY", "FMG_WORKSPACE_KEY",
        "WORKSPACE_KEY", "FMG_WORKSPACE_KEY_FILE", "API_KEY", "OPENAI_API_KEY",
        "STEAM_API_KEY", "YOUTUBE_API_KEY", "DEEPSEEK_API_KEY", "SMTP_PASSWORD",
        "SMTP_USERNAME", "NETEASE_PASSWORD", "FMG_MASTER_KEY", "MASTER_KEY",
        "MASTER_KEY_FILE", "RESPONSE_TOKEN", "RESPONSE_CAPABILITY", "RECIPIENT_EMAIL",
        "EMAIL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        "DATABASE_URL",
    ]:
        base_env.pop(name, None)
    base_env.update({
        "FMG_RELEASE_EVIDENCE_TEST_MODE": "1",
        "FMG_SSH_BIN": str(tools / "ssh"),
        "FMG_CURL_BIN": str(tools / "curl"),
        "FMG_DOCKER_BIN": str(tools / "docker"),
        "FMG_VERIFY_RELEASE_BIN": str(tools / "verify"),
        "FMG_EC2_HOST": host,
        "SERVICE_BASE_URL": origin,
        "FMG_RESTORE_RESULT_FILE": str(restore),
        "FMG_FAKE_COMMAND_LOG": str(log),
        "FMG_FAKE_COMMIT": commit,
        "FMG_EVIDENCE_COMMAND_TIMEOUT_SECONDS": "1",
    })

    success = run(recorder, base_env, version)
    assert success.returncode == 0, success.stderr
    destination = repo / f"release/evidence/{version}"
    expected_files = {
        "deployed-commit.txt", "compose-services.json", "alembic-revision.txt",
        "health-live.json", "health-ready.json", "release-artifact.txt",
        "release-verification.json", "restore-summary.json", "release-checklist.md",
    }
    assert {entry.name for entry in destination.iterdir()} == expected_files
    assert destination.stat().st_mode & 0o077 == 0
    assert (destination / "deployed-commit.txt").read_text() == commit + "\n"
    services = json.loads((destination / "compose-services.json").read_text())
    assert [item["service"] for item in services] == ["api", "beat", "postgres", "proxy", "redis", "worker"]
    assert all(set(item) == {"service", "state", "health"} for item in services)
    assert json.loads((destination / "health-live.json").read_text()) == {"status": "ok"}
    assert json.loads((destination / "health-ready.json").read_text()) == {"status": "ok"}
    assert json.loads((destination / "release-verification.json").read_text()) == {
        "checksum": True, "codesign": True, "gatekeeper": True, "stapled_ticket": True,
    }
    assert (destination / "release-artifact.txt").read_text() == f"archive={archive.name}\nsha256={digest}\n"
    assert json.loads((destination / "restore-summary.json").read_text()) == {
        "alembic_revision": "20260902_0005", "required_table_count": 6, "result": "PASS",
    }
    assert (destination / "release-checklist.md").read_bytes() == checklist.read_bytes()
    assert "SECRET" not in "".join(path.read_text() for path in destination.iterdir())
    output_lines = success.stdout.splitlines()
    assert output_lines[0] == f"release/evidence/{version}/"
    assert set(output_lines[1:-1]) == expected_files
    assert output_lines[-1] == "PASS"
    calls = log.read_text()
    assert "--env-file /etc/find-me-gamer/app.env" in calls
    assert "source " not in calls and "POST" not in calls
    assert not any(path.name.startswith(".tmp-") for path in destination.parent.iterdir())

    # Refusal to overwrite preserves prior immutable evidence.
    marker = destination / "deployed-commit.txt"
    original = marker.read_bytes()
    repeat = run(recorder, base_env, version)
    assert repeat.returncode != 0 and marker.read_bytes() == original

    shutil.rmtree(destination)
    completed = checklist.read_text()

    # Mutable checklist values are validated before any external capture.
    calls_before_field_validation = log.read_text()
    invalid_completed_checklists = [
        ("absolute response capability URL", completed.replace(
            "- Actual outcome: Observed the expected safe outcome.",
            "- Actual outcome: https://release.test/r/opaque-capability?choice=accepted",
            1,
        )),
        ("relative response capability", completed.replace(
            "- Actual outcome: Observed the expected safe outcome.",
            "- Actual outcome: Observed /r/opaque-capability without copying it.",
            1,
        )),
        ("uppercase password assignment", completed.replace(
            "- Environment/device/OS: internal-production / controlled device",
            "- Environment/device/OS: POSTGRES_PASSWORD=SECRET-CANARY",
            1,
        )),
        ("scenario operator placeholder", completed.replace("- Responsible operator: Operator One", "- Responsible operator: TBD", 1)),
        ("scenario timestamp placeholder", completed.replace("- UTC timestamp: 2026-09-03T01:30:00Z", "- UTC timestamp: TBD", 1)),
        ("scenario environment placeholder", completed.replace(
            "- Environment/device/OS: internal-production / controlled device",
            "- Environment/device/OS: N/A",
            1,
        )),
        ("scenario actual placeholder", completed.replace(
            "- Actual outcome: Observed the expected safe outcome.",
            "- Actual outcome: TODO",
            1,
        )),
        ("header operator placeholder", completed.replace("- Primary operator: Operator One", "- Primary operator: TBD", 1)),
        ("sign-off placeholder", completed.replace(
            "- [x] Primary operator approval — name / UTC: Operator One / 2026-09-03T02:05:00Z",
            "- [x] Primary operator approval — name / UTC: ___ / 2026-09-03T02:05:00Z",
            1,
        )),
        ("sign-off identity mismatch", completed.replace(
            "- [x] Independent witness approval — name / UTC: Witness Two / 2026-09-03T02:06:00Z",
            "- [x] Independent witness approval — name / UTC: Someone Else / 2026-09-03T02:06:00Z",
            1,
        )),
    ]
    for label, invalid_checklist in invalid_completed_checklists:
        checklist.write_text(invalid_checklist, encoding="utf-8")
        rejected = run(recorder, base_env, version)
        assert rejected.returncode != 0, label
        assert "SECRET-CANARY" not in rejected.stdout + rejected.stderr
        assert not destination.exists()
        assert log.read_text() == calls_before_field_validation

    # Ordinary Unicode names and environment descriptions remain accepted.
    unicode_completed = completed.replace("Operator One", "操作员甲")
    unicode_completed = unicode_completed.replace("Witness Two", "Witness Élodie 二")
    unicode_completed = unicode_completed.replace(
        "internal-production / controlled device", "生产环境 / controlled Mac"
    )
    checklist.write_text(unicode_completed, encoding="utf-8")
    unicode_success = run(recorder, base_env, version)
    assert unicode_success.returncode == 0, unicode_success.stderr
    assert destination.exists()
    shutil.rmtree(destination)
    checklist.write_text(completed, encoding="utf-8")

    scenarios = [
        ("ssh-failure", "deployed commit"),
        ("bad-commit", "deployed commit"),
        ("compose-malformed", "Compose"),
        ("compose-unhealthy", "Compose"),
        ("compose-secret", "Compose"),
        ("bad-revision", "Alembic"),
        ("revision-secret", "Alembic"),
        ("curl-failure", "health"),
        ("malformed-health", "health"),
        ("unsafe-health", "health"),
        ("verify-failure", "release verification"),
        ("verify-malformed", "release verification"),
        ("verify-secret", "release verification"),
        ("hang", "timed out"),
    ]
    for mode, stage in scenarios:
        env = base_env | {"FMG_FAKE_MODE": mode}
        failed = run(recorder, env, version, timeout=8)
        assert failed.returncode != 0, mode
        assert stage.lower() in failed.stderr.lower(), (mode, failed.stderr)
        assert "SECRET-CANARY" not in failed.stdout + failed.stderr
        assert not destination.exists()
        evidence_root = destination.parent
        if evidence_root.exists():
            assert not any(path.name.startswith(".tmp-") for path in evidence_root.iterdir())

    # Input validation occurs before capture and never leaks forbidden input.
    before_calls = log.read_text()
    invalid_cases = [
        ("01.2.3", base_env, "version"),
        (version, base_env | {"SERVICE_BASE_URL": "http://release.test"}, "HTTPS"),
        (version, base_env | {"FMG_EC2_HOST": "operator@localhost"}, "SSH"),
        (version, base_env | {"WORKSPACE_ACCESS_KEY": "SECRET-CANARY"}, "sensitive"),
    ]
    for supplied_version, env, stage in invalid_cases:
        failed = run(recorder, env, supplied_version)
        assert failed.returncode != 0 and stage.lower() in failed.stderr.lower()
        assert "SECRET-CANARY" not in failed.stdout + failed.stderr
    assert log.read_text() == before_calls

    # Incomplete checklist, mismatched checksum, unsafe restore and path escapes fail pre-capture.
    checklist.write_text(completed.replace("- [x] PASS", "- [ ] PASS", 1), encoding="utf-8")
    assert run(recorder, base_env, version).returncode != 0
    checklist.write_text(completed, encoding="utf-8")
    sidecar.write_text(f"{'0' * 64}  {archive.name}\n", encoding="utf-8")
    assert run(recorder, base_env, version).returncode != 0
    sidecar.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    outside = test_root / "restore.txt"
    outside.write_text(restore.read_text(), encoding="utf-8")
    assert run(recorder, base_env | {"FMG_RESTORE_RESULT_FILE": str(outside)}, version).returncode != 0
    restore.unlink()
    restore.symlink_to(outside)
    assert run(recorder, base_env, version).returncode != 0
    restore.unlink()
    restore.write_text("result=PASS\nalembic_revision=20260902_0005\nrequired_table_count=6\nextra=unsafe\n")
    assert run(recorder, base_env, version).returncode != 0
    assert log.read_text() == before_calls

print("PASS: fake-backed sanitized atomic evidence recorder contracts")
PY

echo "PASS: release checklist and evidence recorder"
