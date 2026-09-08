import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent


class SmokeAssertions(unittest.TestCase):
    def test_checkpoint_counts_reject_source_refetch_or_missing_visual(self):
        self.assertTrue((HERE / "smoke.py").exists())
        spec = importlib.util.spec_from_file_location("analyze_smoke_test", HERE / "smoke.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        good = {"youtube_channel": 1, "youtube_playlist": 1, "youtube_videos": 1,
                "creator_map_00": 1, "creator_map_01": 1, "creator_visual": 1,
                "creator_content": 1, "creator_presentation": 1,
                "creator_performance": 1, "creator_commercial": 1,
                "creator_brief": 2, "asset_download": 2}
        module.require_youtube_counts(good, brief_calls=2)
        for field, value in (("youtube_channel", 2), ("creator_map_00", 2), ("asset_download", 0)):
            with self.assertRaises(AssertionError):
                module.require_youtube_counts({**good, field: value}, brief_calls=2)


if __name__ == "__main__":
    unittest.main()
