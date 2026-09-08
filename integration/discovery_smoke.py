"""One-page real-Celery discovery smoke. Default is synthetic local providers."""

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
PIN = "c8abe9b1a00d16ae6ea65117d1ec20b412befce1"
PRIVATE = ROOT / ".local/discovery-smoke"


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


def private_write(path, value):
    with os.fdopen(
        os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
    ) as stream:
        stream.write(value)


def initialize(directory, *, live):
    directory.mkdir(parents=True, mode=0o700)
    directory.chmod(0o700)
    config = {
        "workspace_key": secrets.token_urlsafe(32),
        "mode": "live" if live else "fixture",
    }
    private_write(directory / "client.json", json.dumps(config))
    private_write(
        directory / "master.key", base64.b64encode(secrets.token_bytes(32)).decode()
    )
    return config


def load_credentials(*, live, acknowledge, path):
    if not live:
        if path is not None:
            raise ValueError("Do not supply real credentials in fixture mode.")
        return {"youtube": "fixture-youtube", "x": "fixture-x"}
    if not acknowledge or path is None:
        raise ValueError(
            "Live mode requires explicit cost acknowledgement and a private credential file."
        )
    path = Path(path)
    if (
        path.is_symlink()
        or stat.S_IMODE(path.stat().st_mode) != 0o600
        or path.stat().st_uid != os.getuid()
    ):
        raise ValueError(
            "Credential file must be owned by this user, not a symlink, and mode 0600."
        )
    values = json.loads(path.read_text())
    if set(values) != {"youtube", "x"} or any(
        not isinstance(v, str)
        or not v
        or len(v) > 16384
        or any(ord(c) <= 32 or ord(c) >= 127 for c in v)
        for v in values.values()
    ):
        raise ValueError(
            "Credential file must contain only valid youtube and x secret strings."
        )
    return values


def query_payload(platform, query):
    if platform not in {"youtube", "x"}:
        raise ValueError("Unsupported smoke platform.")
    size, requests = (5, 2) if platform == "youtube" else (10, 1)
    return {
        "providers": [
            {
                "platform": platform,
                "query": query,
                "page_size": size,
                "max_requests": requests,
            }
        ],
        "batch_target": 1,
        "result_limit": size,
        "batch_request_budget": requests,
        "total_request_budget": requests,
        "batch_scan_budget": size,
        "total_scan_budget": size,
    }


