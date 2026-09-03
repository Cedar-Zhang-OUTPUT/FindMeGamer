#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 - \
  "$repository_root" \
  "${repository_root}/integration/tests/fixtures/fake_docker.py" <<'PY'
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
fake_docker = Path(sys.argv[2])
with tempfile.TemporaryDirectory(prefix="fmg-integration-cleanup-test.") as temporary:
    test_root = Path(temporary)
    binary_dir = test_root / "bin"
    state_dir = test_root / "state"
    binary_dir.mkdir()
    state_dir.mkdir()
    (binary_dir / "docker").symlink_to(fake_docker)
    environment = os.environ.copy()
    environment["PATH"] = f"{binary_dir}:{environment['PATH']}"
    environment["FMG_FAKE_DOCKER_STATE"] = str(state_dir)
    environment["FMG_FAKE_DOCKER_HANG_DOWN"] = "1"
    environment["FMG_INTEGRATION_CLEANUP_TIMEOUT_SECONDS"] = "0.2"
    completed = subprocess.run(
        ["bash", str(root / "integration/run.sh")],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 42, completed.stderr
    calls = (state_dir / "calls.log").read_text(encoding="utf-8").splitlines()
    projects = {
        line.split()[-1]
        .removesuffix("-api:latest")
        .removesuffix("-worker:latest")
        .removesuffix("-beat:latest")
        for line in calls
    }
    assert len(projects) == 1, calls
    project = projects.pop()
    assert calls.count(f"down {project}") == 1, calls
    assert sorted(line for line in calls if line.startswith("image-rm ")) == [
        f"image-rm {project}-api:latest",
        f"image-rm {project}-beat:latest",
        f"image-rm {project}-worker:latest",
    ]
    assert not list(state_dir.glob("*.image")), calls
print("PASS: failed run continues exact image cleanup after bounded down timeout")
PY
