#!/usr/bin/env python3
"""Small local identity index. No network, billing or automatic decisions."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value
    ):
        raise ValueError("Invalid run ID")
    return value


@contextlib.contextmanager
def lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".index.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield root


def atomic(path, data):
    fd, name = tempfile.mkstemp(prefix=".fmg-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def initialize(root, appid, run):
    safe_id(run)
    if not isinstance(appid, str) or not re.fullmatch(r"[1-9][0-9]*", appid):
        raise ValueError("Invalid Steam App ID")
    with lock(root) as root:
        path = root / "creator-index.json"
        if path.exists():
            if json.loads(path.read_text())["app_id"] != appid:
                raise ValueError("Workspace belongs to another game")
        else:
            atomic(path, {"schema_version": 1, "app_id": appid, "accounts": {}})
        for relative in [f"runs/{run}/evidence", f"runs/{run}/matches", "outreach"]:
            (root / relative).mkdir(parents=True, exist_ok=True)
    return {"root": str(root.resolve()), "app_id": appid, "run_id": run}


def index(root, rows):
    if not isinstance(rows, list):
        raise ValueError("Input must be an array")
    with lock(root) as root:
        path = root / "creator-index.json"
        data = json.loads(path.read_text())
        for row in rows:
            platform = row["platform"]
            identity = row["account_id"]
            run = safe_id(row["run_id"])
            status = row["status"]
            if (
                platform not in {"youtube", "x", "twitch", "instagram"}
                or not isinstance(identity, str)
                or not identity.strip()
                or status not in {"seen", "recommended", "rejected", "contacted"}
            ):
                raise ValueError("Invalid identity/status")
            key = platform + ":" + identity
            account = data["accounts"].setdefault(
                key, {"platform": platform, "account_id": identity, "events": []}
            )
            event = {"run_id": run, "status": status}
            if event not in account["events"]:
                account["events"].append(event)
            for field in ("name", "profile_url"):
                if field in row:
                    account[field] = row[field]
        atomic(path, data)
    return {"known_accounts": len(data["accounts"])}


def summary(root, run):
    safe_id(run)
    root = Path(root)
    data = json.loads((root / "creator-index.json").read_text())
    usage = root / "runs" / run / "usage.json"
    counts = {
        status: sum(
            any(e["run_id"] == run and e["status"] == status for e in row["events"])
            for row in data["accounts"].values()
        )
        for status in ("seen", "recommended", "rejected", "contacted")
    }
    return {
        "run_id": run,
        "known_accounts": len(data["accounts"]),
        "counts": counts,
        "usage": json.loads(usage.read_text()) if usage.exists() else None,
    }


def main():
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="command", required=True)
    for command in ("init", "index", "summary"):
        sub = subs.add_parser(command)
        sub.add_argument("--root", type=Path, required=True)
        if command == "init":
            sub.add_argument("--app-id", required=True)
        if command == "index":
            sub.add_argument("--input", type=Path, required=True)
        else:
            sub.add_argument("--run-id", required=True)
    args = p.parse_args()
    try:
        result = (
            initialize(args.root, args.app_id, args.run_id)
            if args.command == "init"
            else (
                index(args.root, json.loads(args.input.read_text()))
                if args.command == "index"
                else summary(args.root, args.run_id)
            )
        )
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except (ValueError, KeyError, TypeError, OSError):
        p.exit(2, "Invalid or unreadable workspace input; existing files retained.\n")


if __name__ == "__main__":
    main()
