#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 - "$repository_root" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

root = Path(sys.argv[1])
expected = {
    "schema_version": 1,
    "version": "0.4.3",
    "release_page_url": "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.4.3-internal.1",
}


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, capture_output=True, timeout=40, **kwargs)


adapted = json.loads(run([
    "docker", "run", "--rm", "--network", "none",
    "-e", "SERVICE_DOMAIN=44.233.174.193",
    "-v", f"{root / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
    "caddy:2.11.4-alpine", "caddy", "adapt", "--config", "/etc/caddy/Caddyfile",
    "--adapter", "caddyfile",
]).stdout)


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


nodes = list(objects(adapted))
manifest_routes = [
    node for node in nodes
    if any(isinstance(matcher, dict) and matcher.get("path") == ["/updates/macos.json"] for matcher in node.get("match", []))
]
assert len(manifest_routes) == 1, "exact manifest route is missing"
route = manifest_routes[0]
assert route["match"] == [{"method": ["GET", "HEAD"], "path": ["/updates/macos.json"]}]
responses = [node for node in objects(route) if node.get("handler") == "static_response"]
assert len(responses) == 1 and responses[0]["status_code"] == 200
assert json.loads(responses[0]["body"]) == expected
assert any(node.get("path") == ["/api/*", "/r/*", "/health/live", "/health/ready"] for node in nodes)
proxies = [node for node in nodes if node.get("handler") == "reverse_proxy"]
assert len(proxies) == 1 and proxies[0]["upstreams"] == [{"dial": "api:8000"}]
assert any(node.get("body") == "Not Found" and node.get("status_code") == 404 for node in nodes)

# Exercise the production handlers without ACME, Internet, host ports, or the
# actual API. Preserve the handler text; replace only the test listener/upstream.
source = (root / "Caddyfile").read_text(encoding="utf-8")
handlers = source[source.index("\t@backend path "):]
test_config = ":8080 {\n" + handlers.replace("reverse_proxy api:8000", "reverse_proxy 127.0.0.1:8081")
test_config += '\n:8081 {\n\trespond "BACKEND_ROUTE_UNCHANGED" 418\n}\n'

probe = r'''
import http.client, json, time
expected = EXPECTED_MANIFEST

def request(method, path):
    conn = http.client.HTTPConnection("127.0.0.1", 8080, timeout=3)
    try:
        conn.request(method, path)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()

deadline = time.monotonic() + 10
while True:
    try:
        status, headers, body = request("GET", "/updates/macos.json")
        break
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(.1)
assert status == 200 and json.loads(body) == expected
headers = {key.lower(): value for key, value in headers.items()}
assert headers["content-type"] == "application/json; charset=utf-8"
assert headers["cache-control"] == "no-store"
assert headers["x-content-type-options"] == "nosniff"
assert "set-cookie" not in headers and "location" not in headers
status, head_headers, body = request("HEAD", "/updates/macos.json")
assert status == 200 and body == b""
assert {key.lower(): value for key, value in head_headers.items()}["content-type"] == headers["content-type"]
for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
    status, _, body = request(method, "/updates/macos.json")
    assert status == 404 and body == b"Not Found", (method, status, body)
for path in ("/", "/updates", "/updates/", "/updates/macos.json/", "/updates/macos.json.extra", "/updates/other.json", "/source.zip", "/FindMeGamer.dmg"):
    status, _, body = request("GET", path)
    assert status == 404 and body == b"Not Found", (path, status, body)
for path in ("/api/v1/session", "/r/test-token", "/health/live", "/health/ready"):
    status, _, body = request("GET", path)
    assert status == 418 and body == b"BACKEND_ROUTE_UNCHANGED", (path, status, body)
print("PASS: anonymous manifest GET/HEAD, exact path/method isolation, unchanged backend routes")
'''.replace("EXPECTED_MANIFEST", repr(expected))

name = f"fmg-manifest-test-{uuid.uuid4().hex[:12]}"
container_created = False
with tempfile.TemporaryDirectory(prefix="fmg-manifest-test-") as directory:
    config_path = Path(directory) / "Caddyfile"
    config_path.write_text(test_config, encoding="utf-8")
    try:
        run([
            "docker", "run", "-d", "--name", name, "--network", "none",
            "--label", "fmg.test=macos-update-manifest",
            "--tmpfs", "/data", "--tmpfs", "/config",
            "-v", f"{config_path}:/etc/caddy/Caddyfile:ro",
            "caddy:2.11.4-alpine", "caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile",
        ])
        container_created = True
        result = run([
            "docker", "run", "--rm", "-i", "--network", f"container:{name}",
            "python:3.13-slim", "python", "-",
        ], input=probe)
        print(result.stdout.strip())

        # A Git checkout can atomically replace the host file while an existing
        # single-file bind still sees the previous inode. Validate/reload stdin
        # from the current host bytes; a later restart must also read that version.
        identity_before = run(["docker", "inspect", "--format", "{{.Id}} {{.State.StartedAt}}", name]).stdout
        major, minor, patch = map(int, expected["version"].split("."))
        next_version = f"{major}.{minor}.{patch + 1}"
        promoted = dict(expected, version=next_version, release_page_url=f"https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v{next_version}-internal.1")
        promoted_config = test_config.replace(f'"version":"{expected["version"]}"', f'"version":"{next_version}"').replace(expected["release_page_url"], promoted["release_page_url"])
        replacement = Path(directory) / "Caddyfile.next"
        replacement.write_text(promoted_config, encoding="utf-8")
        replacement.replace(config_path)
        run(["docker", "exec", "-i", name, "caddy", "validate", "--config", "-", "--adapter", "caddyfile"], input=config_path.read_text(encoding="utf-8"))
        run(["docker", "exec", "-i", name, "caddy", "reload", "--config", "-", "--adapter", "caddyfile"], input=config_path.read_text(encoding="utf-8"))
        assert run(["docker", "inspect", "--format", "{{.Id}} {{.State.StartedAt}}", name]).stdout == identity_before
        promoted_probe = probe.replace(repr(expected), repr(promoted))
        run(["docker", "run", "--rm", "-i", "--network", f"container:{name}", "python:3.13-slim", "python", "-"], input=promoted_probe)
        run(["docker", "restart", name])
        run(["docker", "run", "--rm", "-i", "--network", f"container:{name}", "python:3.13-slim", "python", "-"], input=promoted_probe)
        assert run(["docker", "inspect", "--format", "{{.Id}}", name]).stdout.strip() == identity_before.split()[0]
        print("PASS: stdin validation/hot reload preserves container; atomic host-file promotion survives restart")
    finally:
        if container_created:
            run(["docker", "rm", "-f", name])
PY
