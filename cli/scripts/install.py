#!/usr/bin/env python3
"""Verified explicit-tag installer. Offline bundles supported; no access tokens."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tarfile
import tempfile
import urllib.request

REPO = "Cedar-Zhang-OUTPUT/FindMeGamer"
MAX = 32 * 1024 * 1024


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError("Unsafe redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    if not url.startswith("https://"):
        raise ValueError("HTTPS required")
    with urllib.request.build_opener(HTTPSRedirect()).open(
        urllib.request.Request(url, headers={"User-Agent": "fmg-installer"}), timeout=60
    ) as r:
        data = r.read(MAX + 1)
    if len(data) > MAX:
        raise ValueError("Download too large")
    return data


def verified(read, name, sums):
    expected = {
        line.split()[1]: line.split()[0]
        for line in sums.decode().splitlines()
        if len(line.split()) == 2
    }.get(name)
    data = read(name)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Checksum mismatch; existing installation retained")
    return data


def binary(data, destination):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        entries = tar.getmembers()
        if (
            len(entries) != 1
            or entries[0].name != "fmg"
            or not entries[0].isfile()
            or not 0 < entries[0].size <= MAX
        ):
            raise ValueError("Invalid binary archive")
        payload = tar.extractfile(entries[0]).read(MAX + 1)
    destination.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".fmg-", dir=destination)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), 0o755)
        os.replace(name, destination / "fmg")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def skills(data, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".fmg-skills-", dir=destination
    ) as temporary:
        root = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            total = 0
            for entry in tar:
                parts = Path(entry.name).parts
                if (
                    not parts
                    or parts[0] not in {"fmg-api", "fmg-research"}
                    or ".." in parts
                    or Path(entry.name).is_absolute()
                    or not (entry.isfile() or entry.isdir())
                ):
                    raise ValueError("Unsafe Skill archive")
                total += entry.size
                if total > MAX:
                    raise ValueError("Skill archive too large")
                out = root / entry.name
                if entry.isdir():
                    out.mkdir(parents=True, exist_ok=True)
                else:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(tar.extractfile(entry).read())
        for name in ("fmg-api", "fmg-research"):
            if not (root / name / "SKILL.md").is_file():
                raise ValueError("Incomplete Skill bundle")
        for name in ("fmg-api", "fmg-research"):
            current = destination / name
            backup = destination / (name + ".previous")
            if current.exists():
                if backup.exists():
                    raise ValueError(
                        "Previous Skill backup exists; move it before another update"
                    )
                current.rename(backup)
            try:
                (root / name).rename(current)
            except OSError:
                if backup.exists() and not current.exists():
                    backup.rename(current)
                raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag")
    p.add_argument("--release-dir", type=Path)
    p.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    p.add_argument("--skills", action="store_true")
    p.add_argument("--skill-dir", type=Path, default=Path.home() / ".codex/skills")
    args = p.parse_args()
    try:
        system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
        arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(
            platform.machine()
        )
        if not system or not arch:
            raise ValueError("Unsupported platform")
        if args.release_dir:

            def read(name):
                with (args.release_dir / name).open("rb") as f:
                    data = f.read(MAX + 1)
                if len(data) > MAX:
                    raise ValueError("Asset too large")
                return data

        else:
            if not args.tag or not re.fullmatch(
                r"fmg-v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", args.tag
            ):
                raise ValueError("Specify --tag fmg-vX.Y.Z")
            meta = json.loads(
                fetch(f"https://api.github.com/repos/{REPO}/releases/tags/{args.tag}")
            )
            if meta.get("tag_name") != args.tag:
                raise ValueError("Release tag mismatch")
            assets = {
                a["name"]: a["browser_download_url"]
                for a in meta["assets"]
                if a["browser_download_url"].startswith(
                    f"https://github.com/{REPO}/releases/download/{args.tag}/"
                )
            }
            read = lambda name: fetch(assets[name])
        sums = read("SHA256SUMS")
        data = verified(read, f"fmg_{system}_{arch}.tar.gz", sums)
        skilldata = verified(read, "fmg-skills.tar.gz", sums) if args.skills else None
        if skilldata is not None:
            skills(skilldata, args.skill_dir)
        binary(data, args.bin_dir)
        print(
            json.dumps(
                {
                    "installed": str(args.bin_dir / "fmg"),
                    "skills": str(args.skill_dir) if args.skills else None,
                    "next": "Add bin directory to PATH; authenticate using company HTTPS address and token via stdin. Reload Codex Skills if needed.",
                }
            )
        )
    except Exception:
        p.exit(
            1,
            "Installation failed. Check tag, connection, checksums and destination permissions; no credentials were printed.\n",
        )


if __name__ == "__main__":
    main()
