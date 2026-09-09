"""Bounded effective records, not acquisition JSON or sender-viewing evidence."""

import hashlib
import json

from app.repositories.creator_library import effective_fields, work_detail
from app.core.creator_identity import creator_account_key

GAME_FIELDS = ("name", "description", "tags", "developer", "languages", "release_date")
CREATOR_FIELDS = (
    "name",
    "public_name",
    "handle",
    "description",
    "follower_count",
    "languages",
    "country_code",
    "country_name",
    "source_notes",
    "internal_notes",
    "interest_notes",
)
WORK_FIELDS = (
    "id",
    "revision",
    "work_name",
    "content_title",
    "content_type",
    "game_id",
    "source_url",
    "published_at",
    "evidence_excerpt",
    "verification_notes",
    "timestamp_seconds",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def bounded(value, *, depth=0):
    if depth > 6:
        return None
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, list):
        return [bounded(v, depth=depth + 1) for v in value[:20]]
    if isinstance(value, dict):
        return {
            k: bounded(v, depth=depth + 1)
            for k, v in list(value.items())[:40]
            if not any(
                part in k.lower()
                for part in (
                    "contact",
                    "email",
                    "url",
                    "thumbnail",
                    "raw",
                    "token",
                    "secret",
                )
            )
        }
    if value is None or type(value) in (bool, int, float):
        return value
    return None


def game_data(snapshot):
    game = snapshot.get("game", {})
    return {
        "game": {k: game.get(k) for k in GAME_FIELDS},
        "references": [
            {k: r.get(k) for k in ("id", "name", "reason", "similarities")}
            for r in snapshot.get("references", [])
        ],
    }


def game_brief(snapshot):
    data = game_data(snapshot)
    brief = {
        **bounded(data),
        "context_is_bounded": True,
        "reference_count": len(data["references"]),
    }
    intent = snapshot.get("campaign_brief")
    if isinstance(intent, str) and intent.strip():
        brief["campaign_intent"] = {"text": intent[:5000], "is_verified_fact": False}
    return brief


def creator_snapshot(creator, candidate_id):
    fields = effective_fields(creator).model_dump(mode="json")
    fields = {k: fields.get(k) for k in CREATOR_FIELDS}
    works = [
        work_detail(w, creator).model_dump(mode="json")
        for w in creator.works
        if w.identity_revision == creator.identity_revision
    ]
    works = [{k: w.get(k) for k in WORK_FIELDS} for w in works]
    works.sort(
        key=lambda w: (
            bool(w.get("evidence_excerpt") and w.get("verification_notes")),
            w.get("published_at") or "",
            w["id"],
        ),
        reverse=True,
    )
    identity = {
        "platform": creator.platform,
        "account_id": creator_account_key(creator),
        "revision": creator.identity_revision,
    }
    # Fingerprint all effective work values, even if only the most useful20 fit the
    # model context. No raw acquired JSON, contacts or credentials are retained.
    fingerprint = digest(
        {
            "identity": identity,
            "revision": creator.manual_revision,
            "fields": fields,
            "analysis": bounded(creator.analysis),
            "works": works,
        }
    )
    chosen = [
        {k: (v[:2000] if isinstance(v, str) else v) for k, v in w.items()}
        for w in works[:20]
    ]
    compact = {
        k: fields.get(k)
        for k in ("name", "description", "languages", "country_code", "follower_count")
    }
    if compact.get("description"):
        compact["description"] = compact["description"][:500]
    compact["work_titles"] = [
        w.get("content_title") or w.get("work_name") for w in chosen[:3]
    ]
    snapshot = {
        "candidate_id": str(candidate_id),
        "identity": identity,
        "creator_brief": compact,
        "creator_detail": bounded(fields),
        "analysis": bounded(creator.analysis),
        "analysis_available": bool(creator.analysis),
        "works": chosen,
        "work_count": len(works),
        "context_is_bounded": True,
    }
    return snapshot, fingerprint


def evidence_rows(snapshot, brief, source):
    cited = set((brief or {}).get("cited_work_ids", []))
    rows = []
    refs = {
        str(r.get("name", "")).casefold()
        for r in source.get("references", [])
        if r.get("name")
    }
    for work in snapshot.get("works", []):
        if work["id"] not in cited:
            continue
        relation = "related_content"
        if work.get("game_id") and work["game_id"] == source.get("game", {}).get("id"):
            relation = "current_game"
        elif work.get("work_name") and work["work_name"].casefold() in refs:
            relation = "reference_game"
        rows.append(
            {
                "work_id": work["id"],
                "source_url": work.get("source_url"),
                "content_title": work.get("content_title"),
                "timestamp_seconds": work.get("timestamp_seconds"),
                "relation": relation,
                "status": (
                    "recorded_evidence"
                    if work.get("evidence_excerpt") and work.get("verification_notes")
                    else "metadata_only"
                ),
            }
        )
    return rows