def api_request(base, workspace_key, method, path, payload=None):
    headers = {"Authorization": "Bearer " + workspace_key}
    if method == "POST":
        headers["Idempotency-Key"] = secrets.token_urlsafe(24)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(
            Request(base + path, data=data, method=method, headers=headers), timeout=10
        ) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(
            f"Local smoke API returned HTTP {error.code}; no automatic write retry."
        ) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--acknowledge-provider-costs", action="store_true")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--youtube-query", default="indie game")
    parser.add_argument("--x-query", default="indie game")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep only this run's isolated containers for inspection.",
    )
    args = parser.parse_args()
    credentials = load_credentials(
        live=args.live,
        acknowledge=args.acknowledge_provider_costs,
        path=args.credentials_file,
    )
    run_id = secrets.token_hex(4)
    directory = PRIVATE / run_id
    config = initialize(directory, live=args.live)
    source = directory / "source"
    env = docker_environment(os.environ)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(source), PIN],
        cwd=ROOT,
        check=True,
        capture_output=True,
        env=env,
    )
    project = "fmg-discovery-smoke-" + run_id
    private_write(
        directory / "compose.env",
        f"FMG_SMOKE_SOURCE={source}\nFMG_SMOKE_HARNESS={ROOT / 'integration'}\nFMG_SMOKE_PRIVATE={directory}\nFMG_SMOKE_MODE={config['mode']}\n",
    )
    compose = [
        "docker",
        "compose",
        "-p",
        project,
        "--env-file",
        str(directory / "compose.env"),
        "-f",
        str(ROOT / "integration/compose.discovery-smoke.yaml"),
    ]

    def run(*arguments, timeout=120):
        completed = subprocess.run(
            [*compose, *arguments],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if completed.returncode:
            # Do not dump Docker/environment or provider logs into the terminal.
            raise RuntimeError(f"Isolated Docker smoke stage {arguments[0]} failed.")
        return completed.stdout.strip()

    report = {
        "backend_revision": PIN,
        "mode": config["mode"],
        "project": project,
        "providers": {},
    }
    try:
        run("config", "--quiet")
        run("up", "-d", "--wait", "postgres", "redis")
        run(
            "run",
            "--rm",
            "--no-deps",
            "api",
            "python",
            "/harness/discovery_smoke_runtime.py",
            "migrate",
        )
        run("up", "-d", "api", "worker")
        address = run("port", "api", "8000")
        if not address.startswith("127.0.0.1:"):
            raise RuntimeError("Smoke API did not bind loopback.")
        base = "http://" + address
        for attempt in range(45):
            try:
                api_request(base, config["workspace_key"], "GET", "/api/v1/session")
                break
            except (URLError, ConnectionError, RuntimeError):
                if attempt == 44:
                    raise RuntimeError("Isolated API readiness timed out.") from None
                time.sleep(1)
        game = api_request(
            base,
            config["workspace_key"],
            "POST",
            "/api/v2/library/games",
            {"name": "Isolated discovery smoke"},
        )
        activity = api_request(
            base,
            config["workspace_key"],
            "POST",
            "/api/v2/activities",
            {"name": "Bounded provider smoke", "game_id": game["id"]},
        )
        for platform, query in (("youtube", args.youtube_query), ("x", args.x_query)):
            api_request(
                base,
                config["workspace_key"],
                "PUT",
                f"/api/v1/settings/connections/{platform}",
                {"secret": credentials.pop(platform)},
            )
            created = api_request(
                base,
                config["workspace_key"],
                "POST",
                f"/api/v2/activities/{activity['id']}/queries",
                query_payload(platform, query),
            )
            for attempt in range(90):
                state = api_request(
                    base,
                    config["workspace_key"],
                    "GET",
                    f"/api/v2/discovery/queries/{created['query_id']}",
                )
                if state["status"] not in {"queued", "running"}:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Discovery did not reach a bounded terminal state.")
            results = api_request(
                base,
                config["workspace_key"],
                "GET",
                f"/api/v2/discovery/queries/{created['query_id']}/results",
            )
            for item in results["items"]:
                profile = api_request(
                    base,
                    config["workspace_key"],
                    "GET",
                    f"/api/v2/library/creators/{item['creator_id']}",
                )
                if (
                    profile["source_identity"]["account_id"] != item["account_id"]
                    or item["selected"]
                ):
                    raise RuntimeError("Library identity/selection smoke failed.")
            maximum = 2 if platform == "youtube" else 1
            if state["usage"]["requests_used"] > maximum:
                raise RuntimeError("Provider request ceiling exceeded.")
            report["providers"][platform] = {
                "status": state["status"],
                "results": results["total"],
                "usage": state["usage"],
                "source_status": state["sources"].get(platform, {}).get("status"),
                "issues": [
                    i.get("code")
                    for i in state["sources"].get(platform, {}).get("issues", [])
                ],
            }
        if not args.live:
            counts = json.loads(
                run(
                    "exec",
                    "-T",
                    "worker",
                    "python",
                    "-c",
                    "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:18081/stats').read().decode())",
                )
            )
            if counts != {"youtube_search": 1, "youtube_channels": 1, "x_search": 1}:
                raise RuntimeError("Fixture counts did not match one-page limits.")
            if any(p["results"] != 1 for p in report["providers"].values()):
                raise RuntimeError(
                    "Fixture discovery did not publish expected Library results."
                )
            report["fixture_requests"] = counts
        report["completed"] = True
        private_write(directory / "report.json", json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        print(f"Private run files: {directory}")
    finally:
        credentials.clear()
        if not args.keep:
            run("down", "--volumes")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Smoke failed ({type(error).__name__}); no automatic write retry or live fallback.",
            file=sys.stderr,
        )
        sys.exit(1)
