"""Strict synthetic upstream HTTP server, used only by this integration launcher."""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import time
from urllib.parse import parse_qs, urlsplit

KEYS = {name: f"synthetic-match-{name}" for name in ("youtube", "x", "deepseek")}
PATHS = {
    "/youtube/v3/search",
    "/youtube/v3/channels",
    "/x/2/tweets/search/recent",
    "/deepseek/chat/completions",
}
DEFAULT_CONTROL = {"source_fail": "none", "model_fail": "none", "hold": "none"}
SCHEMAS = {
    "SearchPlanOutput": ("planning", "deepseek-v4-flash"),
    "EvaluationScreenOutput": ("screening", "deepseek-v4-flash"),
    "EvaluationMatchBrief": ("deep", "deepseek-v4-pro"),
    "EvaluationRankOutput": ("ranking", "deepseek-v4-pro"),
    "SlotValues": ("drafting", "deepseek-v4-flash"),
}
DRAFT_SCHEMA = {
    "title": "SlotValues",
    "type": "object",
    "additionalProperties": False,
    "required": ["firstName", "channelName", "reference", "observation"],
    "properties": {
        name: {"type": "string", "minLength": 1, "maxLength": 600, "title": title}
        for name, title in (
            ("firstName", "Firstname"),
            ("channelName", "Channelname"),
            ("reference", "Reference"),
            ("observation", "Observation"),
        )
    },
}


def destination_allowed(url):
    parsed = urlsplit(str(url))
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.port == 18081
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and parsed.path in PATHS
    )


