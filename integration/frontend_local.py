"""Persistent isolated local HTTP fixture stack for the Electron developer."""

import argparse
import base64
from http.client import RemoteDisconnected
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local/frontend-http"
PROJECT = "fmg-frontend-http"


def initialize(directory, port):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / "client.json"
    if path.exists():
        config = json.loads(path.read_text())
        if config["base_url"] != f"http://127.0.0.1:{port}":
            raise ValueError("Existing fixture configuration uses a different port.")
        return config
    config = {
        "base_url": f"http://127.0.0.1:{port}",
        "workspace_key": secrets.token_urlsafe(32),
    }
    files = {
        "client.json": json.dumps(config, indent=2) + "\n",
        "master.key": base64.b64encode(secrets.token_bytes(32)).decode(),
        "compose.env": f"FMG_FRONTEND_PORT={port}\nFMG_FRONTEND_PRIVATE_DIR={directory}\n",
    }
    for name, contents in files.items():
        with os.fdopen(
            os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as stream:
            stream.write(contents)
    return config


def smoke(config):
    opener = build_opener(ProxyHandler({}))  # localhost must not use the user's VPN
    headers = {"Authorization": f"Bearer {config['workspace_key']}"}
    for route in (
        "/api/v1/session",
        "/api/v1/profiles/games",
        "/api/v1/profiles/creators",
        "/api/v1/profiles/games/10000000-0000-4000-8000-000000000001",
        "/api/v1/profiles/creators/20000000-0000-4000-8000-000000000001",
        "/api/v2/library/games",
    ):
        with opener.open(
            Request(config["base_url"] + route, headers=headers), timeout=5
        ) as response:
            assert response.status == 200
            body = json.load(response)
            if route == "/api/v1/session":
                assert not any(body["service_connections"].values())
    print(
        "PASS: real HTTP session, v1 Library/details, and v2 games; no provider connections."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "smoke", "contract"])
    parser.add_argument("--port", type=int, default=18090)
    args = parser.parse_args()
    config = initialize(PRIVATE, args.port)
    # Only Docker transport/runtime variables are inherited, never app/provider credentials.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        in {"PATH", "HOME", "TMPDIR", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG"}
    }
    compose = [
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--env-file",
        str(PRIVATE / "compose.env"),
        "-f",
        str(ROOT / "integration/compose.frontend.yaml"),
    ]

    def run(*arguments, timeout=180):
        subprocess.run(
            [*compose, *arguments], env=environment, check=True, timeout=timeout
        )

    if args.action == "contract":
        run("config", "--quiet")
    elif args.action == "stop":
        run("down")  # Keep dedicated data and key for the next frontend session.
    elif args.action == "smoke":
        smoke(config)
    else:
        run("build", "api", timeout=900)
        run("up", "-d", "--wait", "postgres", "redis")
        run(
            "run",
            "--rm",
            "--no-deps",
            "api",
            "python",
            "/harness/frontend_runtime.py",
            "seed",
        )
        run("up", "-d", "api")
        for attempt in range(30):
            try:
                smoke(config)
                break
            except (URLError, TimeoutError, RemoteDisconnected):
                if attempt == 29:
                    raise
                time.sleep(1)
        print(f"Fixture API: {config['base_url']}")
        print(
            f"Private client configuration (never paste into chat or commit): {PRIVATE / 'client.json'}"
        )


if __name__ == "__main__":
    main()
