"""Failure-harness boundaries only; no mock business worker or SMTP server."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
DELIVERY = "11111111-1111-4111-8111-111111111111"


class FailureSmokeContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / "outreach_failure_smoke.py").exists(), "Real failure smoke is missing")
        spec = importlib.util.spec_from_file_location("outreach_failure_contract", HERE / "outreach_failure_smoke.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.state.chmod(0o700)

    def config(self, port=62001):
        return {"backend_revision": "ece2e9d9558dfe057dc40ad58bd98a86e3149dd5", "migration": "20260908_0017", "base_url": f"http://127.0.0.1:{port}", "workspace_key": "synthetic-local-http-key"}

    def server(self):
        class Boundary(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.server.requests.append((self.path, body, dict(self.headers)))
                self.send_response(self.server.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(self.server.body).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Boundary)
        server.requests, server.status, server.body = [], 200, {"id": DELIVERY}
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def test_recovery_routes_preserve_explicit_attempt_and_source_note(self):
        server = self.server()
        api = self.module.FailureAPI(self.config(server.server_port))
        cases = [
            ("retry", {"expected_attempt": 1}),
            ("resolve", {"expected_attempt": 1, "outcome": "sent", "source_note": "Synthetic local EML capture verified by test operator."}),
        ]
        for action, body in cases:
            result = api.request("POST", f"/api/v2/outreach/deliveries/{DELIVERY}/{action}", body, key="synthetic-explicit-action")
            self.assertEqual(result, {"id": DELIVERY})
        for (action, body), (path, seen, headers) in zip(cases, server.requests):
            self.assertEqual(path, f"/api/v2/outreach/deliveries/{DELIVERY}/{action}")
            self.assertEqual(seen, body)
            self.assertEqual(headers["Idempotency-Key"], "synthetic-explicit-action")
            self.assertEqual(headers["Authorization"], "Bearer synthetic-local-http-key")

    def test_recovery_rejects_other_actions_and_invalid_bodies_without_http(self):
        api = self.module.FailureAPI(self.config())
        with patch.object(api.opener, "open", side_effect=AssertionError("Unexpected HTTP")) as opened:
            for action, body in (
                ("retry", {}), ("retry", {"expected_attempt": True}),
                ("retry", {"expected_attempt": -1}), ("retry", {"expected_attempt": 1, "automatic": True}),
                ("resolve", {"expected_attempt": 1, "outcome": "sent", "source_note": " "}),
                ("resolve", {"expected_attempt": 1, "outcome": "not_sent", "source_note": "Synthetic note"}),
                ("send", {"expected_attempt": 1}),
            ):
                with self.assertRaises(self.module.SmokeError):
                    api.request("POST", f"/api/v2/outreach/deliveries/{DELIVERY}/{action}", body)
            opened.assert_not_called()

    def test_recovery_expected_conflict_and_unexpected_error_are_not_retried(self):
        server = self.server()
        api = self.module.FailureAPI(self.config(server.server_port))
        path = f"/api/v2/outreach/deliveries/{DELIVERY}/retry"
        server.status, server.body = 409, {"error": {"message": "PRIVATE-BODY"}}
        api.request("POST", path, {"expected_attempt": 1}, expected=(409,))
        server.status = 500
        with self.assertRaisesRegex(self.module.SmokeError, "^http_status_500$"):
            api.request("POST", path, {"expected_attempt": 1})
        self.assertEqual(len(server.requests), 2)

    def test_fault_context_restores_success_after_normal_exit(self):
        with self.module.smtp_control(self.state, settle_seconds=0) as control:
            control.set("reject")
            path = self.state / "smtp-control.json"
            self.assertEqual(json.loads(path.read_text()), {"mode": "reject"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text()), {"mode": "success"})

    def test_fault_context_restores_success_after_body_failure(self):
        with self.assertRaisesRegex(self.module.SmokeError, "synthetic_stage_failed"):
            with self.module.smtp_control(self.state, settle_seconds=0) as control:
                control.set("unknown_after_capture")
                raise self.module.SmokeError("synthetic_stage_failed")
        path = self.state / "smtp-control.json"
        self.assertEqual(json.loads(path.read_text()), {"mode": "success"})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_or_already_active_control_is_not_overwritten(self):
        with self.module.smtp_control(self.state, settle_seconds=0) as control:
            with self.assertRaises(self.module.SmokeError):
                control.set("external")
        path = self.state / "smtp-control.json"
        path.write_text('{"mode":"reject"}')
        with self.assertRaises(self.module.SmokeError):
            with self.module.smtp_control(self.state, settle_seconds=0):
                self.fail("An existing fault must not be taken over")
        self.assertEqual(json.loads(path.read_text()), {"mode": "reject"})

    def test_expected_mode_requires_new_transport_event_not_just_host_control(self):
        events = self.state / "smtp-events.jsonl"
        events.write_text('{"endpoint":"smtp","status":"captured"}\n')
        self.assertEqual(self.module.smtp_events(self.state), ["captured"])
        with self.assertRaisesRegex(self.module.SmokeError, "smtp_fault_not_observed"):
            self.module.verify_events(self.state, 1, ["rejected"])
        with events.open("a") as stream:
            stream.write('{"endpoint":"smtp","status":"rejected"}\n')
        self.assertEqual(self.module.verify_events(self.state, 1, ["rejected"]), ["rejected"])
        with self.assertRaisesRegex(self.module.SmokeError, "smtp_fault_not_observed"):
            self.module.verify_events(self.state, 1, ["captured", "unknown_after_capture"])


if __name__ == "__main__":
    unittest.main()
