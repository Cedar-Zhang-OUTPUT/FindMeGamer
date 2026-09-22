import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import importlib.util
import json


def installer():
    spec = importlib.util.spec_from_file_location("fmg_install", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_latest_ignores_macos_and_drafts_and_sorts_semver():
    assert (
        installer().latest_tag(
            [
                {"tag_name": "v99.0.0"},
                {"tag_name": "fmg-v0.9.0"},
                {"tag_name": "fmg-v0.10.0", "prerelease": True},
                {"tag_name": "fmg-v9.0.0", "draft": True},
            ]
        )
        == "fmg-v0.10.0"
    )


def test_repeated_skill_upgrade_preserves_all_backups(tmp_path):
    module = installer()
    dest = tmp_path / "skills"

    def bundle(text):
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as tar:
            for name in ("fmg-api", "fmg-research"):
                entry = tarfile.TarInfo(name + "/SKILL.md")
                entry.size = len(text)
                tar.addfile(entry, io.BytesIO(text))
        return out.getvalue()

    module.skills(bundle(b"one"), dest)
    module.skills(bundle(b"two"), dest)
    module.skills(bundle(b"three"), dest, "fmg-v0.7.0")
    assert (dest / "fmg-api/SKILL.md").read_bytes() == b"three"
    assert (dest / "fmg-api.previous/SKILL.md").read_bytes() == b"one"
    assert (dest / "fmg-api.previous-1/SKILL.md").read_bytes() == b"two"
    assert json.loads((dest / 'fmg-api/.fmg-release.json').read_text())['version'] == '0.7.0'
    assert json.loads((dest / 'fmg-research/.fmg-release.json').read_text())['version'] == '0.7.0'


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install.py"


def test_offline_install_checks_hash_and_preserves_previous(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    import platform

    system = {"Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}[platform.machine()]
    name = f"fmg_{system}_{arch}.tar.gz"
    asset = release / name
    with tarfile.open(asset, "w:gz") as tar:
        entry = tarfile.TarInfo("fmg")
        entry.size = 3
        entry.mode = 0o755
        tar.addfile(entry, io.BytesIO(b"new"))
    sums = release / "SHA256SUMS"
    sums.write_text(f'{"0"*64}  {name}\n')
    destination = tmp_path / "bin"
    destination.mkdir()
    (destination / "fmg").write_text("old")
    args = [
        sys.executable,
        str(SCRIPT),
        "--release-dir",
        str(release),
        "--bin-dir",
        str(destination),
    ]
    assert subprocess.run(args, capture_output=True).returncode != 0
    assert (destination / "fmg").read_text() == "old"
    sums.write_text(f"{hashlib.sha256(asset.read_bytes()).hexdigest()}  {name}\n")
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (destination / "fmg").read_bytes() == b"new"
    assert os.access(destination / "fmg", os.X_OK)
