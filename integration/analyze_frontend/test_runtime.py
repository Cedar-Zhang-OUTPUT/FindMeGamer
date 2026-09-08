import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MATCH = HERE.parent / "match_frontend"
sys.path.insert(0, str(MATCH))
import manage

PIN = "5706ad76f924991b80ee2a7fb6806528366be5ce"


class RuntimeBoundaryTests(unittest.TestCase):
    def extension(self):
        self.assertTrue((HERE / "runtime.py").exists(), "strict Analyze runtime missing")
        spec = importlib.util.spec_from_file_location("analyze_runtime_test", HERE / "runtime.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_new_fixed_pin_does_not_change_default_or_existing_owner(self):
        self.assertEqual(manage.ACCEPTED_REVISIONS.get(PIN), "20260908_0019")
        self.assertNotEqual(manage.PIN, PIN)
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            manage.initialize(private, backend_revision=PIN)
            self.assertEqual(manage.load_owned(private)["migration"], "20260908_0019")

    def test_asset_resolver_never_uses_real_dns_and_only_known_https_assets(self):
        extension = self.extension()
        resolver = extension.AssetResolver()
        self.assertEqual(resolver.resolve("analyze-fixture.example", 443), ["93.184.216.34"])
        for host, port in (("youtube.com", 443), ("127.0.0.1", 443), ("analyze-fixture.example", 80)):
            with self.assertRaises(ValueError):
                resolver.resolve(host, port)
        self.assertEqual(extension.asset_path("https://analyze-fixture.example/assets/game.png"), "/assets/game.png")
        for url in ("https://analyze-fixture.example/assets/other.png", "http://analyze-fixture.example/assets/game.png", "https://real.example/assets/game.png", "https://analyze-fixture.example/assets/game.png?x=1"):
            with self.assertRaises(ValueError):
                extension.asset_path(url)

    def test_x_profile_timeline_exact_fixture_identity_and_twenty_one_posts(self):
        extension = self.extension()
        status, body, label = extension.x_source("/x/2/users/900000001", {"user.fields": extension.USER_FIELDS})
        self.assertEqual((status, label, body["data"]["id"]), (200, "x_user", "900000001"))
        query = {"max_results": "50", "exclude": "retweets,replies", "tweet.fields": extension.POST_FIELDS}
        status, body, label = extension.x_source("/x/2/users/900000001/tweets", query)
        self.assertEqual((status, label, len(body["data"])), (200, "x_posts", 21))
        self.assertTrue(all(post["author_id"] == "900000001" for post in body["data"]))
        self.assertEqual(extension.x_source("/x/2/users/123", query)[0], 400)
        self.assertEqual(extension.x_source("/x/2/users/900000001/tweets", {**query, "pagination_token": "unexpected"})[0], 400)


if __name__ == "__main__":
    unittest.main()
