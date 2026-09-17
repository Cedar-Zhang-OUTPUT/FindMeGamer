#!/usr/bin/env python3
"""Read-only loopback dashboard. Gateway authentication stays inside fmg."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import shutil
import subprocess
from threading import Lock
import time


def serve(task_id, executable, port=0):
    secret = secrets.token_urlsafe(24)
    page = Path(__file__).with_name("outreach_dashboard.html").read_bytes()
    lock = Lock()
    cache = {"at": 0, "body": None, "status": 503}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}"):
                self.send_error(403)
                return
            if self.path == f"/{secret}/":
                body, status, content_type = page, 200, "text/html; charset=utf-8"
            elif self.path == f"/{secret}/data":
                with lock:
                    if time.monotonic() - cache["at"] >= 5:
                        try:
                            command = subprocess.run([executable, "outreach", "task", "get", task_id],
                                                     capture_output=True, timeout=25, check=True)
                            data = json.loads(command.stdout)
                            cache.update(body=json.dumps(data).encode(), status=200)
                        except (subprocess.SubprocessError, ValueError, OSError):
                            cache.update(body=b'{"error":"Refresh failed. Existing display is retained; check fmg auth and service connectivity."}', status=503)
                        cache["at"] = time.monotonic()
                    body, status, content_type = cache["body"], cache["status"], "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-src 'self' about:; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/{secret}/", "task_id": task_id, "read_only": True}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--fmg", default="fmg")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    executable = shutil.which(args.fmg)
    if not executable:
        parser.error("Install fmg or provide --fmg /absolute/path/to/fmg")
    serve(args.task_id, executable, args.port)