def write_control(directory, values):
    allowed = {
        "source_fail": {"none", "youtube", "x"},
        "model_fail": {"none", "all", "planning", "screening", "deep", "ranking", "drafting"},
        "hold": {"none", "youtube", "x", "planning", "screening", "deep", "ranking", "drafting"},
    }
    if set(values) != set(allowed) or any(
        values[key] not in options for key, options in allowed.items()
    ):
        raise ValueError("Unsupported test control")
    temporary = Path(directory) / f"control-{os.getpid()}.tmp"
    with os.fdopen(
        os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        json.dump(values, stream)
    temporary.replace(Path(directory) / "control.json")


def control(directory):
    path = Path(directory) / "control.json"
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        # Docker Desktop bind mounts may briefly hide an atomically replaced file.
        return dict(DEFAULT_CONTROL)


def event(directory, endpoint, status):
    # Fixed endpoint labels and status only: no prompts, URLs, IDs, credentials or bodies.
    line = json.dumps({"endpoint": endpoint, "status": status}) + "\n"
    descriptor = os.open(
        Path(directory) / "events.jsonl", os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600
    )
    try:
        os.write(descriptor, line.encode())
    finally:
        os.close(descriptor)


def model_output(title, data):
    if title == "SlotValues":
        if not isinstance(data, dict) or set(data) != {
            "firstName", "channelName", "reference", "recorded_observation"
        }:
            raise ValueError("Unsupported drafting payload")
        recorded = data["recorded_observation"]
        if (
            not isinstance(recorded, dict)
            or set(recorded) != {"evidence_excerpt", "verification_notes"}
            or any(not isinstance(value, str) or not value.strip() for value in recorded.values())
        ):
            raise ValueError("Recorded observation required")
        # Only punctuation is normalized; notes cannot invent an observation.
        clause = recorded["evidence_excerpt"].strip().rstrip(".").rstrip()
        if not clause:
            raise ValueError("Recorded observation required")
        values = {key: data[key] for key in ("firstName", "channelName", "reference")}
        values["observation"] = clause + "."
        for value in values.values():
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= 600
                or value != value.strip()
                or re.search(r"[\x00-\x1f\x7f<>{}]", value)
                or re.search(
                    r"\[(?:first name|channel name|reference game\s*/\s*video|unfilled[^\]]*|specific observation[^\]]*)\]",
                    value,
                    re.IGNORECASE,
                )
            ):
                raise ValueError("Unsupported drafting slot")
        return values
    if title == "SearchPlanOutput":
        platforms = data["conditions"]["platforms"]
        if not platforms or not set(platforms).issubset({"youtube", "x", "twitch", "instagram"}):
            raise ValueError("Unsupported platform")
        return {
            "summary": "Find creators covering cozy cooperative garden adventures.",
            "rationale": "The supplied game and reference describe cooperative gardening and exploration.",
            "queries": [
                {"platform": platform, "terms": ["cozy cooperative gardening"]}
                for platform in platforms
            ],
        }
    if title == "EvaluationScreenOutput":
        return {
            "selected_ids": [
                candidate["candidate_id"] for candidate in data["candidates"]
            ]
        }
    if title == "EvaluationMatchBrief":
        candidate = data["candidate"]
        return {
            "candidate_id": candidate["candidate_id"],
            "summary": "Recorded content metadata suggests a possible fit for this cozy cooperative adventure.",
            "content_fit": "The available titles and descriptions concern cooperative or cozy games.",
            "audience_fit": "Audience country and audience interests remain unknown.",
            "limitations": [
                "Only synthetic recorded metadata is available; further evidence is needed."
            ],
            "cited_work_ids": [work["id"] for work in candidate["works"][:2]],
            "confidence": "limited",
        }
    if title == "EvaluationRankOutput":
        return {
            "items": [
                {"candidate_id": brief["candidate_id"], "score": 65}
                for brief in data["briefs"]
            ]
        }
    raise ValueError("Unsupported schema")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, body, label="rejected"):
        event(self.server.state_directory, label, status)
        content = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def auth(self, service):
        header = "X-Goog-Api-Key" if service == "youtube" else "Authorization"
        expected = KEYS[service] if service == "youtube" else "Bearer " + KEYS[service]
        alternate = "Authorization" if service == "youtube" else "X-Goog-Api-Key"
        return (
            self.headers.get_all(header) == [expected]
            and alternate not in self.headers
            and "Cookie" not in self.headers
        )

    def controlled(self, label, service):
        current = control(self.server.state_directory)
        if current["hold"] == label or current["hold"] == service:
            event(self.server.state_directory, label, "held")
            deadline = (
                time.monotonic() + 15
            )  # Below source timeout; no forgotten permanent hold.
            while time.monotonic() < deadline:
                current = control(self.server.state_directory)
                if current["hold"] not in {label, service}:
                    break
                time.sleep(0.05)
        if current["source_fail"] == service or (
            service == "deepseek" and current["model_fail"] in {"all", label}
        ):
            self.reply(503, {"error": "synthetic_failure"}, label)
            return True
        return False

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path not in PATHS or path == "/deepseek/chat/completions":
            return self.reply(404, {"error": "fixture_endpoint_rejected"})
        service = "youtube" if path.startswith("/youtube/") else "x"
        label = "youtube_channels" if path.endswith("/channels") else service
        if not self.auth(service):
            return self.reply(401, {"error": "synthetic_credential_required"})
        params = parse_qs(parsed.query, keep_blank_values=True)
        if any(len(value) != 1 for value in params.values()):
            return self.reply(400, {"error": "fixture_query_rejected"})
        params = {key: value[0] for key, value in params.items()}
        try:
            if path.endswith("/channels"):
                if (
                    set(params) != {"part", "id"}
                    or params["part"] != "snippet,statistics"
                ):
                    raise ValueError()
                ids = params["id"].split(",")
                if not ids or not set(ids).issubset(
                    {"UCmatchA001", "UCmatchB002", "UCmatchC003"}
                ):
                    raise ValueError()
                body = {"items": [channel(identity) for identity in ids]}
            elif service == "youtube":
                if not {"part", "type", "q", "maxResults"}.issubset(params) or not set(
                    params
                ).issubset(
                    {
                        "part",
                        "type",
                        "q",
                        "maxResults",
                        "pageToken",
                        "regionCode",
                        "relevanceLanguage",
                    }
                ):
                    raise ValueError()
                if (
                    params["part"] != "snippet"
                    or params["type"] != "video"
                    or not 1 <= int(params["maxResults"]) <= 50
                    or not params["q"]
                ):
                    raise ValueError()
                token = params.get("pageToken")
                if token not in {None, "yt-page-2"}:
                    raise ValueError()
                page = (
                    [
                        ("gardenA1", "UCmatchA001"),
                        ("gardenA2", "UCmatchA001"),
                        ("gardenB1", "UCmatchB002"),
                    ]
                    if token is None
                    else [("gardenA1", "UCmatchA001"), ("gardenC1", "UCmatchC003")]
                )
                body = {
                    "items": [
                        {
                            "id": {"videoId": video},
                            "snippet": {
                                "channelId": account,
                                "channelTitle": channel(account)["snippet"]["title"],
                                "title": "Cozy cooperative garden adventure",
                                "description": "Synthetic gardening game metadata",
                                "publishedAt": "2026-09-01T10:00:00Z",
                            },
                        }
                        for video, account in page
                    ]
                }
                if token is None:
                    body["nextPageToken"] = "yt-page-2"
            else:
                required = {
                    "query",
                    "max_results",
                    "expansions",
                    "tweet.fields",
                    "user.fields",
                }
                if (
                    not required.issubset(params)
                    or not set(params).issubset(required | {"next_token"})
                    or params["expansions"] != "author_id"
                    or not 10 <= int(params["max_results"]) <= 100
                    or not params["query"]
                ):
                    raise ValueError()
                token = params.get("next_token")
                if token not in {None, "x-page-2"}:
                    raise ValueError()
                page = (
                    [("8101", "7101"), ("8102", "7101"), ("8103", "7102")]
                    if token is None
                    else [("8101", "7101"), ("8104", "7103")]
                )
                ids = list(dict.fromkeys(account for _, account in page))
                body = {
                    "data": [
                        {
                            "id": post,
                            "author_id": account,
                            "text": "Synthetic cozy cooperative gardening game discussion",
                            "lang": "en",
                            "created_at": "2026-09-01T10:00:00Z",
                            "public_metrics": {"like_count": 7},
                        }
                        for post, account in page
                    ],
                    "includes": {"users": [x_user(identity) for identity in ids]},
                    "meta": {"result_count": len(page)},
                }
                if token is None:
                    body["meta"]["next_token"] = "x-page-2"
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {"error": "fixture_query_rejected"})
        if not self.controlled(label, service):
            self.reply(200, body, label)

    def do_POST(self):
        if self.path != "/deepseek/chat/completions":
            return self.reply(404, {"error": "fixture_endpoint_rejected"})
        if not self.auth("deepseek"):
            return self.reply(401, {"error": "synthetic_credential_required"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1_000_000:
                raise ValueError()
            request = json.loads(self.rfile.read(size))
            if set(request) - {
                "model",
                "messages",
                "response_format",
                "thinking",
                "max_tokens",
            } or request["response_format"] != {"type": "json_object"}:
                raise ValueError()
            schema_text = request["messages"][0]["content"]
            if not isinstance(schema_text, str):
                raise ValueError()
            schema = json.loads(schema_text.split("JSON Schema: ")[-1])
            title = schema["title"]
            label, model = SCHEMAS[title]
            if request["model"] != model or request["messages"][-1]["role"] != "user":
                raise ValueError()
            if title == "SlotValues" and (
                schema != DRAFT_SCHEMA
                or request.get("thinking") != {"type": "disabled"}
                or type(request.get("max_tokens")) is not int
                or request["max_tokens"] != 2048
                or not isinstance(request["messages"], list)
                or len(request["messages"]) != 3
                or any(
                    not isinstance(message, dict)
                    or set(message) != {"role", "content"}
                    or message["role"] != role
                    or not isinstance(message["content"], str)
                    or not message["content"].strip()
                    for message, role in zip(request["messages"], ("system", "system", "user"))
                )
            ):
                raise ValueError()
            data = json.loads(request["messages"][-1]["content"])
            body = model_output(title, data)
        except (ValueError, KeyError, TypeError, IndexError):
            return self.reply(400, {"error": "fixture_model_contract_rejected"})
        if not self.controlled(label, "deepseek"):
            self.reply(
                200,
                {
                    "id": "synthetic-completion",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(body),
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 80,
                        "completion_tokens": 100,
                        "total_tokens": 180,
                    },
                },
                label,
            )


def channel(identity):
    names = {
        "UCmatchA001": "Garden Party Games",
        "UCmatchB002": "Quiet Orchard",
        "UCmatchC003": "Cooperative Trails",
    }
    snippet = {
        "title": names[identity],
        "description": "Synthetic cozy and cooperative game creator",
        "customUrl": "@" + identity,
    }
    stats = {"subscriberCount": "4200", "hiddenSubscriberCount": False}
    if identity == "UCmatchB002":
        stats = {"hiddenSubscriberCount": True}
    else:
        snippet["country"] = "US"
    return {"id": identity, "snippet": snippet, "statistics": stats}


def x_user(identity):
    names = {
        "7101": "Sprout Co-op",
        "7102": "Mossy Controller",
        "7103": "Orchard Expeditions",
    }
    return {
        "id": identity,
        "name": names[identity],
        "username": "fixture" + identity,
        "description": "Synthetic cozy game notes",
        "public_metrics": {} if identity == "7102" else {"followers_count": 1300},
    }


def start_server(state_directory, *, port=18081):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.state_directory = Path(state_directory)
    Thread(target=server.serve_forever, daemon=True).start()
    return server
