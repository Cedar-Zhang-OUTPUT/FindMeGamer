"""Only provider/download boundaries for pinned 5706ad7; never business fakes."""

import http.client
import importlib.util
import json
import os
from pathlib import Path
from threading import Lock, Thread
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

spec = importlib.util.spec_from_file_location("analyze_data", Path(__file__).with_name("fixture.py"))
data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data)

USER_FIELDS = "name,username,description,public_metrics,location,profile_image_url,protected"
POST_FIELDS = "author_id,created_at,lang,public_metrics"
ASSET_HOST = "analyze-fixture.example"
SYNTHETIC_IP = "93.184.216.34"  # Validation token only; never connected or resolved.
X_ID = "900000001"
X_PATHS = {f"/x/2/users/{X_ID}", f"/x/2/users/{X_ID}/tweets"}
SOURCE_PATHS = {"/steam/appdetails", "/youtube/v3/channels", "/youtube/v3/playlistItems", "/youtube/v3/videos", *X_PATHS}


def asset_path(url):
    if url not in data.ASSET_URLS:
        raise ValueError("Synthetic asset rejected")
    return urlsplit(url).path


class AssetResolver:
    def resolve(self, hostname, port, **_):
        if hostname != ASSET_HOST or port != 443:
            raise ValueError("Synthetic resolver rejected")
        return [SYNTHETIC_IP]


class AssetTransport:
    def __init__(self, **_):
        pass

    def request(self, *, url, connect_ip, port, host_header, server_hostname,
                connect_timeout, read_timeout, max_response_bytes, deadline, clock):
        from app.integrations.public_pages import RawPageResponse

        path = asset_path(url)
        if (connect_ip, port, host_header, server_hostname) != (SYNTHETIC_IP, 443, ASSET_HOST, ASSET_HOST):
            raise ValueError("Synthetic connection rejected")
        # Real HTTP download on the same strict local fixture, then real loader
        # MIME/magic-byte/size/Base64 processing. Never use the synthetic public IP.
        connection = http.client.HTTPConnection("127.0.0.1", 18081, timeout=min(read_timeout, max(0.01, deadline-clock())))
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read(max_response_bytes + 1)
            return RawPageResponse(response.status, response.getheader("Content-Type"), len(body), None, (body,))
        finally:
            connection.close()


def x_source(path, query):
    user = {"id": X_ID, "name": "Synthetic X Puzzle Creator", "username": "synthetic_puzzles", "description": "Cooperative puzzle commentary. Contact xcreator@example.com", "protected": False, "public_metrics": {"followers_count": 12000}}
    if path == f"/x/2/users/{X_ID}" and query == {"user.fields": USER_FIELDS}:
        return 200, {"data": user}, "x_user"
    if path == f"/x/2/users/{X_ID}/tweets" and query == {"max_results": "50", "exclude": "retweets,replies", "tweet.fields": POST_FIELDS}:
        posts = [{"id": str(910000001 + index), "author_id": X_ID, "text": "Synthetic cooperative puzzle commentary.", "created_at": f"2026-08-{index+1:02d}T10:00:00Z", "lang": "en", "public_metrics": {"like_count": 30, "reply_count": 2, "retweet_count": 1}} for index in range(21)]
        return 200, {"data": posts, "meta": {"result_count": 21}}, "x_posts"
    return 400, {"error": "synthetic_x_contract_rejected"}, "rejected"


def x_model(body, schema):
    try:
        assert set(body) == {"model", "messages", "response_format", "thinking", "max_tokens"}
        assert body["model"] == "deepseek-v4-flash" and body["max_tokens"] == 4096
        assert body["response_format"] == {"type": "json_object"} and body["thinking"] == {"type": "disabled"}
        messages = body["messages"]
        assert len(messages) == 3 and [m["role"] for m in messages] == ["system", "system", "user"]
        assert json.loads(messages[0]["content"].split("JSON Schema: ")[-1]) == schema
        prefix, raw = messages[-1]["content"].split("\n", 1)
        assert prefix == "SOURCE_JSON_UNTRUSTED_EVIDENCE"
        payload = json.loads(raw)
        assert payload["coverage"] == "recent_account_posts" and payload["more_available"] is False
        if "posts" in payload:
            assert set(payload) == {"account", "coverage", "more_available", "posts"}
            ids = [p["source_id"] for p in payload["posts"]]
            assert ids and len(ids) <= 10
            assert all(identity in {str(910000001+i) for i in range(21)} for identity in ids)
            label = f"x_map_{(int(ids[0])-910000001)//10:02d}"
        else:
            assert set(payload) == {"coverage", "more_available", "validated_intermediate_interpretations"}
            intermediates = payload["validated_intermediate_interpretations"]
            assert len(intermediates) == 3
            ids = intermediates[0]["content_summary"]["cited_source_ids"]
            label = "x_final"
        output = {"english_language_check": True, "content_summary": {"status": "available", "text": "Synthetic cooperative puzzle commentary.", "cited_source_ids": [ids[0]], "kind": "ai_inference"}}
        output.update({key: {"status": "unavailable", "reason": "Insufficient synthetic evidence."} for key in ("content_style", "audience_inference", "promotion_fit", "brand_safety")})
        return 200, {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]}, label
    except (AssertionError, ValueError, KeyError, TypeError, IndexError):
        return 400, {"error": "synthetic_x_model_rejected"}, "rejected"


