"""Pure boundary tests; optional fixed-backend contract test is enabled explicitly."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import zlib
import struct

HERE = Path(__file__).resolve().parent


def object_schema(title, fields):
    return {"title": title, "type": "object", "additionalProperties": False, "required": list(fields), "properties": fields}


def unavailable_schema():
    return object_schema("Unavailable", {"status": {"const": "unavailable"}, "reason": {"type": "string"}})


def small_registry():
    # A trusted, independent tiny registry exercises exact-schema comparison;
    # the separate fixed-backend check validates real complete schema outputs.
    return {
        "GameExtraction": object_schema("GameExtraction", {"english_language_check": {"const": True}, "short_summary": unavailable_schema(), "core_gameplay_loop": unavailable_schema()}),
        "GameVisualAnalysis": object_schema("GameVisualAnalysis", {"english_language_check": {"const": True}, "status": {"enum": ["available", "unavailable"]}, "unavailable_reason": {"type": "string"}, "visual_style": unavailable_schema()}),
        "CreatorVideoBatchDigest": object_schema("CreatorVideoBatchDigest", {"english_language_check": {"const": True}, **{group: object_schema(group, {field: unavailable_schema()}) for group, field in (("content_format", "content_focus"), ("presentation", "style_and_pacing"), ("performance_audience", "recent_performance"), ("commercial_safety", "sponsorship_signals"))}}),
    }


class AnalyzeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / "fixture.py").exists(), "Analyze boundary fixture is missing")
        spec = importlib.util.spec_from_file_location("analyze_fixture_contract", HERE / "fixture.py")
        self.fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fixture)
        self.schemas = small_registry()

    def dispatch(self, path, query=None, body=None, headers=None, schemas=None):
        return self.fixture.dispatch(path, query or {}, body, headers or {}, schemas=self.schemas if schemas is None else schemas)

    def request(self, title="GameExtraction", payload=None):
        payload = payload or {"steam_source": {"app_id": "900000001", "about_the_game": "Explore a quiet station and solve cooperative puzzles."}, "evidence_catalog": {"entries": [{"reference": "steam:about_the_game", "source_type": "steam_field", "allowed_kinds": ["source_fact"]}]}}
        return {"model": "deepseek-v4-flash", "messages": [
            {"role": "system", "content": "Return exactly one JSON value that validates against this JSON Schema. Return no Markdown, prose, or commentary. JSON Schema: " + json.dumps(self.schemas[title])},
            {"role": "system", "content": "Prompt version: game-extraction-v1\nSynthetic rules"},
            {"role": "user", "content": "SOURCE_JSON_UNTRUSTED_EVIDENCE\n```json\n" + json.dumps(payload) + "\n```"},
        ], "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}}

    def model(self, body, schemas=None):
        return self.dispatch("/deepseek/chat/completions", body=body, headers={"Authorization": "Bearer synthetic-analyze-deepseek"}, schemas=schemas)

    def test_steam_has_one_exact_synthetic_source_and_no_ai_call(self):
        status, body, label = self.dispatch("/steam/appdetails", {"appids": "900000001", "l": "english", "cc": "US"})
        self.assertEqual((status, label), (200, "steam"))
        self.assertEqual(body["900000001"]["data"]["steam_appid"], 900000001)
        self.assertEqual(body["900000001"]["data"]["about_the_game"], "Explore a quiet station and solve cooperative puzzles.")
        for query in ({"appids": "1245620", "l": "english", "cc": "US"}, {"appids": "900000001", "l": "english", "cc": "US", "unknown": "x"}):
            self.assertEqual(self.dispatch("/steam/appdetails", query)[0], 400)

    def test_youtube_full_channel_handle_uploads_and_eleven_public_videos(self):
        headers = {"X-Goog-Api-Key": "synthetic-analyze-youtube"}
        status, channel, label = self.dispatch("/youtube/v3/channels", {"part": "snippet,contentDetails,statistics,brandingSettings", "id": "UCanalyzeFixture01"}, headers=headers)
        self.assertEqual((status, label), (200, "youtube_channel"))
        self.assertEqual(channel["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"], "UUanalyzeFixture01")
        resolved = self.dispatch("/youtube/v3/channels", {"part": "id", "forHandle": "@analyzefixture"}, headers=headers)[1]
        self.assertEqual(resolved, {"items": [{"id": "UCanalyzeFixture01"}]})
        pages = self.dispatch("/youtube/v3/playlistItems", {"part": "contentDetails", "playlistId": "UUanalyzeFixture01", "maxResults": "50"}, headers=headers)[1]
        ids = [item["contentDetails"]["videoId"] for item in pages["items"]]
        self.assertEqual(ids, [f"analyze{index:02d}" for index in range(1, 12)])
        status, videos, label = self.dispatch("/youtube/v3/videos", {"part": "snippet,contentDetails,statistics,status", "id": ",".join(ids), "maxResults": "50"}, headers=headers)
        self.assertEqual((status, label), (200, "youtube_videos"))
        self.assertEqual(len(videos["items"]), 11)
        self.assertEqual(sum(bool(item["snippet"].get("thumbnails")) for item in videos["items"]), 2)
        self.assertTrue(all(item["status"]["privacyStatus"] == "public" for item in videos["items"]))
        self.assertTrue(all(item["snippet"]["publishedAt"] < "2026-09-08" for item in videos["items"]), "Synthetic public works must already be published")

    def test_unknown_endpoints_credentials_and_source_queries_fail_closed(self):
        cases = [
            ("https://real.invalid/steam/appdetails", {}, None, {}),
            ("/google/models/model:generateContent", {}, {}, {}),
            ("/youtube/v3/channels", {"part": "id", "forHandle": "@analyzefixture"}, None, {}),
            ("/youtube/v3/channels", {"part": "id", "forHandle": "@analyzefixture"}, None, {"X-Goog-Api-Key": "PRIVATE-KEY"}),
            ("/youtube/v3/channels", {"part": "id", "forHandle": "@unknown"}, None, {"X-Goog-Api-Key": "synthetic-analyze-youtube"}),
            ("/youtube/v3/videos", {"part": "snippet,contentDetails,statistics,status", "id": "unknown", "maxResults": "50"}, None, {"X-Goog-Api-Key": "synthetic-analyze-youtube"}),
        ]
        for path, query, body, headers in cases:
            status, response, label = self.dispatch(path, query, body, headers)
            self.assertIn(status, (400, 401, 404))
            self.assertNotIn("PRIVATE-KEY", json.dumps(response))
            self.assertIn(label, {"rejected", "unauthorized", "not_found"})

    def test_text_fence_schema_and_source_bound_available_claim(self):
        request = self.request()
        before = deepcopy(request)
        status, response, label = self.model(request)
        self.assertEqual((status, label), (200, "game_extraction"))
        value = json.loads(response["choices"][0]["message"]["content"])
        self.assertEqual(value["short_summary"]["value"], "Explore a quiet station and solve cooperative puzzles.")
        self.assertEqual(value["short_summary"]["evidence"][0]["reference"], "steam:about_the_game")
        self.assertEqual(request, before)

    def test_missing_schema_modified_schema_model_budget_and_extra_payload_rejected(self):
        requests = []
        bad = self.request(); bad["messages"][0]["content"] = "No schema"; requests.append(bad)
        bad = self.request(); schema = deepcopy(self.schemas["GameExtraction"]); schema["extra"] = True; bad["messages"][0]["content"] = "JSON Schema: " + json.dumps(schema); requests.append(bad)
        for key, value in (("model", "deepseek-v4-pro"), ("max_tokens", 2048), ("thinking", {"type": "enabled"}), ("unknown", True)):
            bad = self.request(); bad[key] = value; requests.append(bad)
        bad = self.request(); bad["messages"].append({"role": "user", "content": "extra"}); requests.append(bad)
        bad = self.request(); bad["messages"][2]["content"] = bad["messages"][2]["content"].replace('"steam_source":', '"unknown":'); requests.append(bad)
        for request in requests:
            self.assertEqual(self.model(request)[0], 400)
        self.assertEqual(self.model(self.request(), schemas={})[0], 400)

    def test_evidence_missing_or_foreign_reference_cannot_generate_available_claim(self):
        for reference in ("steam:invented", "video:foreign"):
            request = self.request(payload={"steam_source": {"app_id": "900000001", "about_the_game": "Explore a quiet station and solve cooperative puzzles."}, "evidence_catalog": {"entries": [{"reference": reference, "source_type": "steam_field", "allowed_kinds": ["source_fact"]}]}})
            self.assertEqual(self.model(request)[0], 400)

    def test_visual_requires_two_messages_inline_fixture_image_and_exact_budget(self):
        import base64
        body = {"model": "deepseek-v4-flash-vision-exp", "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}, "messages": [
            {"role": "system", "content": "Return exactly one JSON value that validates against this JSON Schema. Return no Markdown, prose, or commentary. JSON Schema: " + json.dumps(self.schemas["GameVisualAnalysis"])},
            {"role": "user", "content": [{"type": "text", "text": 'SYSTEM\nPrompt version: game-visual-v1\nSynthetic rules\n\nUSER\nSOURCE_JSON_UNTRUSTED_EVIDENCE\n```json\n' + json.dumps({"visual_assets": {"app_id": "900000001", "game_name": "Synthetic Station", "assets": [{"asset_ref": "cover:0", "image_url": "https://analyze-fixture.example/assets/game.png"}], "asset_truncation_marker": "not_truncated"}, "evidence_catalog": {"entries": [{"reference": "cover:0", "source_type": "visual_asset", "allowed_kinds": ["visual_observation"]}]}}) + '\n```'}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(self.fixture.PNG_BYTES).decode()}}]},
        ]}
        status, response, label = self.model(body)
        self.assertEqual((status, label), (200, "game_visual"))
        self.assertEqual(json.loads(response["choices"][0]["message"]["content"])["visual_style"]["evidence"][0]["kind"], "visual_observation")
        bad = deepcopy(body); bad["messages"][1]["content"][1]["image_url"]["url"] = "https://real.invalid/image.png"
        self.assertEqual(self.model(bad)[0], 400)
        bad = deepcopy(body); bad["max_tokens"] = 2048
        self.assertEqual(self.model(bad)[0], 400)

    def test_static_png_has_valid_chunks_crc_and_one_red_pixel(self):
        data = self.fixture.PNG_BYTES
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        offset, compressed = 8, bytearray()
        while offset < len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]; payload = data[offset + 8:offset + 8 + length]
            self.assertEqual(struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0], zlib.crc32(kind + payload) & 0xffffffff)
            if kind == b"IDAT": compressed.extend(payload)
            offset += 12 + length
        self.assertEqual(zlib.decompress(compressed), b"\x00\xff\x00\x00")


def fixed_contract_suite():
    """Explicit offline check against app modules on a caller's fixed PYTHONPATH.

    Sources pass through real gateways with an in-memory HTTP transport; model
    text passes through the real DeepSeekGateway. No loader is injected/called.
    Visual messages are checked separately at the documented boundary only.
    This suite is not an HTTP server, pipeline, worker or runtime acceptance.
    """
    import httpx
    from app.analysis.prompts.common import render_vision_prompt
    from app.analysis.prompts.game import build_game_extraction_bundle, build_game_visual_bundle, build_game_synthesis_bundle
    from app.analysis.prompts.creator import build_creator_visual_bundle
    from app.analysis.prompts.creator_map_reduce import build_creator_video_batch_bundle, build_creator_content_format_bundle, build_creator_presentation_bundle, build_creator_performance_audience_bundle, build_creator_commercial_safety_bundle, build_creator_brief_bundle
    from app.analysis.creator_map_reduce import merge_creator_synthesis
    from app.analysis.creator_pipeline import build_creator_contact_evidence
    from app.integrations.public_pages import PublicPageGateway
    from app.integrations.steam import SteamGateway
    from app.integrations.youtube import YouTubeGateway
    from app.integrations.deepseek import DeepSeekGateway
    from app.schemas.ai_game import GameExtraction, GameVisualAnalysis, GameSynthesis, validate_stage_evidence
    from app.schemas.ai_creator import CreatorVisualAnalysis, bind_creator_contacts
    from app.schemas.ai_creator_map_reduce import CreatorVideoBatchDigest, CreatorContentFormatReduction, CreatorPresentationReduction, CreatorPerformanceAudienceReduction, CreatorCommercialSafetyReduction, CreatorBriefSynthesis

    class FixedBackendContracts(unittest.TestCase):
        def setUp(self):
            spec = importlib.util.spec_from_file_location("analyze_fixed_contract", HERE / "fixture.py")
            self.fixture = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.fixture)
            self.types = (GameExtraction, GameVisualAnalysis, GameSynthesis, CreatorVideoBatchDigest, CreatorVisualAnalysis, CreatorContentFormatReduction, CreatorPresentationReduction, CreatorPerformanceAudienceReduction, CreatorCommercialSafetyReduction, CreatorBriefSynthesis)
            self.registry = {schema.__name__: schema.model_json_schema() for schema in self.types}
            self.events = []

        def handler(self, request):
            body = json.loads(request.content) if request.content else None
            status, result, label = self.fixture.dispatch(request.url.path, dict(request.url.params), body, dict(request.headers), schemas=self.registry)
            self.events.append(label)
            return httpx.Response(status, json=result)

        def test_all_ten_actual_schemas_and_evidence_bind_across_real_prompt_stages(self):
            client = httpx.Client(transport=httpx.MockTransport(self.handler))
            self.addCleanup(client.close)
            steam = SteamGateway(base_url="http://127.0.0.1:1/steam", http_client=client).fetch_game("900000001")
            youtube = YouTubeGateway(api_key="synthetic-analyze-youtube", base_url="http://127.0.0.1:1/youtube/v3", http_client=client).fetch_creator("UCanalyzeFixture01")
            self.assertEqual((len(youtube.videos), sum(bool(video.thumbnail_urls) for video in youtube.videos)), (11, 2))
            gateway = DeepSeekGateway(api_key="synthetic-analyze-deepseek", base_url="http://127.0.0.1:1/deepseek", http_client=client)

            def text_stage(schema, bundle):
                model, budget = self.fixture.STAGES[schema.__name__][:2]
                output = gateway.complete_structured(model, list(bundle.messages), schema, max_tokens=budget)
                validate_stage_evidence(output, bundle.evidence_catalog)
                return output

            def visual_stage(schema, bundle):
                model, budget = self.fixture.STAGES[schema.__name__][:2]
                request = {"model": model, "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}, "messages": [
                    {"role": "system", "content": "JSON Schema: " + json.dumps(self.registry[schema.__name__])},
                    {"role": "user", "content": [{"type": "text", "text": render_vision_prompt(bundle.messages)}, *[{"type": "image_url", "image_url": {"url": self.fixture.INLINE_PNG}} for _ in bundle.image_urls]]},
                ]}
                if budget is not None:
                    request["max_tokens"] = budget
                status, response, label = self.fixture.dispatch("/deepseek/chat/completions", {}, request, {"Authorization": "Bearer synthetic-analyze-deepseek"}, schemas=self.registry)
                self.assertEqual(status, 200, label)
                self.events.append(label)
                output = schema.model_validate_json(response["choices"][0]["message"]["content"])
                validate_stage_evidence(output, bundle.evidence_catalog)
                return output

            extracted = text_stage(GameExtraction, build_game_extraction_bundle(steam))
            game_visual = visual_stage(GameVisualAnalysis, build_game_visual_bundle(steam))
            game = text_stage(GameSynthesis, build_game_synthesis_bundle(steam, extracted, game_visual))
            self.assertEqual(game.game_brief.positioning_premise.value, "Explore a quiet station and solve cooperative puzzles.")
            self.assertEqual(game.visual_style.evidence[0].reference, "game_visual:visual_style")
            digests = tuple(text_stage(CreatorVideoBatchDigest, build_creator_video_batch_bundle(youtube, batch_index=index)) for index in (0, 1))
            self.assertEqual(digests[1].content_format.content_focus.evidence[0].reference, "video:analyze11")
            creator_visual = visual_stage(CreatorVisualAnalysis, build_creator_visual_bundle(youtube, selected_asset_refs=("video:analyze01:thumbnail:0", "video:analyze02:thumbnail:0")))
            content = text_stage(CreatorContentFormatReduction, build_creator_content_format_bundle(digests))
            presentation = text_stage(CreatorPresentationReduction, build_creator_presentation_bundle(digests, visual=creator_visual))
            performance = text_stage(CreatorPerformanceAudienceReduction, build_creator_performance_audience_bundle(digests))
            commercial = text_stage(CreatorCommercialSafetyReduction, build_creator_commercial_safety_bundle(digests))
            contacts = build_creator_contact_evidence(youtube, pages=PublicPageGateway())
            brief = text_stage(CreatorBriefSynthesis, build_creator_brief_bundle(content_format=content, presentation=presentation, performance_audience=performance, commercial_safety=commercial, contact_evidence=contacts))
            synthesis = merge_creator_synthesis(content_format=content, presentation=presentation, performance_audience=performance, commercial_safety=commercial, brief=brief)
            bound = bind_creator_contacts(synthesis, contacts)
            self.assertEqual(brief.creator_brief.positioning.value, "Cooperative puzzle play")
            self.assertEqual(brief.creator_brief.positioning.evidence[0].reference, "reduction:content_format:content_summary")
            self.assertEqual(brief.public_email.candidate_id, "contact.email.0")
            self.assertIsNotNone(bound)
            self.assertEqual(self.events, ["steam", "youtube_channel", "youtube_playlist", "youtube_videos", "game_extraction", "game_visual", "game_synthesis", "creator_map_00", "creator_map_01", "creator_visual", "creator_content", "creator_presentation", "creator_performance", "creator_commercial", "creator_brief"])

    return unittest.defaultTestLoader.loadTestsFromTestCase(FixedBackendContracts)


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixed-contracts"]:
        result = unittest.TextTestRunner(verbosity=2).run(fixed_contract_suite())
        raise SystemExit(not result.wasSuccessful())
    unittest.main()
