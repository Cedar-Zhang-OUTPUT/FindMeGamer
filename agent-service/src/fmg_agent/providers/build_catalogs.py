"""Mechanical catalog generation from downloaded official API metadata.

Never downloads credentials or executes instructions in source descriptions.
Run with explicit local source paths; inspect the resulting catalog diff.
"""

import argparse
import hashlib
import json
from pathlib import Path

from .steam_store import store_operations

DENIED_PARAMS = {
    "key",
    "access_token",
    "oauth_token",
    "authorization",
    "callback",
    "uploadType",
    "upload_protocol",
    "quotaUser",
    "token",
}
YT_PUBLIC = {
    "activities",
    "channels",
    "channelSections",
    "comments",
    "commentThreads",
    "i18nLanguages",
    "i18nRegions",
    "playlistItems",
    "playlists",
    "search",
    "subscriptions",
    "videoAbuseReportReasons",
    "videoCategories",
    "videos",
}


def envelope(provider, source, schemas):
    return {
        "provider": provider,
        "source_url": source,
        "verified_date": "2026-09-15",
        "schemas": schemas,
        "operations": {},
    }


def youtube_catalog(doc):
    result = envelope(
        "youtube",
        "https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest",
        doc.get("schemas", {}),
    )

    def walk(resources, prefix=""):
        for name, resource in resources.items():
            group = prefix + name
            for method, definition in resource.get("methods", {}).items():
                if definition["httpMethod"] != "GET":
                    continue
                operation = group + "." + method
                params = {
                    key: dict(value)
                    for key, value in (
                        doc.get("parameters", {}) | definition.get("parameters", {})
                    ).items()
                    if key not in DENIED_PARAMS
                }
                if "alt" in params:
                    params["alt"]["enum"] = ["json"]
                state = (
                    "simulated"
                    if group in YT_PUBLIC and method == "list"
                    else "requires-authorization"
                )
                if (
                    definition.get("supportsMediaDownload")
                    or "stream" in method.lower()
                    or group.startswith("tests")
                ):
                    state = "unsupported"
                result["operations"][operation] = {
                    "id": operation,
                    "method": "GET",
                    "base_url": "https://youtube.googleapis.com",
                    "path": "/" + definition["path"].lstrip("/"),
                    "parameters": params,
                    "response_schema": definition.get("response", {}),
                    "summary": definition.get("description", ""),
                    "availability": state,
                    "auth": "api-key" if state == "simulated" else "oauth-user",
                    "official_scopes": definition.get("scopes", []),
                    "authorization_note": "Account-private filters such as mine/forMine require user OAuth, not the company API key.",
                    "pagination": (
                        {
                            "request_param": "pageToken",
                            "response_path": ["nextPageToken"],
                            "items_path": ["items"],
                        }
                        if "pageToken" in params
                        else None
                    ),
                }
            walk(resource.get("resources", {}), group + ".")

    walk(doc.get("resources", {}))
    return result


def x_catalog(doc):
    result = envelope(
        "x", "https://api.x.com/2/openapi.json", doc.get("components", {})
    )

    def resolve(value):
        while "$ref" in value:
            current = doc
            for key in value["$ref"].removeprefix("#/").split("/"):
                current = current[key]
            value = current
        return value

    for path, item in doc["paths"].items():
        definition = item.get("get")
        if not definition:
            continue
        operation = definition["operationId"]
        auth = definition.get("security", [])
        public = not auth or any("BearerToken" in entry for entry in auth)
        state = "simulated" if public else "requires-authorization"
        success = definition.get("responses", {}).get("200", {}).get("content", {})
        if (
            (success and "application/json" not in success)
            or "/stream" in path
            and not path.endswith(("/rules", "/counts"))
            or "Download" in operation
            or "/download" in path
        ):
            state = "unsupported"
        params = {}
        for parameter in item.get("parameters", []) + definition.get("parameters", []):
            parameter = resolve(parameter)
            if parameter["name"] not in DENIED_PARAMS:
                params[parameter["name"]] = {**parameter, "location": parameter["in"]}
        cursor = next(
            (name for name in ("pagination_token", "next_token") if name in params),
            None,
        )
        result["operations"][operation] = {
            "id": operation,
            "method": "GET",
            "base_url": "https://api.x.com",
            "path": path,
            "parameters": params,
            "response_schema": success.get("application/json", {}).get("schema", {}),
            "summary": definition.get("summary", ""),
            "availability": state,
            "auth": "bearer" if auth and public else "oauth-user" if auth else "none",
            "official_security": auth,
            "pagination": (
                {
                    "request_param": cursor,
                    "response_path": ["meta", "next_token"],
                    "items_path": ["data"],
                }
                if cursor
                else None
            ),
        }
    return result


