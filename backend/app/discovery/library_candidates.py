"""Bounded Library pages, transaction-local and independent of live collection."""

from math import ceil
from uuid import UUID

from sqlalchemy import select

from app.db.models.discovery import DiscoveryCandidate
from app.core.creator_identity import creator_account_key
from app.db.models.profiles import CreatorProfile
from app.discovery.library import evaluate_candidate, _time
from app.repositories.creator_library import effective_fields
from app.schemas.discovery import DiscoveredAccount


def add_candidate(session, query, creator, account, notes, source):
    existing = session.scalar(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.query_id == query.id,
            DiscoveryCandidate.platform == account.platform,
            DiscoveryCandidate.account_id == account.account_id,
        )
    )
    if existing:
        sources = list(existing.filter_notes.get("discovery_sources", []))
        if source not in sources:
            existing.filter_notes = {
                **existing.filter_notes,
                "discovery_sources": [*sources, source],
            }
        return False
    if query.result_count >= query.conditions.get("result_limit", 600):
        return False
    query.result_count += 1
    session.add(
        DiscoveryCandidate(
            query_id=query.id,
            creator_id=creator.id,
            platform=account.platform,
            account_id=account.account_id,
            identity_revision=creator.identity_revision,
            account_snapshot=account.model_dump(mode="json"),
            filter_notes={**notes, "discovery_sources": [source]},
            ordinal=query.result_count,
        )
    )
    session.flush()
    return True


def scan_library(session, query, batch):
    providers = query.conditions["providers"]
    target = max(1, ceil(batch.target_count / len(providers)))
    states = dict(query.provider_states)
    for provider in providers:
        platform = provider["platform"]
        state = dict(states.get(platform, {}))
        library = dict(state.get("library", {}))
        if (
            library.get("status") == "complete"
            or library.get("_batch") == batch.ordinal
        ):
            continue
        statement = (
            select(CreatorProfile)
            .where(
                CreatorProfile.platform == platform,
                CreatorProfile.created_at <= query.created_at,
            )
            .order_by(CreatorProfile.id)
        )
        if library.get("_cursor"):
            statement = statement.where(CreatorProfile.id > UUID(library["_cursor"]))
        rows = list(session.scalars(statement.limit(201)))
        scanned = added = 0
        for creator in rows[:200]:
            if added >= target or query.result_count >= query.conditions.get(
                "result_limit", 600
            ):
                break
            scanned += 1
            library["_cursor"] = str(creator.id)
            fields = effective_fields(creator)
            account_id = creator_account_key(creator)
            account = DiscoveredAccount(
                platform=platform,
                account_id=account_id,
                profile_url=creator.canonical_url,
                display_name=fields.name,
                handle=fields.handle,
                description=fields.description,
                follower_count=fields.follower_count,
                country=fields.country_code,
                avatar_url=fields.avatar_url,
                collected_at=_time(
                    (creator.current_facts or {}).get("metadata_collected_at")
                )
                or creator.last_analyzed_at
                or creator.created_at,
            )
            eligible, notes = evaluate_candidate(
                session, creator, account, [], query.conditions.get("filters", {})
            )
            if eligible:
                added += int(
                    add_candidate(session, query, creator, account, notes, "library")
                )
        library.update(
            status="more" if scanned < len(rows) else "complete",
            scanned_count=library.get("scanned_count", 0) + scanned,
            added_count=library.get("added_count", 0) + added,
            _batch=batch.ordinal,
        )
        states[platform] = {**state, "library": library}
    query.provider_states = states
