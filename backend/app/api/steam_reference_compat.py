"""One opt-in response extension; keep installed internal.4 strict DTOs usable."""

import json
from starlette.responses import Response

HEADER = "X-FMG-Steam-References"


def legacy_projection(value):
    if isinstance(value, list):
        return [legacy_projection(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {
        key: legacy_projection(item)
        for key, item in value.items()
        if key != "steam_recommendations"
    }
    if {"id", "name", "url", "similarities", "reason"} <= result.keys():
        result.pop("source", None)
        result.pop("source_url", None)
    if isinstance(result.get("reference_works"), list):
        result["reference_works"] = [
            (
                {
                    key: item
                    for key, item in work.items()
                    if key not in {"source", "source_url"}
                }
                if isinstance(work, dict)
                else work
            )
            for work in result["reference_works"]
        ]
    return result


async def negotiate_steam_references(request, response):
    if not request.url.path.startswith("/api/v2/") or not response.headers.get(
        "content-type", ""
    ).startswith("application/json"):
        return response
    vary = response.headers.get("Vary")
    response.headers["Vary"] = f"{vary}, {HEADER}" if vary else HEADER
    if request.headers.get(HEADER) == "1":
        return response
    body = (
        b"".join([chunk async for chunk in response.body_iterator])
        if hasattr(response, "body_iterator")
        else response.body
    )
    projected = json.dumps(
        legacy_projection(json.loads(body)), ensure_ascii=False, separators=(",", ":")
    ).encode()
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() != "content-length"
    }
    return Response(
        projected,
        status_code=response.status_code,
        headers=headers,
        background=response.background,
    )
