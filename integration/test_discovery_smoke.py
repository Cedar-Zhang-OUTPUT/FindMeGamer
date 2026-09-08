import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class DiscoverySmokeTests(unittest.TestCase):
    def test_live_needs_explicit_flags_and_private_credentials_file(self):
        from integration.discovery_smoke import load_credentials

        with self.assertRaises(ValueError):
            load_credentials(live=True, acknowledge=False, path=None)
        with self.assertRaises(ValueError):
            load_credentials(live=True, acknowledge=True, path=None)
        self.assertEqual(
            load_credentials(live=False, acknowledge=False, path=None),
            {"youtube": "fixture-youtube", "x": "fixture-x"},
        )

    def test_fixture_never_reads_a_supplied_real_secret_file(self):
        from integration.discovery_smoke import load_credentials

        with self.assertRaises(ValueError):
            load_credentials(live=False, acknowledge=False, path=Path("does-not-exist"))

    def test_live_rejects_public_file_and_can_read_only_explicit_private_fixture(self):
        from integration.discovery_smoke import load_credentials

        with TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.json"
            path.write_text('{"youtube":"synthetic-youtube", "x":"synthetic-x"}')
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_credentials(live=True, acknowledge=True, path=path)
            path.chmod(0o600)
            self.assertEqual(
                load_credentials(live=True, acknowledge=True, path=path),
                {"youtube": "synthetic-youtube", "x": "synthetic-x"},
            )
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                load_credentials(live=True, acknowledge=True, path=link)

    def test_queries_have_one_page_total_budgets_and_no_cursor(self):
        from integration.discovery_smoke import query_payload

        yt = query_payload("youtube", "indie game")
        x = query_payload("x", "indie game")
        self.assertEqual(yt["total_request_budget"], 2)
        self.assertEqual(yt["total_scan_budget"], 5)
        self.assertEqual(yt["providers"][0]["page_size"], 5)
        self.assertEqual(x["total_request_budget"], 1)
        self.assertEqual(x["total_scan_budget"], 10)
        self.assertEqual(x["providers"][0]["page_size"], 10)
        for payload in (yt, x):
            self.assertEqual(
                payload["batch_request_budget"], payload["total_request_budget"]
            )
            self.assertEqual(payload["batch_scan_budget"], payload["total_scan_budget"])
            self.assertNotIn("cursor", payload["providers"][0])

    def test_host_credentials_and_proxy_are_not_inherited_by_containers(self):
        from integration.discovery_smoke import docker_environment

        self.assertEqual(
            docker_environment(
                {
                    "PATH": "/usr/bin",
                    "DOCKER_CONTEXT": "desktop-linux",
                    "YOUTUBE_API_KEY": "synthetic",
                    "X_BEARER_TOKEN": "synthetic",
                    "HTTPS_PROXY": "http://localhost:9999",
                    "ALL_PROXY": "synthetic",
                    "AWS_SECRET_ACCESS_KEY": "synthetic",
                }
            ),
            {"PATH": "/usr/bin", "DOCKER_CONTEXT": "desktop-linux"},
        )

    def test_initialization_creates_random_keys_and_private_run_files(self):
        from integration.discovery_smoke import initialize

        with TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "first", Path(temporary) / "second"
            first_config = initialize(first, live=False)
            second_config = initialize(second, live=False)
            self.assertNotEqual(
                first_config["workspace_key"], second_config["workspace_key"]
            )
            self.assertEqual(first_config["mode"], "fixture")
            self.assertEqual(first.stat().st_mode & 0o777, 0o700)
            for name in ("client.json", "master.key"):
                self.assertEqual((first / name).stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
