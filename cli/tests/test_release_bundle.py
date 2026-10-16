"""Acceptance of actual cross-built assets; opt in with FMG_RELEASE_DIR."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import hashlib
from datetime import datetime, timezone

import pytest


def test_actual_bundle_installs_skills_and_reports_release_version(tmp_path):
    bundle = os.environ.get("FMG_RELEASE_DIR")
    if not bundle:
        pytest.skip("Build release assets and set FMG_RELEASE_DIR")
    root = Path(bundle)
    expected = os.environ.get("FMG_RELEASE_VERSION")
    assert expected, "Set FMG_RELEASE_VERSION to the version being accepted"
    required = {
        "fmg_darwin_arm64.tar.gz",
        "fmg_darwin_amd64.tar.gz",
        "fmg_linux_arm64.tar.gz",
        "fmg_linux_amd64.tar.gz",
        "fmg-skills.tar.gz",
        "install.py",
    }
    sums = dict(
        (name, digest)
        for digest, name in (
            line.split() for line in (root / "SHA256SUMS").read_text().splitlines()
        )
    )
    assert set(sums) == required
    for name in required:
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == sums[name]
    config = tmp_path / "config.json"
    authentication = (
        b'{"server":"https://retained.invalid","token":"test-only-retained-token"}\n'
    )
    config.write_bytes(authentication)
    config.chmod(0o600)
    for archive in root.glob("*.tar.gz"):
        with tarfile.open(archive) as source:
            assert all(not Path(e.name).name.startswith("._") for e in source)
    result = subprocess.run(
        [
            sys.executable,
            str(root / "install.py"),
            "--release-dir",
            str(root),
            "--tag",
            "fmg-v" + expected,
            "--skills",
            "--skill-dir",
            str(tmp_path / "skills"),
            "--bin-dir",
            str(tmp_path / "bin"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # Exercise an actual same-version upgrade, with existing authentication and
    # installed Skills, using the verified local bundle and no network calls.
    upgraded = subprocess.run(
        result.args,
        env=dict(os.environ, FMG_CONFIG=str(config)),
        capture_output=True,
        text=True,
    )
    assert upgraded.returncode == 0, upgraded.stderr
    assert config.read_bytes() == authentication
    assert config.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "skills/fmg-api/SKILL.md").is_file()
    assert (tmp_path / "skills/fmg-research/scripts/workspace.py").is_file()
    version = subprocess.run(
        [str(tmp_path / "bin/fmg"), "version"], capture_output=True, text=True
    )
    assert version.returncode == 0
    assert "0.1.0-dev" not in version.stdout
    assert expected in version.stdout
    assert (tmp_path / "skills/fmg-api/scripts/outreach_dashboard.html").is_file()
    assert (tmp_path / "skills/fmg-research/scripts/research_dashboard.py").is_file()
    cache = {
        "tag": "fmg-v" + expected,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "updates.json").write_text(json.dumps(cache))
    env = dict(
        os.environ,
        FMG_CONFIG=str(tmp_path / "config.json"),
        FMG_SKILL_DIR=str(tmp_path / "skills"),
    )
    checked = subprocess.run(
        [str(tmp_path / "bin/fmg"), "update", "check"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stderr
    status = json.loads(checked.stdout)
    assert status["status"] == "current"
    assert status["installed_skills"] == {"fmg-api": expected, "fmg-research": expected}
