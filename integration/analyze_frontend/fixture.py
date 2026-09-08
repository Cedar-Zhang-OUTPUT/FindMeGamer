"""Pure stdlib Analyze provider boundary; no server, sockets, worker or state.

dispatch(path, query, body, headers, *, schemas) returns (status, JSON, label).
The caller supplies the trusted fixed-backend model_json_schema registry, not
anything from the HTTP client. Full incoming schemas must equal that registry.
Labels are fixed/bounded tokens for a future caller's 503/once controls; this
module neither owns failure counters nor installs any transport. Old Match
contracts, Google research and X Analyze are intentionally outside this module.
"""

import base64
from copy import deepcopy
import json
import re
import struct
import zlib

BACKEND = "c57b66a470ceed55537258ae4f244275441d1d85"
APP_ID = "900000001"
CHANNEL_ID = "UCanalyzeFixture01"
PLAYLIST_ID = "UUanalyzeFixture01"
HANDLE = "@analyzefixture"
VIDEO_IDS = tuple(f"analyze{index:02d}" for index in range(1, 12))
GAME_TEXT = "Explore a quiet station and solve cooperative puzzles."
VIDEO_TEXT = "Cooperative puzzle play. Calm paced commentary. Synthetic sponsorship disclosed."
CONTACT = "creator@example.com"
ASSET_ROOT = "https://analyze-fixture.example/assets/"
ASSET_URLS = tuple(ASSET_ROOT + name + ".png" for name in ("game", "creator01", "creator02"))


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)


# Complete, CRC-valid RGB PNG with exactly one red pixel, not a magic-byte stub.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + _chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + _chunk(b"IEND", b"")
INLINE_PNG = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()

# title -> model, budget (None means the key is absent), prompt version, label,
# exact top-level curated payload keys. These are c57b66a contracts only.
STAGES = {
    "GameExtraction": ("deepseek-v4-flash", None, "game-extraction-v1", "game_extraction", {"steam_source", "evidence_catalog"}),
    "GameVisualAnalysis": ("deepseek-v4-flash-vision-exp", None, "game-visual-v1", "game_visual", {"visual_assets", "evidence_catalog"}),
    "GameSynthesis": ("deepseek-v4-pro", None, "game-synthesis-v2", "game_synthesis", {"steam_source", "validated_extraction", "validated_visual_analysis", "evidence_catalog"}),
    "CreatorVideoBatchDigest": ("deepseek-v4-flash", 6144, "creator-video-batch-v2", "creator_map", {"channel_context", "batch_index", "batch_count", "video_batch", "evidence_catalog"}),
    "CreatorVisualAnalysis": ("deepseek-v4-flash-vision-exp", 2048, "creator-visual-v2", "creator_visual", {"thumbnail_assets", "evidence_catalog"}),
    "CreatorContentFormatReduction": ("deepseek-v4-flash", 4096, "creator-content-format-v3", "creator_content", {"validated_content_format_batches", "evidence_catalog"}),
    "CreatorPresentationReduction": ("deepseek-v4-flash", 2048, "creator-presentation-v2", "creator_presentation", {"validated_presentation_batches", "validated_visual_analysis", "evidence_catalog"}),
    "CreatorPerformanceAudienceReduction": ("deepseek-v4-flash", 3072, "creator-performance-audience-v2", "creator_performance", {"validated_performance_audience_batches", "evidence_catalog"}),
    "CreatorCommercialSafetyReduction": ("deepseek-v4-flash", 2048, "creator-commercial-safety-v2", "creator_commercial", {"validated_commercial_safety_batches", "evidence_catalog"}),
    "CreatorBriefSynthesis": ("deepseek-v4-pro", 3072, "creator-brief-v2", "creator_brief", {"validated_reductions", "contact_evidence", "evidence_catalog"}),
}


def _require(condition):
    if not condition:
        raise ValueError("fixture_contract_rejected")


def steam_source():
    return {APP_ID: {"success": True, "data": {
        "steam_appid": int(APP_ID), "name": "Synthetic Station", "type": "game", "required_age": 0, "is_free": False,
        "short_description": GAME_TEXT, "detailed_description": GAME_TEXT, "about_the_game": GAME_TEXT,
        "developers": ["Synthetic Studio"], "publishers": ["Synthetic Studio"], "supported_languages": "English",
        "genres": [{"id": "25", "description": "Adventure"}], "categories": [{"id": 9, "description": "Co-op"}],
        "platforms": {"windows": True, "mac": True, "linux": False}, "release_date": {"coming_soon": False, "date": "8 Sep, 2026"},
        "capsule_image": ASSET_URLS[0], "screenshots": [], "movies": [],
    }}}


