"""Direct smoke helper contracts; HTTP sockets are local, no worker substitute."""

from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
B = "ece2e9d9558dfe057dc40ad58bd98a86e3149dd5"
ACTIVITY = "11111111-1111-4111-8111-111111111111"
COMPOSITION = "22222222-2222-4222-8222-222222222222"


class OutreachSmokeContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / "outreach_smoke.py").exists(), "Real HTTP outreach smoke is missing")
        spec = importlib.util.spec_from_file_location("outreach_smoke_contract", HERE / "outreach_smoke.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)

    def config(self, origin="http://127.0.0.1:62001"):
        return {"backend_revision": B, "migration": "20260908_0017", "base_url": origin, "workspace_key": "synthetic-local-http-key"}

    def server(self):
        class Boundary(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.server.requests.append((self.command, self.path, dict(self.headers), json.loads(body)))
                self.send_response(self.server.status)
                self.send_header("Content-Type", "application/json")
                if self.server.status == 302:
                    self.send_header("Location", self.server.origin + "/forbidden-redirect")
                self.end_headers()
                self.wfile.write(json.dumps(self.server.response).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Boundary)
        server.origin = f"http://127.0.0.1:{server.server_port}"
        server.requests, server.status, server.response = [], 201, {"id": COMPOSITION}
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def eml(self, name):
        message = EmailMessage()
        message["From"] = "Toki <sender@example.com>"
        message["To"] = "synthetic@example.com"
        message["Subject"] = "Synthetic capture"
        message.set_content("Synthetic body")
        message.add_alternative("<p>Synthetic body</p>", subtype="html")
        path = self.state / name
        path.write_bytes(message.as_bytes())
        path.chmod(0o600)
        return path

    def test_only_fixed_b_and_a_new_loopback_origin_are_accepted(self):
        self.module.validate_config(self.config())
        cases = [
            {**self.config(), "backend_revision": "HEAD"},
            {**self.config(), "migration": "20260908_0016"},
            {**self.config(), "workspace_key": ""},
        ]
        for origin in ("https://example.com", "http://localhost:62001", "http://127.0.0.1:65164", "http://127.0.0.1:18090", "http://127.0.0.1:53251", "http://127.0.0.1:59414", "http://user:secret@127.0.0.1:62001", "http://127.0.0.1:62001/path"):
            cases.append(self.config(origin))
        for config in cases:
            with self.subTest(origin=config["base_url"]):
                with self.assertRaises(self.module.SmokeError) as error:
                    self.module.validate_config(config)
                self.assertNotIn("secret", str(error.exception))

    def test_http_post_preserves_exact_final_body_and_explicit_replay_key(self):
        server = self.server()
        api = self.module.API(self.config(server.origin))
        path = f"/api/v2/outreach/compositions/{COMPOSITION}/send-batches"
        body = {"request_id": ACTIVITY, "qualification_token": "a" * 64, "excluded": []}
        first = api.request("POST", path, body, key="synthetic-replay-key")
        second = api.request("POST", path, body, key="synthetic-replay-key")
        self.assertEqual(first, {"id": COMPOSITION})
        self.assertEqual(second, first)
        self.assertEqual(len(server.requests), 2)
        for method, seen_path, headers, observed in server.requests:
            self.assertEqual((method, seen_path, observed), ("POST", path, body))
            self.assertEqual(headers["Authorization"], "Bearer synthetic-local-http-key")
            self.assertEqual(headers["Idempotency-Key"], "synthetic-replay-key")
            self.assertNotIn("Cookie", headers)

    def test_forbidden_routes_and_non_synthetic_smtp_are_rejected_before_http(self):
        api = self.module.API(self.config())
        with patch.object(api.opener, "open", side_effect=AssertionError("Unexpected HTTP")) as opened:
            for method, path, body in (
                ("POST", "/api/v1/outreach/send", {}),
                ("POST", "/api/v1/outreach/smtp/test", {}),
                ("GET", "https://example.com/private", None),
                ("DELETE", f"/api/v2/activities/{ACTIVITY}", None),
                ("PUT", "/api/v1/outreach/smtp", {**self.module.SMTP, "host": "real.invalid"}),
                ("PUT", "/api/v1/outreach/smtp", {**self.module.SMTP, "password": "PRIVATE-KEY"}),
            ):
                with self.subTest(method=method, path=path):
                    with self.assertRaises(self.module.SmokeError):
                        api.request(method, path, body)
            opened.assert_not_called()

    def test_http_errors_and_redirects_never_expose_response_or_follow_location(self):
        server = self.server()
        api = self.module.API(self.config(server.origin))
        server.response = {"email": "PRIVATE-EMAIL", "secret": "PRIVATE-KEY", "body": "PRIVATE-BODY"}
        for status in (500, 302):
            server.status = status
            with self.assertRaises(self.module.SmokeError) as error:
                api.request("POST", "/api/v2/activities", {"game_id": ACTIVITY})
            self.assertEqual(str(error.exception), f"http_status_{status}")
        self.assertEqual(len(server.requests), 2)
        server.status = 409
        self.assertEqual(
            api.request("POST", "/api/v2/activities", {"game_id": ACTIVITY}, expected=(409,)),
            server.response,
        )

    def test_capture_wait_ignores_old_files_and_waits_for_both_complete_messages(self):
        old = self.eml("smtp-old.eml")

        def publish():
            time.sleep(0.03)
            self.eml("smtp-first.eml")
            time.sleep(0.03)
            self.eml("smtp-second.eml")

        publisher = threading.Thread(target=publish)
        publisher.start()
        try:
            result = self.module.wait_captures(self.state, {old.name}, 2, seconds=1, settle_seconds=0.05)
        finally:
            publisher.join()
        self.assertEqual({path.name for path in result}, {"smtp-first.eml", "smtp-second.eml"})

    def test_capture_wait_rejects_duplicates_permissions_and_times_out_safely(self):
        self.eml("smtp-one.eml")
        two = self.eml("smtp-two.eml")
        with self.assertRaisesRegex(self.module.SmokeError, "capture_count_exceeded"):
            self.module.wait_captures(self.state, set(), 1, seconds=0.1)
        two.chmod(0o644)
        with self.assertRaisesRegex(self.module.SmokeError, "capture_not_private"):
            self.module.wait_captures(self.state, set(), 2, seconds=0.1)
        with self.assertRaisesRegex(self.module.SmokeError, "capture_timeout"):
            self.module.wait_captures(self.state, {"smtp-one.eml", "smtp-two.eml"}, 1, seconds=0.02)

    def test_poll_stops_on_terminal_state_and_never_invents_worker_progress(self):
        seen = []

        def read():
            value = {"status": "queued" if not seen else "succeeded"}
            seen.append(value)
            return value

        result = self.module.poll(read, lambda value: value["status"] != "queued", seconds=1)
        self.assertEqual(result, {"status": "succeeded"})
        self.assertEqual(len(seen), 2)
        with self.assertRaisesRegex(self.module.SmokeError, "operation_timeout"):
            self.module.poll(lambda: {"status": "running"}, lambda value: False, seconds=0.02)


if __name__ == "__main__":
    unittest.main()
