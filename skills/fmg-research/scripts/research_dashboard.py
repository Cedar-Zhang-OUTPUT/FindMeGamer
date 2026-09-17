#!/usr/bin/env python3
"""Read-only local Match Brief viewer. No provider requests or credentials."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
from workspace import safe_id


def snapshot(root, run_id):
    run = (root / "runs" / safe_id(run_id)).resolve()
    if not run.is_relative_to(root.resolve()):
        raise ValueError("Run outside workspace")
    matches, unreadable = [], 0
    for path in sorted((run / "matches").glob("*.json")):
        try:
            if not path.resolve().is_relative_to(run) or path.stat().st_size > 2_000_000:
                raise ValueError("Invalid brief")
            item = json.loads(path.read_text())
            if not isinstance(item, dict) or not isinstance(item.get("creator"), dict) or not isinstance(item.get("match"), dict):
                raise ValueError("Invalid brief")
            matches.append(item)
        except (OSError, ValueError):
            unreadable += 1
    progress = {}
    path = run / "progress.json"
    if path.exists():
        if not path.resolve().is_relative_to(run):
            raise ValueError("Progress outside workspace")
        progress = json.loads(path.read_text())
    return {"run_id": run_id, "matches": matches, "phase": progress.get("phase", "Research in progress"), "unreadable": unreadable}


def serve(root, run_id, port=0):
    root = Path(root).resolve()
    safe_id(run_id)
    if not (root / "runs" / run_id).is_dir():
        raise ValueError("Run does not exist")
    secret = secrets.token_urlsafe(24)
    page = Path(__file__).with_name("research_dashboard.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != origin.removeprefix("http://") or self.headers.get("Origin") not in (None, origin):
                self.send_error(403)
                return
            status = 200
            if self.path == f"/{secret}/":
                body, kind = page, "text/html; charset=utf-8"
            elif self.path == f"/{secret}/data":
                try:
                    body = json.dumps(snapshot(root, run_id)).encode()
                except (OSError, ValueError, TypeError, AttributeError):
                    body, status = b'{"error":"Could not read research files"}', 503
                kind = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/{secret}/", "read_only": True}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    serve(args.root, args.run_id, args.port)
