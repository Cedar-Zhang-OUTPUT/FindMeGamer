"""Acceptance of actual cross-built assets; opt in with FMG_RELEASE_DIR."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

import pytest


def test_actual_bundle_installs_skills_and_reports_release_version(tmp_path):
    bundle = os.environ.get("FMG_RELEASE_DIR")
    if not bundle:
        pytest.skip("Build release assets and set FMG_RELEASE_DIR")
    root = Path(bundle)
    expected = os.environ.get("FMG_RELEASE_VERSION")
    assert expected, "Set FMG_RELEASE_VERSION to the version being accepted"
    for archive in root.glob("*.tar.gz"):
        with tarfile.open(archive) as source:
            assert all(not Path(e.name).name.startswith("._") for e in source)
    result = subprocess.run(
        [
            sys.executable,
            str(root / "install.py"),
            "--release-dir",
            str(root),
            "--tag", "fmg-v" + expected,
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
    assert expected in version.stdout
    assert (tmp_path / "skills/fmg-api/scripts/outreach_dashboard.html").is_file()
    assert (tmp_path / "skills/fmg-research/scripts/research_dashboard.py").is_file()
    cache = {'tag': 'fmg-v' + expected, 'checked_at': datetime.now(timezone.utc).isoformat()}
    (tmp_path / 'updates.json').write_text(json.dumps(cache))
    env = dict(os.environ, FMG_CONFIG=str(tmp_path / 'config.json'), FMG_SKILL_DIR=str(tmp_path / 'skills'))
    checked = subprocess.run([str(tmp_path / 'bin/fmg'), 'update', 'check'], env=env, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
    status = json.loads(checked.stdout)
    assert status['status'] == 'current'
    assert status['installed_skills'] == {'fmg-api': expected, 'fmg-research': expected}