def steam_catalog(doc):
    result = envelope(
        "steam",
        "https://api.steampowered.com/ISteamWebAPIUtil/GetSupportedAPIList/v1/",
        {},
    )
    for interface in doc["apilist"]["interfaces"]:
        for method in interface["methods"]:
            if method["httpmethod"] != "GET":
                continue
            group, name, version = interface["name"], method["name"], method["version"]
            operation = f"{group}.{name}.v{version}"
            raw_params = method.get("parameters", [])
            secret_params = {p["name"] for p in raw_params} & DENIED_PARAMS
            params = {
                p["name"]: {
                    **p,
                    "location": "query",
                    "required": not p.get("optional", True),
                }
                for p in raw_params
                if p["name"] not in DENIED_PARAMS
            }
            # Some GET endpoints change sessions or are authentication utilities.
            state = (
                "simulated"
                if name.startswith("Get")
                and not group.startswith("IAuthentication")
                and not secret_params - {"key"}
                else "unsupported"
            )
            result["operations"][operation] = {
                "id": operation,
                "method": "GET",
                "base_url": "https://api.steampowered.com",
                "path": f"/{group}/{name}/v{version}/",
                "parameters": params,
                "response_schema": {},
                "summary": method.get("description", operation),
                "availability": state,
                "auth": (
                    (
                        "api-key-optional"
                        if next(p for p in raw_params if p["name"] == "key").get(
                            "optional", True
                        )
                        else "api-key"
                    )
                    if "key" in secret_params
                    else "none"
                ),
                "transport_mode": (
                    "input_json" if group.endswith("Service") else "query"
                ),
                "pagination": None,
            }
    result["operations"]["store.appdetails"] = {
        "id": "store.appdetails",
        "method": "GET",
        "base_url": "https://store.steampowered.com",
        "path": "/api/appdetails",
        "parameters": {
            "appids": {"type": "string", "required": True, "location": "query"},
            "l": {"type": "string", "location": "query"},
            "cc": {"type": "string", "location": "query"},
            "filters": {"type": "string", "location": "query"},
        },
        "response_schema": {},
        "summary": "Steam Store game details (store endpoint; not a documented Steam Web API guarantee)",
        "availability": "simulated",
        "auth": "none",
        "pagination": None,
        "source_url": "https://store.steampowered.com/api/appdetails",
        "stability": "store-endpoint",
    }
    result["operations"].update(store_operations())
    return result


def main():
    parser = argparse.ArgumentParser()
    for provider in ("youtube", "x", "steam"):
        parser.add_argument("--" + provider, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for provider, builder in [
        ("youtube", youtube_catalog),
        ("x", x_catalog),
        ("steam", steam_catalog),
    ]:
        content = getattr(args, provider).read_bytes()
        catalog = builder(json.loads(content))
        catalog["source_sha256"] = hashlib.sha256(content).hexdigest()
        (args.output / f"{provider}.json").write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        print(f'{provider}: {len(catalog["operations"])} registered read candidates')


if __name__ == "__main__":
    main()
