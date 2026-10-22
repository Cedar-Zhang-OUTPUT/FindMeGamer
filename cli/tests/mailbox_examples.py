"""Compiled CLI selection examples against an offline loopback HTTP fixture.

This checks the client request contract only. Backend/database/queue integration
is covered separately; this fixture never invokes a mail transport.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Thread


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    binary = parser.parse_args().binary.resolve()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, data, meta=None):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": data, "meta": meta or {}}).encode())

        def do_GET(self):
            assert self.path == "/v1/email/mailboxes", self.path
            requests.append(("GET", self.path, None))
            self.respond(
                [
                    {
                        "id": "liminal",
                        "from": "liminal_within@ontologyplay.com",
                        "display_name": "Ontology Play",
                        "enabled": True,
                        "ready": True,
                        "allowed_templates": ["liminal-private-outreach"],
                        "send_interval_seconds": 8,
                        "send_interval_choices_seconds": [8, 9, 10],
                    }
                ],
                {"mailboxes_version": 1},
            )

        def do_POST(self):
            assert self.headers["Authorization"] == "Bearer local-contract-token"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["mailbox_id"] == "liminal"
            assert body["template_id"] == "liminal-private-outreach"
            assert body["template_version"] == "2"
            assert self.path in {"/v1/outreach/tasks", "/v1/email/previews"}, self.path
            if self.path == "/v1/outreach/tasks":
                assert self.headers["Idempotency-Key"] == "liminal-agent-a-batch-01"
                assert self.headers["X-FMG-Run-ID"] == "liminal-agent-a"
            requests.append(("POST", self.path, body))
            self.respond({"id": "frozen-id", "revision": "frozen-revision"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="fmg-mailbox-examples-") as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "server": f"http://127.0.0.1:{server.server_port}",
                        "token": "local-contract-token",
                    }
                )
            )
            config.chmod(0o600)
            env = dict(os.environ, FMG_CONFIG=str(config), FMG_NO_UPDATE_CHECK="1")

            def run(args, expected=0):
                result = subprocess.run(
                    [str(binary), *args],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                assert result.returncode == expected, (
                    args,
                    result.returncode,
                    result.stderr,
                )
                assert "local-contract-token" not in result.stdout + result.stderr
                return result

            assert "liminal" in run(["email", "mailboxes"]).stdout
            selection = [
                "--mailbox",
                "liminal",
                "--template",
                "liminal-private-outreach",
                "--template-version",
                "2",
            ]
            batch = root / "batch.json"
            variables = {
                "creator_name": "Fixture Creator",
                "channel_name": "Fixture Channel",
                "reference_work": "Fixture Mystery",
                "specific_observation": "This offline fixture represents saved creator evidence.",
            }
            batch.write_text(
                json.dumps(
                    {
                        "name": "LIMINAL outreach",
                        "recipients": [
                            {
                                "creator_id": "youtube:fixture",
                                "to": "creator@example.com",
                                "variables": variables,
                            }
                        ],
                    }
                )
            )
            create = [
                "--run-id",
                "liminal-agent-a",
                "outreach",
                "task",
                "create",
                "--input",
                str(batch),
                "--idempotency-key",
                "liminal-agent-a-batch-01",
            ]
            run(create + selection)
            message = root / "message.json"
            message.write_text(
                json.dumps({"to": "creator@example.com", "variables": variables})
            )
            preview = ["email", "preview", "--input", str(message)]
            run(preview + selection)
            count = len(requests)
            run(create, 2)
            run(preview, 2)
            batch.write_text(
                json.dumps(
                    {
                        "mailbox_id": "studio-two",
                        "template_id": "liminal-private-outreach",
                        "template_version": "2",
                        "recipients": [],
                    }
                )
            )
            assert "conflict" in run(create + selection, 2).stderr
            run(
                [
                    "outreach",
                    "task",
                    "start",
                    "frozen-id",
                    "--revision",
                    "frozen-revision",
                    "--confirm",
                    "--mailbox",
                    "studio-two",
                ],
                2,
            )
            run(
                [
                    "email",
                    "send",
                    "--preview-id",
                    "frozen-id",
                    "--confirm",
                    "--idempotency-key",
                    "approved",
                    "--mailbox",
                    "studio-two",
                ],
                2,
            )
            assert len(requests) == count == 3
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "requests": 3,
                        "checks": [
                            "mailbox-discovery",
                            "explicit-task-flags",
                            "explicit-preview-flags",
                            "missing-selection-no-post",
                            "conflict-no-post",
                            "immutable-start-send",
                        ],
                    }
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
