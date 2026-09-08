"""Read all bounded query candidates, classify known evidence, then page."""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.discovery import DiscoveryCandidate
from app.db.models.discovery_evaluation import EvaluationRun, EvaluationItem
from app.db.models.profiles import CreatorProfile
from app.repositories.creator_library import detail
from app.repositories.library_queries import current_works, descending


def evidence_groups(creator, source):
    groups = set()
    game = source.get("game") or {}
    game_id = game.get("id") if isinstance(game, dict) else None
    refs = {
        r["name"].strip().casefold()
        for r in source.get("references", [])
        if r.get("name")
    }
    for work in current_works(creator):
        if not (work.evidence_excerpt and work.verification_notes):
            continue
        if work.game_id and str(work.game_id) == game_id:
            groups.add("current_game")
        elif work.work_name and work.work_name.casefold() in refs:
            groups.add("reference_game")
        else:
            groups.add("related_content")
    return [
        group
        for group in ("current_game", "reference_game", "related_content")
        if group in groups
    ]


def relevance_values(session, query_id):
    from app.repositories.discovery_evaluation import result_rows

    run = session.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.query_id == query_id, EvaluationRun.status == "completed")
        .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
        .limit(1)
    )
    if run is None:
        return {}
    items = session.scalars(
        select(EvaluationItem).where(EvaluationItem.run_id == run.id)
    ).all()
    projected = {v["candidate_id"]: v for v in result_rows(session, run, items)}
    return {
        item.candidate_id: (
            None if projected[item.candidate_id]["stale"] else item.score,
            (
                "stale"
                if projected[item.candidate_id]["stale"]
                else "available" if item.score is not None else "not_evaluated"
            ),
        )
        for item in items
    }


def candidate_page(
    session, query, *, evidence, sort, limit, offset, candidate_ids=None
):
    statement = select(DiscoveryCandidate).where(
        DiscoveryCandidate.query_id == query.id
    )
    if candidate_ids is not None:
        statement = statement.where(DiscoveryCandidate.id.in_(candidate_ids))
    candidates = session.scalars(statement).all()
    creators = {
        c.id: c
        for c in session.scalars(
            select(CreatorProfile)
            .where(CreatorProfile.id.in_([row.creator_id for row in candidates]))
            .options(
                selectinload(CreatorProfile.works),
                selectinload(CreatorProfile.contacts),
            )
        )
    }
    relevance = relevance_values(session, query.id) if sort == "relevance" else {}
    ranked = []
    for row in candidates:
        creator = creators.get(row.creator_id)
        identity_changed = (
            creator is None
            or creator.identity_revision != row.identity_revision
            or creator.platform != row.platform
            or (creator.platform_account_id or creator.youtube_channel_id)
            != row.account_id
        )
        current = detail(creator) if creator else None
        groups = (
            evidence_groups(creator, query.source_snapshot)
            if creator and not identity_changed
            else []
        )
        if (
            evidence == "none"
            and groups
            or evidence not in ("all", "none")
            and evidence not in groups
        ):
            continue
        score, relevance_status = relevance.get(row.id, (None, "not_evaluated"))
        if identity_changed:
            score = None
            relevance_status = "stale" if row.id in relevance else "not_evaluated"
        item = {
            "id": row.id,
            "creator_id": row.creator_id,
            "platform": row.platform,
            "account_id": row.account_id,
            "account": row.account_snapshot,
            "creator": current,
            "filter_notes": row.filter_notes,
            "identity_revision": row.identity_revision,
            "identity_changed": identity_changed,
            "selected": False,
            "added_at": row.added_at,
            "evidence_groups": groups,
            "relevance_status": relevance_status,
        }
        if sort == "followers":
            primary = descending(
                current.follower_count if current and not identity_changed else None
            )
        elif sort == "recent_publish":
            primary = descending(
                current.latest_published_at
                if current and not identity_changed
                else None
            )
        elif sort == "recent_added":
            primary = descending(row.added_at)
        elif sort == "relevance":
            primary = descending(score)
        else:
            primary = ()
        ranked.append(((*primary, row.ordinal, str(row.id)), item))
    ranked.sort(key=lambda pair: pair[0])
    return {
        "items": [v for _, v in ranked[offset : offset + limit]],
        "total": len(ranked),
        "limit": limit,
        "offset": offset,
    }
