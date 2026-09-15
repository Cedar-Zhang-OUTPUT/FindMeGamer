from pathlib import Path
import subprocess
import json
import os

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
