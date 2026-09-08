"""Create/operate only an owned, pinned, synthetic Match frontend fixture stack."""

import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PIN = "cad55656a9a15ef183c6e0ba4ba608bd61a7a1b5"
MIGRATION = "20260908_0012"


def private_write(path, value, *, replace=False):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL)
    with os.fdopen(os.open(path, flags, 0o600), "w") as stream:
        stream.write(value)


def initialize(directory):
    directory = Path(directory).absolute()
    directory.mkdir(mode=0o700, parents=True)
    directory.chmod(0o700)
    run_id = secrets.token_hex(6)
    config = {
        "base_url": None,
        "workspace_key": secrets.token_urlsafe(32),
        "project": "fmg-match-frontend-" + run_id,
        "queue": "match-frontend-" + run_id,
        "backend_revision": PIN,
        "migration": MIGRATION,
    }
    private_write(directory / "client.json", json.dumps(config, indent=2) + "\n")
    private_write(
        directory / "master.key", base64.b64encode(secrets.token_bytes(32)).decode()
    )
    private_write(
        directory / "owner.json",
        json.dumps(
            {
                "kind": "match-frontend-synthetic-v1",
                "directory": str(directory),
                "project": config["project"],
                "revision": PIN,
            }
        ),
    )
    (directory / "state").mkdir(mode=0o700)
    return config


def load_owned(directory):
    directory = Path(directory).absolute()
    try:
        if directory.is_symlink() or directory.stat().st_mode & 0o777 != 0o700:
            raise ValueError()
        for name in ("owner.json", "client.json", "master.key"):
            path = directory / name
            if (
                path.is_symlink()
                or path.stat().st_mode & 0o777 != 0o600
                or path.stat().st_uid != os.getuid()
            ):
                raise ValueError()
        owner = json.loads((directory / "owner.json").read_text())
        config = json.loads((directory / "client.json").read_text())
        if (
            owner["kind"] != "match-frontend-synthetic-v1"
            or owner["directory"] != str(directory)
            or owner["revision"] != PIN
            or config["backend_revision"] != PIN
            or not re.fullmatch(r"fmg-match-frontend-[0-9a-f]{12}", owner["project"])
            or config["project"] != owner["project"]
            or config["queue"] != owner["project"].removeprefix("fmg-")
        ):
            raise ValueError()
        return config
    except (OSError, KeyError, ValueError):
        raise ValueError(
            "Directory is not an owned private Match frontend fixture"
        ) from None


def docker_environment(environment):
    allowed = {
        "PATH",
        "HOME",
        "TMPDIR",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
    }
    return {key: value for key, value in environment.items() if key in allowed}


def command(directory, *arguments, timeout=180):
    config = load_owned(directory)
    argv = [
        "docker",
        "compose",
        "-p",
        config["project"],
        "--env-file",
        str(directory / "compose.env"),
        "-f",
        str(HERE / "compose.yaml"),
        *arguments,
    ]
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        env=docker_environment(os.environ),
        timeout=timeout,
    )
    if result.returncode:
        # Private diagnostics contain Docker output only; never dumped by CLI.
        private_write(directory / "last-docker-error.txt", result.stderr, replace=True)
        raise RuntimeError("Owned Docker stage failed: " + arguments[0])
    return result.stdout.strip()


def request(config, method, path, payload=None):
    headers = {"Authorization": "Bearer " + config["workspace_key"]}
    if method == "POST":
        headers["Idempotency-Key"] = secrets.token_urlsafe(24)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    try:
        with build_opener(ProxyHandler({})).open(
            Request(
                config["base_url"] + path, data=data, headers=headers, method=method
            ),
            timeout=10,
        ) as response:
            return json.load(response)
    except HTTPError as error:
        # Only the HTTP status is reportable, never request/response bodies.
        raise RuntimeError(f"Fixture API returned HTTP {error.code}") from None


