from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import threading
import time
from urllib.parse import parse_qs, urlsplit


STATE = Path(os.environ.get("FAKE_STATE_DIR", "/integration-state"))
STATE.mkdir(parents=True, exist_ok=True)
UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)


def unavailable() -> dict[str, str]:
    return {"status": "unavailable", "reason": "The supplied evidence is silent."}


def unavailable_inference() -> dict[str, str]:
    return {
        "status": "unavailable",
        "reason": "The supplied evidence is silent.",
        "provenance": "ai_inference",
    }


def creator_metadata() -> dict[str, object]:
    fields = (
        "primary_games",
        "genres",
        "formats",
        "style",
        "pacing",
        "livestream_tendency",
        "long_form_tendency",
        "short_form_tendency",
        "recent_performance_summary",
        "engagement_summary",
        "publishing_frequency_context",
        "sponsorship_patterns",
        "brand_safety_signals",
        "collaboration_risks",
    )
    return {
        "english_language_check": True,
        **{field: unavailable() for field in fields},
    }


def creator_synthesis() -> dict[str, object]:
    analysis_fields = (
        "content_summary",
        "primary_games",
        "genres",
        "formats",
        "style",
        "pacing",
        "production_quality",
        "livestream_tendency",
        "long_form_tendency",
        "short_form_tendency",
        "recent_performance_summary",
        "engagement_summary",
        "publishing_frequency_context",
        "representative_video_context",
        "sponsorship_patterns",
        "brand_safety",
        "suitable_game_types",
        "collaboration_risks",
    )
    brief_fields = (
        "positioning",
        "content_focus",
        "formats",
        "style_and_pacing",
        "performance_context",
        "promotion_fit",
        "brand_safety",
        "suitable_game_types",
        "collaboration_risks",
    )
    result: dict[str, object] = {
        "english_language_check": True,
        **{field: unavailable() for field in analysis_fields},
        "audience_inference": {
            "primary_language": unavailable_inference(),
            "likely_regions": unavailable_inference(),
            "interests": unavailable_inference(),
        },
        "public_email": unavailable(),
        "linked_site": unavailable(),
        "social_links": unavailable(),
        "creator_brief": {
            **{field: unavailable() for field in brief_fields},
            "audience": unavailable_inference(),
        },
    }
    return result


def game_extraction() -> dict[str, object]:
    fields = (
        "short_summary",
        "core_gameplay_loop",
        "themes",
        "tone",
        "target_audience",
        "key_selling_points",
        "content_hooks",
        "comparable_games",
        "suitable_creator_types",
        "promotion_risks",
    )
    return {
        "english_language_check": True,
        **{field: unavailable() for field in fields},
    }


def game_synthesis() -> dict[str, object]:
    fields = (
        "short_summary",
        "core_gameplay_loop",
        "themes",
        "visual_style",
        "tone",
        "target_audience",
        "key_selling_points",
        "content_hooks",
        "comparable_games",
        "suitable_creator_types",
        "promotion_risks",
    )
    brief_fields = (
        "positioning_premise",
        "core_gameplay_loop",
        "genres",
        "themes",
        "tone",
        "visual_identity",
        "target_audience",
        "key_selling_points",
        "content_hooks",
        "comparable_games",
        "suitable_creator_types",
        "promotion_risks",
    )
    return {
        "english_language_check": True,
        **{field: unavailable() for field in fields},
        "game_brief": {field: unavailable() for field in brief_fields},
    }


def pairwise(creator_id: str) -> dict[str, object]:
    dimension = {
        "analysis": "The supplied profile supports a qualitative fit.",
        "evidence": ["The locked profile is the evidence used for this comparison."],
    }
    return {
        "english_language_check": True,
        "creator_id": creator_id,
        "content_fit": dimension,
        "audience_fit": dimension,
        "performance_fit": dimension,
        "promotion_fit": dimension,
        "brand_safety": dimension,
        "strengths": ["The creator is suitable for the deterministic campaign."],
        "risks": ["Launch timing still requires coordination."],
        "evidence": ["The locked creator snapshot was reviewed."],
        "match_reasons": ["The content format fits the game."],
    }


def ranking(creator_ids: list[str]) -> dict[str, object]:
    items = []
    for order, creator_id in enumerate(creator_ids):
        score = 0.90 - order * 0.05
        items.append(
            {
                "creator_id": creator_id,
                "total_score": score,
                "dimension_scores": {
                    "content_fit": score,
                    "audience_fit": score,
                    "performance_fit": score,
                    "promotion_fit": score,
                    "brand_safety": score,
                },
                "backend_order": order,
                "result_group": "recommended",
                "qualitative_label": "Strong Match",
                "dimension_outcomes": {
                    "content_fit": "The content aligns with the game.",
                    "audience_fit": "The audience is suitable.",
                    "performance_fit": "The performance context is suitable.",
                    "promotion_fit": "The format supports promotion.",
                    "brand_safety": "No concern appears in supplied evidence.",
                },
                "match_reasons": ["The creator is a strong qualitative fit."],
            }
        )
    return {"english_language_check": True, "items": items}


def append_log(line: str) -> None:
    with (STATE / "calls.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{line}\n")


def block_until_process_stops(marker: str) -> None:
    path = STATE / marker
    if path.exists():
        return
    path.write_text("entered\n", encoding="utf-8")
    while True:
        time.sleep(1)


