import importlib.util
from pathlib import Path
import json
import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "skills/fmg-research/scripts/workspace.py"
)


def module():
    spec = importlib.util.spec_from_file_location("workspace", SCRIPT)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_init_and_index_preserve_history_and_cross_platform_identity(tmp_path):
    w = module()
    w.initialize(tmp_path, "570", "run1")
    profile = tmp_path / "game-profile.md"
    profile.write_text("User edited profile")
    w.initialize(tmp_path, "570", "run2")
    assert profile.read_text() == "User edited profile"
    rows = [
        {
            "platform": "youtube",
            "account_id": "123",
            "name": "Same",
            "status": "seen",
            "run_id": "run1",
        },
        {
            "platform": "x",
            "account_id": "123",
            "name": "Same",
            "status": "recommended",
            "run_id": "run1",
        },
    ]
    w.index(tmp_path, rows)
    w.index(tmp_path, rows)
    w.index(tmp_path, [{**rows[0], "status": "recommended", "run_id": "run2"}])
    data = json.loads((tmp_path / "creator-index.json").read_text())
    assert len(data["accounts"]) == 2
    assert len(data["accounts"]["youtube:123"]["events"]) == 2
    assert len(data["accounts"]["x:123"]["events"]) == 1
    assert w.summary(tmp_path, "run2")["known_accounts"] == 2
    assert w.summary(tmp_path, "run2")["usage"] is None


def test_wrong_game_and_traversal_fail_without_mutation(tmp_path):
    w = module()
    w.initialize(tmp_path, "570", "run1")
    before = (tmp_path / "creator-index.json").read_bytes()
    with pytest.raises(ValueError):
        w.initialize(tmp_path, "571", "run1")
    with pytest.raises(ValueError):
        w.initialize(tmp_path, "570", "../outside")
    with pytest.raises(ValueError):
        w.index(
            tmp_path,
            [
                {
                    "platform": "youtube",
                    "account_id": "",
                    "run_id": "run1",
                    "status": "seen",
                }
            ],
        )
    assert (tmp_path / "creator-index.json").read_bytes() == before


def test_atomic_replacement_failure_preserves_index(tmp_path, monkeypatch):
    w = module()
    w.initialize(tmp_path, "570", "run1")
    before = (tmp_path / "creator-index.json").read_bytes()

    def fail(*args):
        raise OSError("interrupted")

    monkeypatch.setattr(w.os, "replace", fail)
    with pytest.raises(OSError):
        w.index(
            tmp_path,
            [{"platform": "x", "account_id": "1", "run_id": "run1", "status": "seen"}],
        )
    assert (tmp_path / "creator-index.json").read_bytes() == before
