"""Best-effort Steam Store HTML adapter, not a documented/stable official API."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit
import httpx
from app.analysis.contracts import SteamRecommendedItem, SteamRecommendations
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.http import (
    read_bounded_bytes,
    streaming_response,
    ResponseTooLarge,
    InvalidContentLength,
)

MAX_RECOMMENDATIONS = 9
RECOMMENDATION_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


class _ReleasedParser(HTMLParser):
    def __init__(self, source_id):
        super().__init__(convert_charrefs=True)
        self.source_id = source_id
        self.depth = 0
        self.section_depth = None
        self.found = False
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self.depth += 1
            if attrs.get("id") == "released" and not self.found:
                self.found = True
                self.section_depth = self.depth
        if (
            tag != "a"
            or self.section_depth is None
            or len(self.ids) >= MAX_RECOMMENDATIONS
        ):
            return
        if "similar_grid_capsule" not in attrs.get("class", "").split():
            return
        app_id = attrs.get("data-ds-appid", "")
        if not re.fullmatch(r"[1-9][0-9]{0,9}", app_id) or int(app_id) > 2147483647:
            return
        try:
            url = urlsplit(attrs.get("href", ""))
            valid = (
                url.scheme == "https"
                and url.netloc == "store.steampowered.com"
                and re.match(r"^/app/" + app_id + r"(?:/|$)", url.path)
            )
        except ValueError:
            return
        if valid and app_id != self.source_id and app_id not in self.ids:
            self.ids.append(app_id)

    def handle_endtag(self, tag):
        if tag == "div":
            if self.section_depth == self.depth:
                self.section_depth = None
            self.depth -= 1


def recommended_app_ids(html, source_id):
    parser = _ReleasedParser(source_id)
    parser.feed(html)
    if not parser.found:
        raise ValueError("Steam released recommendations section missing")
    return parser.ids


def fetch_recommendations(client, app_id, fetch_details):
    url = f"https://store.steampowered.com/recommended/morelike/app/{app_id}/"
    metadata = {"source_url": url, "fetched_at": datetime.now(UTC)}
    failures = (
        httpx.HTTPError,
        ValueError,
        PermanentIntegrationError,
        TransientIntegrationError,
        ResponseTooLarge,
        InvalidContentLength,
    )
    try:
        with streaming_response(
            client,
            "GET",
            url,
            params={"l": "english", "cc": "US"},
            timeout=RECOMMENDATION_TIMEOUT,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                return SteamRecommendations(status="unavailable", **metadata)
            body = read_bounded_bytes(response, max_bytes=2_000_000).decode("utf-8")
        ids = recommended_app_ids(body, app_id)
    except failures:
        return SteamRecommendations(status="unavailable", **metadata)

    def named_item(target_id):
        try:
            game = fetch_details(target_id)
            if game.type != "game" or not game.name.strip():
                return None
            return SteamRecommendedItem(
                app_id=target_id,
                name=game.name[:255],
                url=f"https://store.steampowered.com/app/{target_id}/",
            )
        except failures:
            return None

    with ThreadPoolExecutor(max_workers=3) as executor:
        items = tuple(
            item for item in executor.map(named_item, ids) if item is not None
        )
    status = (
        "available"
        if len(items) == len(ids)
        else ("partial" if items else "unavailable")
    )
    return SteamRecommendations(status=status, items=items, **metadata)