def start(directory):
    config = load_owned(directory)
    source = directory / "source"
    if not source.exists():
        source.mkdir(mode=0o700)
        archive = subprocess.run(
            ["git", "archive", PIN, "backend"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
            bundle.extractall(source, filter="data")
    private_write(
        directory / "compose.env",
        f"FMG_MATCH_SOURCE={source}\nFMG_MATCH_HARNESS={HERE}\nFMG_MATCH_PRIVATE={directory}\nFMG_MATCH_QUEUE={config['queue']}\nFMG_MATCH_IMAGE={config['project']}:cad5565\n",
        replace=True,
    )
    command(directory, "config", "--quiet")
    command(directory, "build", "api", timeout=900)
    command(directory, "up", "-d", "--wait", "postgres", "redis")
    command(
        directory,
        "run",
        "--rm",
        "--no-deps",
        "api",
        "python",
        "/harness/runtime.py",
        "migrate",
    )
    command(directory, "up", "-d", "api", "worker", "relay")
    address = command(directory, "port", "relay", "8000")
    if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", address):
        raise RuntimeError("Fixture API is not loopback-only")
    config["base_url"] = "http://" + address
    private_write(
        directory / "client.json", json.dumps(config, indent=2) + "\n", replace=True
    )
    for attempt in range(45):
        try:
            request(config, "GET", "/api/v1/session")
            break
        except (URLError, ConnectionError, RuntimeError):
            if attempt == 44:
                raise RuntimeError("Fixture API readiness timed out") from None
            time.sleep(1)
    for service in ("youtube", "x", "deepseek"):
        request(
            config,
            "PUT",
            f"/api/v1/settings/connections/{service}",
            {"secret": f"synthetic-match-{service}"},
        )
    if "game_id" not in config:
        game = request(
            config,
            "POST",
            "/api/v2/library/games",
            {
                "name": "Moonseed Garden Together",
                "description": "A synthetic cozy cooperative adventure about restoring floating gardens, growing unusual plants, and exploring with friends.",
                "developer": "Synthetic Orchard Studio",
                "tags": ["Cozy", "Cooperative", "Gardening", "Exploration"],
                "languages": ["English"],
                "reference_works": [
                    {
                        "name": "Cloud Orchard Companions",
                        "similarities": ["Cooperative gardening", "Gentle exploration"],
                        "reason": "A synthetic reference illustrating the desired cooperative cozy audience.",
                    }
                ],
            },
        )
        config["game_id"] = game["id"]
        config["reference_work_ids"] = [item["id"] for item in game["reference_works"]]
        private_write(
            directory / "client.json", json.dumps(config, indent=2) + "\n", replace=True
        )
    return config


def public_status(directory, config):
    return {
        key: config.get(key)
        for key in (
            "base_url",
            "project",
            "queue",
            "backend_revision",
            "migration",
            "game_id",
        )
    } | {"client_file": str(directory / "client.json")}


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["start", "status", "stop", "control", "smoke", "failures"]
    )
    parser.add_argument("--directory", type=Path)
    parser.add_argument(
        "--source-fail", choices=["none", "youtube", "x"], default="none"
    )
    parser.add_argument(
        "--model-fail",
        choices=["none", "all", "planning", "screening", "deep", "ranking"],
        default="none",
    )
    parser.add_argument(
        "--hold",
        choices=["none", "youtube", "x", "planning", "screening", "deep", "ranking"],
        default="none",
    )
    args = parser.parse_args(arguments)
    directory = args.directory
    if directory is None:
        if args.action != "start":
            parser.error("An owned --directory is required")
        directory = Path(tempfile.mkdtemp(prefix="fmg-match-frontend-")) / "private"
        initialize(directory)
    directory = directory.absolute()
    config = load_owned(directory)
    if args.action == "start":
        config = start(directory)
    elif args.action == "stop":
        command(
            directory, "stop"
        )  # Volumes, credentials, and current data are retained.
    elif args.action == "control":
        from fixture import write_control

        write_control(
            directory / "state",
            {
                "source_fail": args.source_fail,
                "model_fail": args.model_fail,
                "hold": args.hold,
            },
        )
    elif args.action == "smoke":
        from smoke import run

        print(json.dumps(run(directory), indent=2))
    elif args.action == "failures":
        from failure_smoke import run

        print(json.dumps(run(directory), indent=2))
    print(json.dumps(public_status(directory, config), indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Match fixture failed ({type(error).__name__}); inspect only owned private diagnostics.",
            file=sys.stderr,
        )
        sys.exit(1)