def install():
    match_path = Path("/harness/fixture.py")
    if not match_path.exists():
        match_path = Path(__file__).resolve().parent.parent / "match_frontend/fixture.py"
    match_spec = importlib.util.spec_from_file_location("analyze_match_boundary", match_path)
    match = importlib.util.module_from_spec(match_spec)
    match_spec.loader.exec_module(match)
    from app.integrations import deepseek, public_pages
    from app.integrations.vision_images import VisionImageLoader
    from app.schemas import ai_game, ai_creator, ai_creator_map_reduce
    from app.schemas.x_analysis import XAnalysisSignals

    registry = {}
    for title in data.STAGES:
        schema = next(getattr(module, title) for module in (ai_game, ai_creator, ai_creator_map_reduce) if hasattr(module, title))
        registry[title] = schema.model_json_schema()
    deepseek.VisionImageLoader = lambda: VisionImageLoader(resolver=AssetResolver(), transport=AssetTransport())
    public_pages.SocketResolver = AssetResolver
    public_pages.PinnedHTTPTransport = AssetTransport

    def allowed(url):
        parsed = urlsplit(str(url))
        return match.destination_allowed(url) or (parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port == 18081 and not parsed.username and not parsed.password and not parsed.fragment and parsed.path in SOURCE_PATHS)

    class Handler(match.Handler):
        def controlled_analyze(self, label):
            path = self.server.state_directory / "analyze-control.json"
            try:
                control = json.loads(path.read_text())
            except FileNotFoundError:
                control = {"stage": "none", "mode": "none", "token": "none"}
            if control.get("stage") != label:
                return False
            if control.get("mode") == "once":
                with self.server.control_lock:
                    marker = "fault-" + control["token"]
                    if marker in self.server.used_faults:
                        return False
                    self.server.used_faults.add(marker)
            elif control.get("mode") != "always":
                return False
            self.reply(503, {"error": "synthetic_failure"}, label)
            return True

        def do_GET(self):
            parsed = urlsplit(self.path)
            if self.path in {urlsplit(url).path for url in data.ASSET_URLS}:
                match.event(self.server.state_directory, "asset_download", 200)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data.PNG_BYTES)))
                self.end_headers()
                self.wfile.write(data.PNG_BYTES)
                return
            if parsed.path not in SOURCE_PATHS:
                return super().do_GET()
            params = parse_qs(parsed.query, keep_blank_values=True)
            if any(len(v) != 1 for v in params.values()) or any(len(self.headers.get_all(k)) != 1 for k in self.headers):
                return self.reply(400, {"error": "duplicate_input"})
            query = {k: v[0] for k, v in params.items()}
            if parsed.path.endswith("channels") and query.get("part") == "snippet,statistics":
                return super().do_GET()
            headers = dict(self.headers)
            if parsed.path in X_PATHS:
                if not self.auth("x"):
                    return self.reply(401, {"error": "synthetic_credential_required"})
                status, body, label = x_source(parsed.path, query)
            else:
                if headers.get("X-Goog-Api-Key") == match.KEYS["youtube"]:
                    headers["X-Goog-Api-Key"] = "synthetic-analyze-youtube"
                status, body, label = data.dispatch(parsed.path, query, None, headers, schemas=registry)
            if status != 200 or not self.controlled_analyze(label):
                self.reply(status, body, label)

        def do_POST(self):
            if self.path != "/deepseek/chat/completions":
                return super().do_POST()
            if not self.auth("deepseek"):
                return self.reply(401, {"error": "synthetic_credential_required"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_000_000:
                    raise ValueError()
                raw = self.rfile.read(length)
                body = json.loads(raw)
                title = json.loads(body["messages"][0]["content"].split("JSON Schema: ")[-1])["title"]
            except (ValueError, KeyError, TypeError, IndexError):
                return self.reply(400, {"error": "synthetic_contract_rejected"})
            if title not in registry and title != "XAnalysisSignals":
                import io
                self.rfile = io.BytesIO(raw)
                return super().do_POST()
            if title == "XAnalysisSignals":
                status, response, label = x_model(body, XAnalysisSignals.model_json_schema())
            else:
                status, response, label = data.dispatch(self.path, {}, body, {"Authorization": "Bearer synthetic-analyze-deepseek"}, schemas=registry)
            if status != 200 or not self.controlled_analyze(label):
                self.reply(status, response, label)

    def start(state_directory, *, port=18081):
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        server.daemon_threads = True
        server.state_directory = Path(state_directory)
        server.control_lock, server.used_faults = Lock(), set()
        Thread(target=server.serve_forever, daemon=True).start()
        return server

    return allowed, start
