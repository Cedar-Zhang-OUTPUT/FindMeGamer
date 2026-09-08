"""Test-only boundary contracts; real sockets and private filesystem, no Docker."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

HERE = Path(__file__).resolve().parent


class FixtureContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            (HERE / "fixture.py").exists(), "Strict HTTP fixture is missing"
        )
        spec = importlib.util.spec_from_file_location(
            "match_fixture", HERE / "fixture.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.server = self.module.start_server(self.state, port=0)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, data=None, headers=None):
        request = Request(
            self.base + path,
            data=None if data is None else json.dumps(data).encode(),
            headers=headers or {},
            method="GET" if data is None else "POST",
        )
        try:
            with self.opener.open(request, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_youtube_two_pages_duplicate_accounts_and_unknown_followers(self):
        # Missing cursor handling or invented audience metadata breaks this contract.
        headers = {"X-Goog-Api-Key": "synthetic-match-youtube"}
        first = self.request(
            "/youtube/v3/search?part=snippet&type=video&q=cozy&maxResults=50",
            headers=headers,
        )[1]
        second = self.request(
            "/youtube/v3/search?part=snippet&type=video&q=cozy&maxResults=50&pageToken=yt-page-2",
            headers=headers,
        )[1]
        self.assertEqual(first["nextPageToken"], "yt-page-2")
        self.assertNotIn("nextPageToken", second)
        self.assertEqual(
            [x["snippet"]["channelId"] for x in first["items"]],
            ["UCmatchA001", "UCmatchA001", "UCmatchB002"],
        )
        self.assertEqual(
            [x["snippet"]["channelId"] for x in second["items"]],
            ["UCmatchA001", "UCmatchC003"],
        )
        channels = self.request(
            "/youtube/v3/channels?part=snippet%2Cstatistics&id=UCmatchB002",
            headers=headers,
        )[1]
        self.assertNotIn("country", channels["items"][0]["snippet"])
        self.assertTrue(channels["items"][0]["statistics"]["hiddenSubscriberCount"])

    def test_x_two_pages_have_duplicate_authors_and_deterministic_exhaustion(self):
        headers = {"Authorization": "Bearer synthetic-match-x"}
        query = "/x/2/tweets/search/recent?query=cozy&max_results=100&expansions=author_id&tweet.fields=author_id,created_at,lang,public_metrics&user.fields=name,username,description,public_metrics,location,profile_image_url"
        first = self.request(query, headers=headers)[1]
        second = self.request(query + "&next_token=x-page-2", headers=headers)[1]
        self.assertEqual(first["meta"]["next_token"], "x-page-2")
        self.assertNotIn("next_token", second["meta"])
        self.assertEqual(
            [x["author_id"] for x in first["data"]], ["7101", "7101", "7102"]
        )
        self.assertNotIn(
            "followers_count", first["includes"]["users"][1]["public_metrics"]
        )

    def test_unexpected_destinations_endpoints_and_credentials_fail_closed(self):
        self.assertEqual(self.request("/not-an-endpoint")[0], 404)
        self.assertEqual(
            self.request(
                "/youtube/v3/search?part=snippet&type=video&q=a&maxResults=50"
            )[0],
            401,
        )
        self.assertEqual(
            self.request(
                "/youtube/v3/search?part=snippet&type=video&q=a&maxResults=50&pageToken=evil",
                headers={"X-Goog-Api-Key": "synthetic-match-youtube"},
            )[0],
            400,
        )
        self.assertFalse(
            self.module.destination_allowed("https://api.deepseek.com/chat/completions")
        )
        self.assertFalse(
            self.module.destination_allowed("http://127.0.0.1:18081/unexpected")
        )
        self.assertTrue(
            self.module.destination_allowed(
                "http://127.0.0.1:18081/deepseek/chat/completions"
            )
        )

    def test_models_obey_input_ids_and_reject_unknown_contracts(self):
        candidate = "10000000-0000-4000-8000-000000000001"
        cases = [
            (
                "SearchPlanOutput",
                "deepseek-v4-flash",
                {"conditions": {"platforms": ["youtube", "x"]}},
                "queries",
            ),
            (
                "EvaluationScreenOutput",
                "deepseek-v4-flash",
                {"candidates": [{"candidate_id": candidate}]},
                "selected_ids",
            ),
            (
                "EvaluationMatchBrief",
                "deepseek-v4-pro",
                {"candidate": {"candidate_id": candidate, "works": []}},
                "candidate_id",
            ),
            (
                "EvaluationRankOutput",
                "deepseek-v4-pro",
                {"briefs": [{"candidate_id": candidate}]},
                "items",
            ),
        ]
        for title, model, payload, field in cases:
            request = {
                "model": model,
                "messages": [
                    {"role": "system", "content": json.dumps({"title": title})},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "max_tokens": 2048,
            }
            status, body = self.request(
                "/deepseek/chat/completions",
                request,
                {"Authorization": "Bearer synthetic-match-deepseek"},
            )
            self.assertEqual(status, 200)
            output = json.loads(body["choices"][0]["message"]["content"])
            self.assertIn(field, output)
            if title == "EvaluationScreenOutput":
                self.assertEqual(output[field], [candidate])
            if title == "EvaluationMatchBrief":
                self.assertEqual(output["confidence"], "limited")
                self.assertEqual(output["cited_work_ids"], [])
        request["messages"][0]["content"] = '{"title":"UnknownSchema"}'
        self.assertEqual(
            self.request(
                "/deepseek/chat/completions",
                request,
                {"Authorization": "Bearer synthetic-match-deepseek"},
            )[0],
            400,
        )

    def test_failure_and_hold_controls_are_test_only_and_do_not_log_content(self):
        self.module.write_control(
            self.state, {"source_fail": "youtube", "model_fail": "none", "hold": "none"}
        )
        headers = {"X-Goog-Api-Key": "synthetic-match-youtube"}
        path = (
            "/youtube/v3/search?part=snippet&type=video&q=PRIVATE-PROMPT&maxResults=50"
        )
        self.assertEqual(self.request(path, headers=headers)[0], 503)
        self.module.write_control(
            self.state, {"source_fail": "none", "model_fail": "none", "hold": "youtube"}
        )
        result = []
        thread = threading.Thread(
            target=lambda: result.append(self.request(path, headers=headers))
        )
        thread.start()
        time.sleep(0.1)
        self.assertTrue(thread.is_alive())
        self.module.write_control(
            self.state, {"source_fail": "none", "model_fail": "none", "hold": "none"}
        )
        thread.join(2)
        self.assertEqual(result[0][0], 200)
        self.assertNotIn("PRIVATE-PROMPT", (self.state / "events.jsonl").read_text())
        self.assertNotIn(
            "synthetic-match-youtube", (self.state / "events.jsonl").read_text()
        )
        self.assertEqual(self.request("/control", {})[0], 404)

    def test_control_reader_tolerates_atomic_rename_visibility_gap(self):
        # Docker Desktop can report exists then ENOENT during a host atomic rename.
        self.module.write_control(
            self.state, {"source_fail": "x", "model_fail": "none", "hold": "none"}
        )
        original = Path.read_text

        def disappear(path, *args, **kwargs):
            path.unlink()
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", disappear):
            try:
                value = self.module.control(self.state)
            except FileNotFoundError:
                self.fail("Fixture control rename gap interrupted the HTTP request")
            self.assertEqual(
                value, {"source_fail": "none", "model_fail": "none", "hold": "none"}
            )


class LifecycleContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            (HERE / "manage.py").exists(), "Owned environment manager is missing"
        )
        spec = importlib.util.spec_from_file_location(
            "match_manage", HERE / "manage.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_explicit_accepted_revision_has_its_own_migration_and_preserves_old_runs(self):
        revision = "b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857"
        with tempfile.TemporaryDirectory() as temporary:
            old_directory = Path(temporary) / "old"
            old = self.module.initialize(old_directory)
            new_directory = Path(temporary) / "new"
            new = self.module.initialize(new_directory, backend_revision=revision)
            self.assertEqual(new["backend_revision"], revision)
            self.assertEqual(new["migration"], "20260908_0014")
            self.assertEqual(self.module.load_owned(new_directory), new)
            self.assertEqual(self.module.load_owned(old_directory), old)
            self.assertEqual(old["migration"], "20260908_0012")
            self.assertNotEqual(old["project"], new["project"])
            self.assertNotEqual(old["workspace_key"], new["workspace_key"])

    def test_unaccepted_revision_is_rejected_before_creating_private_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "unaccepted"
            with self.assertRaises(ValueError):
                self.module.initialize(directory, backend_revision="HEAD")
            self.assertFalse(directory.exists())

    def test_query_and_named_set_revision_uses_0015_without_upgrading_collection(self):
        revision = "a852307d6908e671ae1998c9741f19ffe65f5048"
        with tempfile.TemporaryDirectory() as temporary:
            collection_directory = Path(temporary) / "collection"
            collection = self.module.initialize(
                collection_directory,
                backend_revision="b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857",
            )
            query_directory = Path(temporary) / "queries"
            queries = self.module.initialize(query_directory, backend_revision=revision)
            self.assertEqual(queries["backend_revision"], revision)
            self.assertEqual(queries["migration"], "20260908_0015")
            self.assertEqual(self.module.load_owned(query_directory), queries)
            self.assertEqual(self.module.load_owned(collection_directory), collection)
            self.assertEqual(collection["migration"], "20260908_0014")
            self.assertNotEqual(queries["project"], collection["project"])
            self.assertNotEqual(queries["workspace_key"], collection["workspace_key"])

    def test_cli_can_start_a_separate_accepted_revision_without_printing_keys(self):
        revision = "b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857"
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with patch.object(self.module.tempfile, "mkdtemp", return_value=temporary), \
                 patch.object(self.module, "start", side_effect=self.module.load_owned) as start, \
                 contextlib.redirect_stdout(output):
                self.module.main(["start", "--backend-revision", revision])
            directory = Path(temporary) / "private"
            config = self.module.load_owned(directory)
            start.assert_called_once_with(directory)
            self.assertEqual(config["backend_revision"], revision)
            self.assertNotIn(config["workspace_key"], output.getvalue())

    def test_cli_does_not_upgrade_an_existing_owned_instance(self):
        revision = "b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "old"
            old = self.module.initialize(directory)
            with patch.object(self.module, "start") as start, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    self.module.main(["start", "--directory", str(directory), "--backend-revision", revision])
            self.assertEqual(failure.exception.code, 2)
            start.assert_not_called()
            self.assertEqual(self.module.load_owned(directory), old)

    def test_generated_credentials_are_private_and_reopening_preserves_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            config = self.module.initialize(directory)
            self.assertTrue(config["project"].startswith("fmg-match-frontend-"))
            self.assertGreaterEqual(len(config["workspace_key"]), 32)
            self.assertEqual(self.module.load_owned(directory), config)
            for path in (
                directory / "client.json",
                directory / "master.key",
                directory / "owner.json",
            ):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(FileExistsError):
                self.module.initialize(directory)

    def test_other_stack_and_unowned_directory_cannot_be_operated(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            self.module.initialize(directory)
            owner = json.loads((directory / "owner.json").read_text())
            owner["project"] = "fmg-frontend-http"
            (directory / "owner.json").write_text(json.dumps(owner))
            with self.assertRaises(ValueError):
                self.module.load_owned(directory)
            with self.assertRaises(ValueError):
                self.module.load_owned(Path(temporary))

    def test_cli_status_never_prints_credentials_and_drops_ambient_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            config = self.module.initialize(directory)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.module.main(["status", "--directory", str(directory)])
            self.assertNotIn(config["workspace_key"], output.getvalue())
            self.assertNotIn((directory / "master.key").read_text(), output.getvalue())
            self.assertIn(str(directory / "client.json"), output.getvalue())
            self.assertEqual(
                self.module.docker_environment(
                    {
                        "PATH": "/bin",
                        "DEEPSEEK_API_KEY": "real",
                        "DATABASE_URL": "real",
                        "HTTP_PROXY": "real",
                    }
                ),
                {"PATH": "/bin"},
            )


class RelayContract(unittest.TestCase):
    def test_relay_cannot_be_used_as_an_external_proxy(self):
        self.assertTrue(
            (HERE / "relay.py").exists(), "Fixed-target loopback relay is missing"
        )
        spec = importlib.util.spec_from_file_location("match_relay", HERE / "relay.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(module.allowed_path("/api/v2/activities?limit=20"))
        self.assertFalse(
            module.allowed_path("https://api.deepseek.com/chat/completions")
        )
        self.assertFalse(module.allowed_path("//api.deepseek.com/chat/completions"))
        self.assertFalse(module.allowed_path("/other"))


if __name__ == "__main__":
    unittest.main()
