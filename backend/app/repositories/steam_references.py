"""Add source-backed references without undoing the operator's choices."""

from uuid import uuid4
from app.schemas.library_v2 import ReferenceWork, reference_key


def remember_reference_removals(profile, references):
    """Operator deletions/retargets apply to manual references too, before any fetch."""
    old_keys = {
        reference_key(ReferenceWork.model_validate(r))
        for r in profile.reference_works or []
    }
    new_keys = {reference_key(ReferenceWork.model_validate(r)) for r in references}
    removed = {value for kind, value in old_keys - new_keys if kind == "steam"}
    if removed:
        statuses = dict(profile.source_status or {})
        prior = dict(statuses.get("steam_recommendations") or {})
        prior["dismissed_app_ids"] = sorted(
            set(prior.get("dismissed_app_ids") or []) | removed
        )
        statuses["steam_recommendations"] = prior
        profile.source_status = statuses


def merge_steam_references(profile, recommendations):
    if recommendations.status == "not_fetched":
        return False
    statuses = dict(profile.source_status or {})
    prior = dict(statuses.get("steam_recommendations") or {})
    tracked = dict(prior.get("imported_reference_ids") or {})
    dismissed = set(prior.get("dismissed_app_ids") or [])
    references = list(profile.reference_works or [])
    current_ids = {str(r["id"]) for r in references}
    for reference_id, app_id in tracked.items():
        if reference_id not in current_ids:
            dismissed.add(app_id)
    keys = {reference_key(ReferenceWork.model_validate(r)) for r in references}
    # A manual retarget/edit keeps its original reference id; do not re-add it.
    imported_app_ids = set(tracked.values())
    changed = False
    if recommendations.status in {"available", "partial"}:
        for item in recommendations.items[:9]:
            if len(references) >= 100:
                break
            if (
                item.app_id in dismissed
                or item.app_id in imported_app_ids
                or ("steam", item.app_id) in keys
            ):
                continue
            identifier = str(uuid4())
            value = ReferenceWork(
                id=identifier,
                name=item.name,
                url=item.url,
                source="steam_more_like_this",
                source_url=recommendations.source_url,
            ).model_dump(mode="json")
            references.append(value)
            keys.add(("steam", item.app_id))
            tracked[identifier] = item.app_id
            changed = True
    profile.reference_works = references
    statuses["steam_recommendations"] = {
        **recommendations.model_dump(mode="json", exclude={"items"}),
        "imported_reference_ids": tracked,
        "dismissed_app_ids": sorted(dismissed),
    }
    profile.source_status = statuses
    return changed