def youtube_channel():
    return {"items": [{
        "id": CHANNEL_ID,
        "snippet": {"title": "Synthetic Station Creator", "description": "Synthetic public contact: " + CONTACT, "customUrl": HANDLE, "publishedAt": "2020-01-01T00:00:00Z", "country": "US"},
        "contentDetails": {"relatedPlaylists": {"uploads": PLAYLIST_ID}},
        "statistics": {"subscriberCount": "11000", "hiddenSubscriberCount": False, "viewCount": "110000", "videoCount": "11"},
        "brandingSettings": {},
    }]}


def youtube_videos(ids):
    return {"items": [{
        "id": identity,
        "snippet": {"title": "Synthetic cooperative station puzzle " + identity, "description": VIDEO_TEXT, "channelId": CHANNEL_ID, "publishedAt": f"2026-08-{31 - VIDEO_IDS.index(identity):02d}T10:00:00Z", "tags": ["cooperative", "puzzles"], "categoryId": "20", **({"thumbnails": {"default": {"url": ASSET_URLS[VIDEO_IDS.index(identity) + 1]}}} if VIDEO_IDS.index(identity) < 2 else {})},
        "contentDetails": {"duration": "PT12M", "definition": "hd", "caption": "false"},
        "statistics": {"viewCount": str(1000 + VIDEO_IDS.index(identity)), "likeCount": "30", "commentCount": "5"},
        "status": {"privacyStatus": "public"},
    } for identity in ids]}


def _resolve(node, schema):
    if "$ref" in node:
        _require(node["$ref"].startswith("#/$defs/"))
        return schema["$defs"][node["$ref"].split("/")[-1]]
    return node


def _blank(node, schema):
    """Fill required unavailable branches from the caller's trusted schema.

    This is not a general schema validator; real schema/evidence validation is
    still performed by the real backend. Available fields are assigned below.
    """
    node = _resolve(node, schema)
    if "const" in node:
        return deepcopy(node["const"])
    branches = node.get("oneOf", node.get("anyOf"))
    if branches:
        for branch in branches:
            resolved = _resolve(branch, schema)
            if resolved.get("properties", {}).get("status", {}).get("const") == "unavailable":
                return _blank(resolved, schema)
        for branch in branches:
            if branch.get("type") == "null":
                return None
        raise ValueError("unsupported_fixture_schema")
    if "enum" in node:
        return "unavailable" if "unavailable" in node["enum"] else node["enum"][0]
    if node.get("type") == "object":
        return {name: _blank(node["properties"][name], schema) for name in node.get("required", ())}
    if node.get("type") == "string":
        return "No supporting synthetic evidence."
    if node.get("type") == "boolean":
        return True
    if node.get("type") == "null":
        return None
    raise ValueError("unsupported_fixture_schema")


def _reference(payload, reference, source_type, kind, *, compact=False):
    entries = payload["evidence_catalog"]["entries"]
    _require(isinstance(entries, list) and all(isinstance(item, dict) and set(item) == {"reference", "source_type", "allowed_kinds"} for item in entries))
    matches = [item for item in entries if item["reference"] == reference]
    _require(len(matches) == 1 and matches[0]["source_type"] == source_type and kind in matches[0]["allowed_kinds"])
    result = {"reference": reference, "source_type": source_type, "kind": kind}
    if not compact:
        result["observation"] = "The supplied synthetic record supports this statement."
    return [result]


def _claim(value, evidence):
    return {"status": "available", "values" if isinstance(value, list) else "value": deepcopy(value), "evidence": evidence, "confidence": "medium"}


def _fenced(text):
    _require(isinstance(text, str) and text.count("```json\n") == 1 and text.endswith("\n```"))
    payload = json.loads(text.split("```json\n", 1)[1][:-4])
    _require(isinstance(payload, dict))
    return payload