def youtube_payload(endpoint: str, query: dict[str, list[str]]) -> dict[str, object]:
    if endpoint == "channels":
        channel_id = query.get("id", ["UCunknown0"])[0]
        if channel_id == "UCrecovery01":
            block_until_process_stops("analysis-blocked")
        append_log(f"youtube channels {channel_id}")
        return {
            "items": [
                {
                    "id": channel_id,
                    "snippet": {
                        "title": f"Creator {channel_id[-2:]}",
                        "description": "",
                    },
                    "contentDetails": {
                        "relatedPlaylists": {"uploads": f"UU{channel_id[2:]}"}
                    },
                    "statistics": {
                        "subscriberCount": "1000",
                        "viewCount": "5000",
                        "videoCount": "1",
                    },
                    "brandingSettings": {},
                }
            ]
        }
    if endpoint == "playlistItems":
        playlist = query.get("playlistId", ["UUunknown"])[0]
        suffix = playlist[2:]
        append_log(f"youtube playlistItems {suffix}")
        return {"items": [{"contentDetails": {"videoId": f"video-{suffix}"}}]}
    if endpoint == "videos":
        ids = query.get("id", ["video-unknown"])[0].split(",")
        append_log("youtube videos")
        return {
            "items": [
                {
                    "id": video_id,
                    "snippet": {
                        "title": f"Video {video_id}",
                        "publishedAt": "2026-09-01T00:00:00Z",
                        "channelId": f"UC{video_id.removeprefix('video-')}",
                    },
                    "contentDetails": {"duration": "PT10M"},
                    "statistics": {
                        "viewCount": "1000",
                        "likeCount": "100",
                        "commentCount": "10",
                    },
                    "status": {"privacyStatus": "public"},
                }
                for video_id in ids
            ]
        }
    return {"items": []}


class Handler(BaseHTTPRequestHandler):
    server_version = "FMGIntegrationFake/1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def reply(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, default=str, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/youtube/v3/"):
            self.reply(
                youtube_payload(parsed.path.rsplit("/", 1)[-1], parse_qs(parsed.query))
            )
            return
        if parsed.path == "/steam/appdetails":
            app_id = parse_qs(parsed.query).get("appids", ["1245620"])[0]
            append_log(f"steam appdetails {app_id}")
            self.reply(
                {
                    app_id: {
                        "success": True,
                        "data": {
                            "steam_appid": int(app_id),
                            "type": "game",
                            "name": "Integration Strategy Game",
                            "is_free": False,
                            "developers": ["Integration Studio"],
                            "publishers": ["Integration Publisher"],
                            "release_date": {
                                "coming_soon": False,
                                "date": "1 Sep, 2026",
                            },
                            "short_description": "A deterministic strategy game.",
                            "about_the_game": "Build a resilient settlement.",
                            "genres": [{"description": "Strategy"}],
                            "categories": [{"description": "Single-player"}],
                            "platforms": {"windows": True, "mac": True, "linux": True},
                            "supported_languages": "English",
                            "recommendations": {"total": 100},
                            "review_score_desc": "Positive",
                        },
                    }
                }
            )
            return
        self.reply({"error": "not_found"}, 404)

    def do_PUT(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        append_log("s3 put_object")
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) if length else b"{}")
        schema_name = body.get("response_format", {}).get("json_schema", {}).get("name")
        messages = json.dumps(body.get("messages", []), separators=(",", ":"))
        creator_ids = list(dict.fromkeys(UUID_PATTERN.findall(messages)))
        append_log(f"deepseek {schema_name}")
        if schema_name == "CreatorMetadataAnalysis":
            payload = creator_metadata()
        elif schema_name == "CreatorSynthesis":
            payload = creator_synthesis()
        elif schema_name == "GameExtraction":
            payload = game_extraction()
        elif schema_name == "GameSynthesis":
            payload = game_synthesis()
        elif schema_name == "ScreeningOutput":
            payload = {
                "english_language_check": True,
                "selected": [
                    {
                        "creator_id": creator_id,
                        "screening_reason": "The creator is a plausible fit.",
                        "evidence": ["The locked compact brief was reviewed."],
                    }
                    for creator_id in creator_ids
                ],
            }
        elif schema_name == "PairwiseMatchBrief":
            if len(creator_ids) != 1:
                self.reply({"error": "bad_pairwise_identity"}, 500)
                return
            creator_id = creator_ids[0]
            append_log(f"pairwise-call {creator_id}")
            completed = STATE / "pairwise-completed"
            completed_ids = (
                set(completed.read_text().splitlines()) if completed.exists() else set()
            )
            if completed_ids and creator_id not in completed_ids:
                block_until_process_stops(f"match-blocked-{creator_id}")
            payload = pairwise(creator_id)
            if creator_id not in completed_ids:
                with completed.open("a", encoding="utf-8") as stream:
                    stream.write(f"{creator_id}\n")
        elif schema_name == "FinalRankingOutput":
            payload = ranking(creator_ids)
        else:
            self.reply({"error": "unknown_schema"}, 500)
            return
        self.reply(
            {"choices": [{"message": {"content": json.dumps(payload, default=str)}}]}
        )


server = ThreadingHTTPServer(("127.0.0.1", 18081), Handler)
server.daemon_threads = True
stop = threading.Event()


def shutdown(_signum: int, _frame: object) -> None:
    stop.set()
    threading.Thread(target=server.shutdown, daemon=True).start()


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
server.serve_forever(poll_interval=0.2)
server.server_close()
