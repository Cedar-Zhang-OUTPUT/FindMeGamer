"""Versioned marginal-cost estimates, never provider invoices.

List-price estimates intentionally precede account discounts/free allowances and
X's best-effort daily deduplication (including calls outside this gateway).
"""

from datetime import date
from decimal import Decimal

VERSION = "fmg-usd-2026-09-15-v1"
X_SOURCE = "https://docs.x.com/x-api/getting-started/pricing"
GEMINI_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"

POSTS = set(
    "searchPostsRecent searchPostsAll getPostsById getPostsByIds getUsersPosts getUsersMentions getUsersLikedPosts getUsersTimeline getUsersBookmarks getUsersBookmarksByFolderId getListsPosts getSpacesPosts getPostsQuotedPosts searchEligiblePosts".split()
)
USERS = set(
    "getUsersById getUsersByIds getUsersByUsername getUsersByUsernames getUsersMe searchUsers getUsersFollowers getUsersFollowing getListsFollowers getListsMembers getPostsLikingUsers getPostsRepostedBy getSpacesBuyers".split()
)
LISTS = set(
    "getListsById getUsersFollowedLists getUsersOwnedLists getUsersPinnedLists getUsersListMemberships".split()
)
SPACES = set("getSpacesById getSpacesByIds getSpacesByCreatorIds searchSpaces".split())


def estimate(
    provider, operation, status, *, data=None, usage=None, model=None, price_date=None
):
    result = {
        "estimated_cost": None,
        "actual_cost": None,
        "currency": "USD",
        "pricing_version": VERSION,
        "complete": False,
        "line_items": [],
        "unpriced_components": [],
        "source_url": None,
        "basis": "list_price_before_discounts_and_daily_deduplication",
    }
    total = Decimal(0)

    def add(component, units, rate):
        nonlocal total
        amount = Decimal(units) * Decimal(rate)
        total += amount
        result["line_items"].append(
            {
                "component": component,
                "quantity": units,
                "unit_price_usd": str(rate),
                "estimated_cost": str(amount),
            }
        )

    def unknown(reason):
        result["unpriced_components"].append(reason)

    if provider in {"youtube", "steam"} and status == "succeeded":
        add("provider_request", 1, "0")
        result["basis"] = "zero_marginal_api_charge_excludes_hosting_and_quota"
        result["source_url"] = (
            "https://developers.google.com/youtube/v3/determine_quota_cost"
            if provider == "youtube"
            else "https://steamcommunity.com/dev"
        )
    elif provider == "x" and status == "succeeded":
        result["source_url"] = X_SOURCE
        primary = (
            "posts"
            if operation in POSTS
            else (
                "users"
                if operation in USERS
                else (
                    "lists"
                    if operation in LISTS
                    else (
                        "spaces"
                        if operation in SPACES
                        else (
                            "communities"
                            if operation in {"getCommunitiesById", "searchCommunities"}
                            else None
                        )
                    )
                )
            )
        )
        data = data if isinstance(data, dict) else {}
        if primary is None:
            unknown("unsupported_operation_pricing")
        else:
            resources = {primary: data.get("data")}
            if (
                resources[primary] is None
                and data.get("meta", {}).get("result_count") == 0
            ):
                resources[primary] = []
            for key, values in (data.get("includes") or {}).items():
                kind = "posts" if key == "tweets" else key
                if kind not in {"posts", "users", "lists", "spaces", "communities"}:
                    unknown("unpriced_expansion:" + key)
                    continue
                current = resources.get(kind, [])
                resources[kind] = (
                    current if isinstance(current, list) else [current]
                ) + (values if isinstance(values, list) else [values])
            for kind, values in resources.items():
                values = values if isinstance(values, list) else [values]
                if any(
                    not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    for item in values
                ):
                    unknown("resource_count_unavailable:" + kind)
                    continue
                add(
                    kind,
                    len({item["id"] for item in values}),
                    "0.010" if kind == "users" else "0.005",
                )
    elif provider == "gemini":
        result["basis"] = "list_price_before_discounts_and_free_allowances"
        result["source_url"] = GEMINI_SOURCE
        result["model"] = model
        usage = usage or {}
        if model not in {"gemini-3.8-flash", "gemini-3.7-flash"}:
            unknown("model_pricing_unavailable")
        elif not all(
            type(usage.get(k)) is int and usage[k] >= 0
            for k in ("promptTokenCount", "candidatesTokenCount")
        ):
            unknown("token_usage_unavailable")
        else:
            multiplier = (
                1 if (price_date or date.today().isoformat()) < "2027-01-01" else 2
            )
            cached = usage.get("cachedContentTokenCount", 0)
            prompt = usage["promptTokenCount"]
            if cached > prompt:
                unknown("invalid_cached_token_count")
            else:
                add(
                    "input_tokens",
                    prompt - cached,
                    str(Decimal("0.00000075") * multiplier),
                )
                add(
                    "cached_input_tokens",
                    cached,
                    str(Decimal("0.000000075") * multiplier),
                )
                add(
                    "output_and_thinking_tokens",
                    usage["candidatesTokenCount"] + usage.get("thoughtsTokenCount", 0),
                    str(Decimal("0.00000375") * multiplier),
                )
            if "search_queries" in usage:
                add(
                    "google_search_queries_before_free_allowance",
                    usage["search_queries"],
                    "0.014",
                )
            else:
                unknown("grounding_usage_unavailable")
    else:
        unknown("request_outcome_or_pricing_unavailable")
    if result["line_items"]:
        result["estimated_cost"] = str(total)
    result["complete"] = not result["unpriced_components"]
    return result
