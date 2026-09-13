"""Durable independent query cursors inside the existing query JSONB snapshot."""

from sqlalchemy import select


def select_direction(conditions, platform, state):
    directions = conditions.get("query_directions", {}).get(platform)
    if not directions:
        return None
    saved = state.get("directions", {})
    offset = state.get("next_direction", 0) % len(directions)
    for step in range(len(directions)):
        index = (offset + step) % len(directions)
        query = directions[index]
        if saved.get(query, {}).get("status") != "exhausted":
            return query, saved.get(query, {}).get("cursor")
    return None


def record_direction(conditions, platform, previous, result, request):
    directions = conditions.get("query_directions", {}).get(platform)
    if not directions:
        return result
    entries = dict(previous.get("directions", {}))
    entries[request["query"]] = {
        k: result.get(k)
        for k in ("status", "cursor", "issues", "provider_items_received")
    }
    result["directions"] = entries
    result["next_direction"] = (directions.index(request["query"]) + 1) % len(
        directions
    )
    if result["status"] in ("more", "exhausted"):
        result["status"] = (
            "more"
            if any(entries.get(q, {}).get("status") != "exhausted" for q in directions)
            else "exhausted"
        )
    return result


def upgrade_legacy_plan(session, query):
    """Only called by explicit start/continue, never a GET or background migration.

    Existing attempts and budgets remain intact. Never replay the old paid query;
    if a new direction is identical, carry over its exact cursor and outcome.
    """
    if query.conditions.get("query_directions"):
        return
    from app.db.models.discovery_plan import DiscoveryPlan
    from app.discovery.planning import provider_query_directions
    from app.schemas.discovery_plan_output import SearchPlanOutput

    plan = session.scalar(
        select(DiscoveryPlan).where(DiscoveryPlan.query_id == query.id)
    )
    if not plan or not plan.output:
        return
    raw_output = {k: plan.output[k] for k in ("summary", "rationale", "queries")}
    game_name = (plan.source_snapshot.get("game") or {}).get("name", "")
    directions = provider_query_directions(
        SearchPlanOutput.model_validate(raw_output), game_name
    )
    providers = [dict(p) for p in query.conditions["providers"]]
    states = dict(query.provider_states)
    for provider in providers:
        platform = provider["platform"]
        previous = dict(states.get(platform, {}))
        entries = {}
        old_query = provider["query"]
        if old_query in directions[platform] and previous.get("status"):
            entries[old_query] = {
                k: previous.get(k)
                for k in ("status", "cursor", "issues", "provider_items_received")
            }
        if platform == "youtube":
            provider["max_requests"] = 3
        previous["directions"] = entries
        previous["next_direction"] = 0
        if previous.get("status") == "exhausted" and len(entries) < len(
            directions[platform]
        ):
            previous["status"] = "more"
        states[platform] = previous
    query.conditions = {
        **query.conditions,
        "providers": providers,
        "query_directions": directions,
    }
    query.provider_states = states
