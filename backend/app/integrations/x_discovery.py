"""Official recent public post search with attributable author metadata."""

import re

from app.integrations.x import XGateway
from app.integrations.youtube import _optional_count
from app.integrations.errors import PermanentIntegrationError
from app.discovery.planning import HomepageCandidate, matches, normalize_language


class XDiscovery(XGateway):
    def search(self, queries, conditions, *, limit=100):
        seen = set()
        budget = 3
        for query in queries[:3]:
            token = None
            tokens = set()
            # Query text is sanitized by the planner. Language operators are hints;
            # returned post metadata still determines filter acceptance.
            languages = " OR ".join("lang:" + v for v in conditions.content_languages)
            expression = f"({query}) -is:retweet" + (
                f" ({languages})" if languages else ""
            )
            while budget and len(seen) < min(limit, 100):
                budget -= 1
                params = {
                    "query": expression[:512],
                    "max_results": "100",
                    "expansions": "author_id",
                    "tweet.fields": "author_id,lang",
                    "user.fields": "name,public_metrics",
                }
                if token:
                    params["next_token"] = token
                payload = self._request_json("tweets/search/recent", params)
                try:
                    posts = payload.get("data", [])
                    if (
                        payload.get("errors")
                        or not isinstance(posts, list)
                        or len(posts) > 100
                    ):
                        raise ValueError()
                    if not posts and payload.get("meta", {}).get("result_count") != 0:
                        raise ValueError()
                    authors = {}
                    for post in posts:
                        author = post["author_id"]
                        language = normalize_language(post.get("lang"))
                        authors.setdefault(author, set())
                        if language:
                            authors[author].add(language)
                    users = payload.get("includes", {}).get("users", [])
                    if not isinstance(users, list) or len(users) > 100:
                        raise ValueError()
                    page = []
                    for user in users:
                        identity = user["id"]
                        if identity not in authors or identity in seen:
                            continue
                        candidate = HomepageCandidate(
                            platform="x",
                            platform_account_id=identity,
                            canonical_url=f"https://x.com/i/user/{identity}",
                            display_name=user["name"],
                            followers=_optional_count(
                                user.get("public_metrics", {}).get("followers_count")
                            ),
                            content_languages=sorted(authors[identity]),
                        )
                        if matches(candidate, conditions):
                            page.append(candidate)
                            seen.add(identity)
                            if len(seen) >= min(limit, 100):
                                break
                    yield page
                except (ValueError, TypeError, KeyError, AttributeError):
                    raise PermanentIntegrationError("x_response_invalid") from None
                token = payload.get("meta", {}).get("next_token")
                if not token or token in tokens:
                    break
                if not isinstance(token, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,1024}", token
                ):
                    raise PermanentIntegrationError("x_response_invalid")
                tokens.add(token)
