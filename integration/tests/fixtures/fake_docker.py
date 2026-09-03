#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


arguments = sys.argv[1:]
state = Path(os.environ["FMG_FAKE_DOCKER_STATE"])
state.mkdir(parents=True, exist_ok=True)


def record(line: str) -> None:
    with (state / "calls.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{line}\n")


if arguments[:2] == ["compose", "version"]:
    raise SystemExit(0)

if arguments[:1] == ["compose"]:
    project = arguments[arguments.index("--project-name") + 1]
    if "config" in arguments:
        port = os.environ["FMG_INTEGRATION_HTTP_PORT"]
        services = {
            name: {} for name in ("proxy", "api", "worker", "beat", "postgres", "redis")
        }
        services["proxy"]["ports"] = [
            {
                "mode": "ingress",
                "target": 8080,
                "published": port,
                "protocol": "tcp",
                "host_ip": "127.0.0.1",
            }
        ]
        print(
            json.dumps(
                {
                    "services": services,
                    "networks": {"backend": {"name": f"{project}-backend"}},
                    "volumes": {
                        name: {"name": f"{project}-{name.replace('_', '-')}"}
                        for name in (
                            "postgres_data",
                            "redis_data",
                            "caddy_data",
                            "caddy_config",
                            "fake_state",
                        )
                    },
                }
            )
        )
        raise SystemExit(0)
    if "build" in arguments:
        for service in ("api", "worker", "beat"):
            (state / f"{service}.image").write_text(project, encoding="utf-8")
        record(f"build-failed {project}")
        raise SystemExit(42)
    if "down" in arguments:
        record(f"down {project}")
        if os.environ.get("FMG_FAKE_DOCKER_HANG_DOWN") == "1":
            time.sleep(10)
        raise SystemExit(0)

if arguments[:2] == ["image", "inspect"]:
    image_name = arguments[-1]
    repository = image_name.removesuffix(":latest")
    project, service = repository.rsplit("-", 1)
    marker = state / f"{service}.image"
    if not marker.exists() or marker.read_text(encoding="utf-8") != project:
        raise SystemExit(1)
    print(f"sha256:fake|{project}|{service}")
    raise SystemExit(0)

if arguments[:2] == ["image", "rm"]:
    image_name = arguments[-1]
    repository = image_name.removesuffix(":latest")
    project, service = repository.rsplit("-", 1)
    marker = state / f"{service}.image"
    if not marker.exists() or marker.read_text(encoding="utf-8") != project:
        raise SystemExit(1)
    marker.unlink()
    record(f"image-rm {image_name}")
    raise SystemExit(0)

record("unexpected-safe-fake-call")
raise SystemExit(2)