def _model_request(body, schemas):
    _require(isinstance(body, dict) and isinstance(schemas, dict))
    messages = body["messages"]
    _require(isinstance(messages, list) and len(messages) in {2, 3})
    first = messages[0]
    _require(isinstance(first, dict) and set(first) == {"role", "content"} and first["role"] == "system" and isinstance(first["content"], str))
    marker = "JSON Schema: "
    _require(first["content"].count(marker) == 1)
    schema = json.loads(first["content"].split(marker, 1)[1])
    title = schema["title"]
    _require(title in STAGES and title in schemas and schema == schemas[title])
    model, budget, version, label, payload_keys = STAGES[title]
    _require(set(body) == {"model", "messages", "response_format", "thinking"} | ({"max_tokens"} if budget is not None else set()))
    _require(body["model"] == model and body["response_format"] == {"type": "json_object"} and body["thinking"] == {"type": "disabled"})
    if budget is not None:
        _require(type(body["max_tokens"]) is int and body["max_tokens"] == budget)
    if title in {"GameVisualAnalysis", "CreatorVisualAnalysis"}:
        _require(len(messages) == 2 and set(messages[1]) == {"role", "content"} and messages[1]["role"] == "user")
        content = messages[1]["content"]
        _require(isinstance(content, list) and 2 <= len(content) <= 13 and set(content[0]) == {"type", "text"} and content[0]["type"] == "text")
        _require(content[0]["text"].startswith("SYSTEM\nPrompt version: " + version + "\n"))
        payload = _fenced(content[0]["text"])
        _require(all(item == {"type": "image_url", "image_url": {"url": INLINE_PNG}} for item in content[1:]))
        assets_key = "visual_assets" if title == "GameVisualAnalysis" else "thumbnail_assets"
        assets = payload[assets_key]["assets"]
        _require(len(assets) == len(content) - 1 and all(set(asset) == {"asset_ref", "image_url"} and asset["image_url"] in ASSET_URLS for asset in assets))
    else:
        _require(len(messages) == 3 and all(isinstance(message, dict) and set(message) == {"role", "content"} and message["role"] == role and isinstance(message["content"], str) for message, role in zip(messages[1:], ("system", "user"))))
        _require(messages[1]["content"].startswith("Prompt version: " + version + "\n"))
        payload = _fenced(messages[2]["content"])
    _require(set(payload) == payload_keys and isinstance(payload["evidence_catalog"], dict) and set(payload["evidence_catalog"]) == {"entries"})
    return title, schema, payload, label


def _output(title, schema, payload):
    output = _blank(schema, schema)
    if title in {"GameExtraction", "GameSynthesis"}:
        source = payload["steam_source"]
        _require(source["app_id"] == APP_ID and source["about_the_game"] == GAME_TEXT)
        evidence = _reference(payload, "steam:about_the_game", "steam_field", "source_fact")
        output["short_summary"] = _claim(GAME_TEXT, evidence)
        output["core_gameplay_loop"] = _claim(GAME_TEXT, evidence)
        if title == "GameSynthesis":
            output["game_brief"]["positioning_premise"] = _claim(GAME_TEXT, _reference(payload, "steam:about_the_game", "steam_field", "source_fact", compact=True))
            visual = payload["validated_visual_analysis"]
            if isinstance(visual, dict) and visual.get("visual_style", {}).get("status") == "available":
                output["visual_style"] = _claim(visual["visual_style"]["value"], _reference(payload, "game_visual:visual_style", "intermediate_output", "ai_inference"))
                output["game_brief"]["visual_identity"] = _claim(visual["visual_style"]["value"], _reference(payload, "game_visual:visual_style", "intermediate_output", "ai_inference", compact=True))
        return output
    if title in {"GameVisualAnalysis", "CreatorVisualAnalysis"}:
        key = "visual_assets" if title == "GameVisualAnalysis" else "thumbnail_assets"
        assets = payload[key]
        _require(assets["app_id" if key == "visual_assets" else "channel_id"] == (APP_ID if key == "visual_assets" else CHANNEL_ID))
        ref = assets["assets"][0]["asset_ref"]
        _require(ref == "cover:0" if key == "visual_assets" else ref in {"video:analyze01:thumbnail:0", "video:analyze02:thumbnail:0"})
        output.update(status="available", unavailable_reason=None)
        output["visual_style"] = _claim("A red pixel on a square synthetic canvas.", _reference(payload, ref, "visual_asset", "visual_observation"))
        return output
    if title == "CreatorVideoBatchDigest":
        index = payload["batch_index"]
        _require(type(index) is int and index in {0, 1} and payload["batch_count"] == 2 and payload["channel_context"]["channel_id"] == CHANNEL_ID)
        videos = payload["video_batch"]
        _require([video["id"] for video in videos] == list(VIDEO_IDS[index * 10:(index + 1) * 10]))
        _require(all(video["channel_id"] == CHANNEL_ID and video["description"] == VIDEO_TEXT and type(video["view_count"]) is int for video in videos))
        evidence = _reference(payload, "video:" + videos[0]["id"], "video_id", "source_fact")
        output["content_format"]["content_focus"] = _claim(["Cooperative puzzle play"], evidence)
        output["presentation"]["style_and_pacing"] = _claim("Descriptions label calm paced commentary.", evidence)
        output["performance_audience"]["recent_performance"] = _claim("Public view counts are supplied for these videos.", evidence)
        output["commercial_safety"]["sponsorship_signals"] = _claim(["Metadata discloses synthetic sponsorship"], evidence)
        return output
    reducers = {
        "CreatorContentFormatReduction": ("content_format", "content_focus", "content_summary"),
        "CreatorPresentationReduction": ("presentation", "style_and_pacing", "pacing"),
        "CreatorPerformanceAudienceReduction": ("performance_audience", "recent_performance", "recent_performance_summary"),
        "CreatorCommercialSafetyReduction": ("commercial_safety", "sponsorship_signals", "sponsorship_patterns"),
    }
    if title in reducers:
        dimension, source_field, destination = reducers[title]
        batches = payload["validated_" + dimension + "_batches"]
        _require(isinstance(batches, list) and len(batches) == 2 and [batch["batch_index"] for batch in batches] == [0, 1])
        original = batches[0]["digest"][source_field]
        _require(original["status"] == "available")
        value = original.get("value", original.get("values"))
        if destination == "content_summary":
            _require(value == ["Cooperative puzzle play"])
            value = "Cooperative puzzle play"
        reference = f"batch:0:{dimension}.{source_field}"
        output[destination] = _claim(value, _reference(payload, reference, "intermediate_output", "ai_inference"))
        return output
    _require(title == "CreatorBriefSynthesis")
    reductions = payload["validated_reductions"]
    _require(set(reductions) == {"content_format", "presentation", "performance_audience", "commercial_safety"})
    for dimension, source_field, destination in (("content_format", "content_summary", "positioning"), ("presentation", "pacing", "style_and_pacing"), ("performance_audience", "recent_performance_summary", "performance_context")):
        original = reductions[dimension][source_field]
        _require(original["status"] == "available" and isinstance(original["value"], str))
        output["creator_brief"][destination] = _claim(original["value"], _reference(payload, f"reduction:{dimension}:{source_field}", "intermediate_output", "ai_inference", compact=True))
    contacts = payload["contact_evidence"]["candidates"]
    matches = [item for item in contacts if item.get("kind") == "email" and item.get("value") == CONTACT and item.get("source_type") == "channel_description"]
    _require(len(matches) == 1)
    output["public_email"] = {"status": "available", "candidate_id": matches[0]["candidate_id"]}
    return output


