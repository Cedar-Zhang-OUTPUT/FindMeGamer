"""Acceptance of actual cross-built assets; opt in with FMG_RELEASE_DIR."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest


def test_actual_bundle_installs_skills_and_reports_release_version(tmp_path):
    bundle = os.environ.get("FMG_RELEASE_DIR")
    if not bundle:
        pytest.skip("Build release assets and set FMG_RELEASE_DIR")
    root = Path(bundle)
    for archive in root.glob("*.tar.gz"):
        with tarfile.open(archive) as source:
            assert all(not Path(e.name).name.startswith("._") for e in source)
    result = subprocess.run(
        [
            sys.executable,
            str(root / "install.py"),
            "--release-dir",
            str(root),
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
    assert (tmp_path / "skills/fmg-api/SKILL.md").is_file()
    assert (tmp_path / "skills/fmg-research/scripts/workspace.py").is_file()
    version = subprocess.run(
        [str(tmp_path / "bin/fmg"), "version"], capture_output=True, text=True
    )
    assert version.returncode == 0
    assert "0.1.0-dev" not in version.stdout
    assert "0.2.0" in version.stdout
