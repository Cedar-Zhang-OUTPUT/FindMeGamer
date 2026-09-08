"""Execute inside the pinned fixture image; no keys or external destinations."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("analyze_extension_check", Path(__file__).with_name("runtime.py"))
extension = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extension)


class FixedRuntimeTests(unittest.TestCase):
    def test_real_loader_downloads_png_and_rejects_external_destinations(self):
        from app.integrations import deepseek
        from app.integrations.errors import IntegrationError

        allowed, start = extension.install()
        with tempfile.TemporaryDirectory() as directory:
            server = start(directory)
            try:
                loader = deepseek.VisionImageLoader()
                self.assertEqual(loader.load("https://analyze-fixture.example/assets/game.png"), extension.data.INLINE_PNG)
                with self.assertRaises(IntegrationError):
                    loader.load("https://youtube.com/unapproved.png")
                recorded = [json.loads(line) for line in (Path(directory) / "events.jsonl").read_text().splitlines()]
                self.assertEqual(recorded, [{"endpoint": "asset_download", "status": 200}])
                self.assertFalse(allowed("https://api.deepseek.com/chat/completions"))
                self.assertFalse(allowed("http://127.0.0.1:18081/private"))
                self.assertTrue(allowed("http://127.0.0.1:18081/x/2/users/900000001/tweets"))
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
