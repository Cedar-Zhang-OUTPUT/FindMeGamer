from pathlib import Path
import subprocess
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_deploy_requires_explicit_apply_before_docker():
    result = subprocess.run(
        ["sh", str(ROOT / "deploy/agent-services/deploy.sh")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "disabled by default" in result.stderr


def test_smoke_rejects_mismatched_cli_target_before_network(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"server": "https://old.example.com", "token": "test-only"})
    )
    result = subprocess.run(
        ["sh", str(ROOT / "deploy/agent-services/smoke.sh"), "https://new.example.com"],
        env=dict(os.environ, FMG_CONFIG=str(config)),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "exact smoke target" in result.stderr


def test_bootstrap_requires_explicit_apply():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "deploy/agent-services/bootstrap_existing.py"),
            "--source-container",
            "not-a-real-container",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "explicit --apply" in result.stderr


def test_backup_rejects_non_project_destination_before_docker():
    result = subprocess.run(
        ["sh", str(ROOT / "deploy/agent-services/backup.sh")],
        env=dict(os.environ, FMG_AGENT_BACKUP_S3="s3://other-project/backups/"),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
