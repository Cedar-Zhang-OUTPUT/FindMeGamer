import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile

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
