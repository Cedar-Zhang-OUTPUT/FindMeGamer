"""Configuration policy tests; no Docker or user credentials needed."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FrontendLocalTests(unittest.TestCase):
    def test_private_synthetic_configuration(self):
        spec = importlib.util.spec_from_file_location(
            "frontend_local", ROOT / "integration/frontend_local.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "local"
            config = module.initialize(directory, 18090)
            self.assertEqual(config["base_url"], "http://127.0.0.1:18090")
            self.assertGreaterEqual(len(config["workspace_key"]), 32)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            for name in ("client.json", "master.key", "compose.env"):
                self.assertEqual((directory / name).stat().st_mode & 0o777, 0o600)
            self.assertEqual(module.initialize(directory, 18090), config)
            with self.assertRaises(ValueError):
                module.initialize(directory, 18091)

    def test_compose_is_isolated_and_has_no_workers(self):
        source = (ROOT / "integration/compose.frontend.yaml").read_text()
        self.assertIn("127.0.0.1:${FMG_FRONTEND_PORT}:8000", source)
        self.assertIn("DEEPSEEK_API_BASE_URL: http://127.0.0.1:9", source)
        self.assertNotIn("worker:", source)
        self.assertNotIn("beat:", source)
        self.assertNotIn("env_file:", source)
        self.assertNotIn("${HOME}", source)


if __name__ == "__main__":
    unittest.main()
