#!/usr/bin/env python3
"""Validate and stage ONLY public website files for GitHub Pages."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = ("index.html", "404.html", "favicon.svg", "robots.txt", "sitemap.xml", ".nojekyll")
PUBLIC_DIRS = ("zh", "css", "js", "assets", "vendor", "licenses", "install")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    if out.exists():
        raise SystemExit("Output must be a new directory; refusing to mix old deployment files")
    if out == ROOT or ROOT in out.parents:
        raise SystemExit("Output must be outside website source")
    entry = json.loads((ROOT / "source/findmegamer-assets-copy-20261022/copy/agent-entry.json").read_text())
    if not entry["releaseGate"]["readyForPublicLaunch"]:
        raise SystemExit("Installation guide release gate is closed")
    subprocess.run([sys.executable, str(ROOT / "tools/check.py")], check=True)
    out.mkdir(parents=True)
    for name in PUBLIC_FILES:
        shutil.copy2(ROOT / name, out / name)
    for name in PUBLIC_DIRS:
        for path in (ROOT / name).rglob("*"):
            if path.is_symlink() or path.name.startswith("."):
                raise SystemExit(f"Unexpected hidden file/symlink: {path}")
        shutil.copytree(ROOT / name, out / name)
    files = list(p for p in out.rglob("*") if p.is_file())
    print(f"Staged {len(files)} public files, {sum(p.stat().st_size for p in files):,} bytes: {out}")

if __name__ == "__main__":
    main()
