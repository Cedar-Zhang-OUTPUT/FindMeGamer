"""Generate a reviewed read-only catalog from a local official HTML snapshot.

No runtime scraping. Explicit public allowlist prevents new privileged endpoints
from becoming callable merely because Twitch adds them to its documentation.
"""

import argparse
import hashlib
import html
import json
import re
from pathlib import Path

SOURCE = "https://dev.twitch.tv/docs/api/reference/"
PUBLIC = set(
    "get-cheermotes get-channel-information get-channel-emotes get-global-emotes get-emote-sets get-channel-chat-badges get-global-chat-badges get-chat-settings get-shared-chat-session get-user-chat-color get-clips get-content-classification-labels get-top-games get-games get-channel-stream-schedule search-categories search-channels get-streams get-channel-teams get-teams get-users get-user-active-extensions get-videos".split()
)
ALTERNATIVES = {
    "get-videos": ["id", "user_id", "game_id"],
    "get-clips": ["id", "broadcaster_id", "game_id"],
    "get-games": ["id", "name", "igdb_id"],
    "get-teams": ["name", "id"],
    "get-users": ["id", "login"],
}


def plain(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def table(section, title):
    body = re.search(
        r"<h3[^>]*>" + title + r"</h3>(.*?)(?=<h3|$)", section, re.S | re.I
    )
    match = re.search(r"<table[^>]*>(.*?)</table>", body[1], re.S) if body else None
    if not match:
        return []
    return [
        [plain(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", match[1], re.S)
        if "<td" in row
    ]


def twitch_catalog(source):
    doc = {
        "provider": "twitch",
        "source_url": SOURCE,
        "verified_date": "2026-09-16",
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "schemas": {},
        "operations": {},
    }
    sections = re.split(r'<h2 id="([^"]+)"[^>]*>(.*?)</h2>', source)
    for index in range(1, len(sections), 3):
        slug, title, section = sections[index : index + 3]
        url = re.search(
            r"GET https://api\.twitch\.tv(/helix/[a-zA-Z0-9_/]+)",
            plain(section.split("<h3>Example Request")[0]),
        )
        if not url:
            continue
        words = slug.split("-")
        name = words[0] + "".join(w.title() for w in words[1:])
        params = {}
        for row in table(section, "Request Query Parameters?"):
            if len(row) != 4:
                raise ValueError(f"Unrecognized parameter table: {name}")
            key, kind, required, description = row
            schema = {
                "type": (
                    "boolean"
                    if kind.lower() == "boolean"
                    else "integer" if kind.lower() == "integer" else "string"
                )
            }
            if key == "first":
                schema = {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25 if slug == "get-channel-stream-schedule" else 100,
                }
            params[key] = {
                "location": "query",
                "required": required.lower() == "yes"
                and key not in ALTERNATIVES.get(slug, []),
                "schema": schema,
                "description": description,
            }
        auth = re.search(r"<h3[^>]*>Authorization</h3>(.*?)(?=<h3)", section, re.S)
        authorization = plain(auth[1]) if auth else "See official documentation."
        state = (
            "simulated"
            if slug in PUBLIC or slug == "get-channel-followers"
            else "requires-authorization"
        )
        if slug in {
            "get-extension-secrets",
            "get-stream-key",
            "get-channel-icalendar",
            "get-all-stream-tags",
            "get-stream-tags",
        }:
            state = "unsupported"
        doc["operations"][name] = {
            "id": name,
            "summary": plain(title),
            "method": "GET",
            "base_url": "https://api.twitch.tv",
            "path": url[1],
            "availability": state,
            "auth": "twitch-app" if slug in PUBLIC else "twitch-user",
            "authorization_note": authorization,
            "parameters": params,
            "response_schema": {"type": "object", "additionalProperties": True},
            "response_fields": table(section, "Response Body"),
            "source_url": SOURCE + "#" + slug,
            "pagination": (
                {
                    "request_param": "after",
                    "response_path": ["pagination", "cursor"],
                    "items_path": (
                        ["data", "segments"]
                        if slug == "get-channel-stream-schedule"
                        else ["data"]
                    ),
                }
                if "after" in params
                else None
            ),
        }
        if slug in ALTERNATIVES:
            doc["operations"][name]["selector_group"] = ALTERNATIVES[slug]
        if slug in {"get-videos", "get-clips", "get-teams"}:
            doc["operations"][name]["exclusive_selectors"] = True
    if not all(
        name in doc["operations"]
        for name in (
            "getUsers",
            "getChannelFollowers",
            "getVideos",
            "searchCategories",
            "getStreams",
        )
    ):
        raise ValueError("Incomplete Twitch source")
    return doc


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            twitch_catalog(args.source.read_text()), ensure_ascii=False, indent=2
        )
        + "\n"
    )