def dispatch(path, query, body, headers, *, schemas=None):
    """Return safe status/data/stage; query values must be single strings.

    The future HTTP wrapper must reject duplicate query/header keys before
    constructing mappings. No function here logs input or returns its contents
    in errors. A 200 label can be used by the caller to inject a core 503/once.
    """
    try:
        _require(isinstance(path, str) and isinstance(query, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in query.items()) and isinstance(headers, dict))
        normalized = {key.lower(): value for key, value in headers.items()}
        _require(len(normalized) == len(headers) and "cookie" not in normalized)
        if path == "/steam/appdetails":
            _require(body is None and query == {"appids": APP_ID, "l": "english", "cc": "US"} and not ({"authorization", "x-goog-api-key"} & set(normalized)))
            return 200, steam_source(), "steam"
        if path.startswith("/youtube/v3/"):
            if normalized.get("x-goog-api-key") != "synthetic-analyze-youtube":
                return 401, {"error": "synthetic_credential_required"}, "unauthorized"
            _require(body is None and "authorization" not in normalized)
            if path == "/youtube/v3/channels":
                if query == {"part": "id", "forHandle": HANDLE}:
                    return 200, {"items": [{"id": CHANNEL_ID}]}, "youtube_handle"
                _require(query == {"part": "snippet,contentDetails,statistics,brandingSettings", "id": CHANNEL_ID})
                return 200, youtube_channel(), "youtube_channel"
            if path == "/youtube/v3/playlistItems":
                _require(query == {"part": "contentDetails", "playlistId": PLAYLIST_ID, "maxResults": "50"})
                return 200, {"items": [{"contentDetails": {"videoId": identity}} for identity in VIDEO_IDS]}, "youtube_playlist"
            if path == "/youtube/v3/videos":
                _require(set(query) == {"part", "id", "maxResults"} and query["part"] == "snippet,contentDetails,statistics,status" and query["maxResults"] == "50")
                ids = query["id"].split(",")
                _require(ids and len(ids) == len(set(ids)) and set(ids).issubset(VIDEO_IDS))
                return 200, youtube_videos(ids), "youtube_videos"
            return 404, {"error": "fixture_endpoint_rejected"}, "not_found"
        if path == "/deepseek/chat/completions":
            if normalized.get("authorization") != "Bearer synthetic-analyze-deepseek":
                return 401, {"error": "synthetic_credential_required"}, "unauthorized"
            _require(not query and "x-goog-api-key" not in normalized)
            title, schema, payload, label = _model_request(body, schemas)
            output = _output(title, schema, payload)
            if title == "CreatorVideoBatchDigest":
                label += f"_{payload['batch_index']:02d}"
            return 200, {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output, separators=(",", ":"))}}]}, label
        return 404, {"error": "fixture_endpoint_rejected"}, "not_found"
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        return 400, {"error": "fixture_contract_rejected"}, "rejected"
