"""Bounded video search -> public author homepages; never full Creator analysis."""

from app.integrations.youtube import (
    YouTubeGateway,
    _items,
    _optional_count,
    _page_token,
)
from app.integrations.errors import PermanentIntegrationError
from app.discovery.planning import HomepageCandidate, matches, normalize_language


class YouTubeDiscovery(YouTubeGateway):
    def search(self, queries, conditions, *, limit=100):
        seen = set()
        budget = 3
        for query in queries[:3]:
            token = None
            tokens = set()
            while budget and len(seen) < min(limit, 100):
                budget -= 1
                params = {
                    "part": "snippet",
                    "type": "video",
                    "q": query,
                    "maxResults": "50",
                }
                if token:
                    params["pageToken"] = token
                payload = self._request_json("search", params)
                try:
                    items = _items(payload, limit=50)
                    video_ids = list(
                        dict.fromkeys(item["id"]["videoId"] for item in items)
                    )
                    channel_ids = list(
                        dict.fromkeys(item["snippet"]["channelId"] for item in items)
                    )
                    if not video_ids:
                        break
                    videos = _items(
                        self._request_json(
                            "videos", {"part": "snippet", "id": ",".join(video_ids)}
                        ),
                        limit=50,
                    )
                    languages = {}
                    for video in videos:
                        if video.get("id") not in video_ids:
                            continue
                        snippet = video.get("snippet", {})
                        language = normalize_language(
                            snippet.get("defaultAudioLanguage")
                        )
                        if language:
                            languages.setdefault(snippet.get("channelId"), set()).add(
                                language
                            )
                    channels = _items(
                        self._request_json(
                            "channels",
                            {"part": "snippet,statistics", "id": ",".join(channel_ids)},
                        ),
                        limit=50,
                    )
                    page = []
                    for channel in channels:
                        identity = channel["id"]
                        if identity not in channel_ids or identity in seen:
                            continue
                        stats = channel.get("statistics", {})
                        candidate = HomepageCandidate(
                            platform="youtube",
                            platform_account_id=identity,
                            display_name=channel["snippet"]["title"],
                            canonical_url=f"https://www.youtube.com/channel/{identity}",
                            followers=(
                                None
                                if stats.get("hiddenSubscriberCount")
                                else _optional_count(stats.get("subscriberCount"))
                            ),
                            content_languages=sorted(languages.get(identity, set())),
                        )
                        if matches(candidate, conditions):
                            page.append(candidate)
                            seen.add(identity)
                            if len(seen) >= min(limit, 100):
                                break
                    yield page
                except (ValueError, TypeError, KeyError, AttributeError):
                    raise PermanentIntegrationError(
                        "youtube_response_invalid"
                    ) from None
                token = payload.get("nextPageToken")
                if not token or token in tokens:
                    break
                if not isinstance(token, str) or not _page_token.fullmatch(token):
                    raise PermanentIntegrationError("youtube_response_invalid")
                tokens.add(token)
