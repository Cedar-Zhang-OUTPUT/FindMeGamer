"""Pinned SMTP wiring only; actual HTTP/worker smoke is a separate acceptance."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
OUTREACH_REVISION = "ece2e9d9558dfe057dc40ad58bd98a86e3149dd5"


class OutreachRuntimeContracts(unittest.TestCase):
    def load_runtime(self):
        fixture = types.ModuleType("fixture")
        fixture.destination_allowed = Mock()
        fixture.start_server = Mock()
        spec = importlib.util.spec_from_file_location("outreach_test_runtime", HERE / "runtime.py")
        runtime = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"fixture": fixture}):
            spec.loader.exec_module(runtime)
        return runtime

    def test_older_pins_do_not_install_smtp_or_import_workers(self):
        runtime = self.load_runtime()
        self.assertTrue(hasattr(runtime, "install_smtp_capture"), "Explicit pinned SMTP wiring is missing")
        for revision in (
            "cad55656a9a15ef183c6e0ba4ba608bd61a7a1b5",
            "b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857",
            "a852307d6908e671ae1998c9741f19ffe65f5048",
            "HEAD",
        ):
            with self.subTest(revision=revision), patch.dict(sys.modules, {"smtp_capture": None}):
                self.assertIsNone(runtime.install_smtp_capture({"backend_revision": revision}, "/not-used"))

    def test_new_pin_routes_both_real_worker_constructors_to_the_capture_gateway(self):
        runtime = self.load_runtime()
        self.assertTrue(hasattr(runtime, "install_smtp_capture"), "Explicit pinned SMTP wiring is missing")
        gateway = object()
        capture = types.ModuleType("smtp_capture")
        capture.capture_gateway = Mock(return_value=gateway)
        app = types.ModuleType("app")
        workers = types.ModuleType("app.workers")
        legacy = types.ModuleType("app.workers.outreach_tasks")
        activity = types.ModuleType("app.workers.activity_send_tasks")
        original_legacy, original_activity = Mock(), Mock()
        legacy.SMTPGateway = original_legacy
        activity.SMTPGateway = original_activity
        workers.outreach_tasks, workers.activity_send_tasks = legacy, activity
        app.workers = workers
        with patch.dict(sys.modules, {
            "smtp_capture": capture, "app": app, "app.workers": workers,
            "app.workers.outreach_tasks": legacy,
            "app.workers.activity_send_tasks": activity,
        }):
            result = runtime.install_smtp_capture({"backend_revision": OUTREACH_REVISION}, "/test-private-state")
        capture.capture_gateway.assert_called_once_with("/test-private-state")
        self.assertIs(result, gateway)
        self.assertIs(legacy.SMTPGateway(), gateway)
        self.assertIs(activity.SMTPGateway(), gateway)
        original_legacy.assert_not_called()
        original_activity.assert_not_called()

    def test_capture_setup_failure_does_not_fall_back_to_real_transport(self):
        runtime = self.load_runtime()
        self.assertTrue(hasattr(runtime, "install_smtp_capture"), "Explicit pinned SMTP wiring is missing")
        capture = types.ModuleType("smtp_capture")
        capture.capture_gateway = Mock(side_effect=ValueError("Private fixture required"))
        with patch.dict(sys.modules, {"smtp_capture": capture}):
            with self.assertRaises(ValueError):
                runtime.install_smtp_capture({"backend_revision": OUTREACH_REVISION}, "/not-private")


if __name__ == "__main__":
    unittest.main()
