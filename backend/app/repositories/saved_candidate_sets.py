from sqlalchemy import select

from app.api.routes.activity import _error, _get
from app.core.idempotency import request_hash
from app.db.models.discovery import DiscoveryCandidate, DiscoveryQuery
from app.db.models.saved_candidate_set import SavedCandidateSet
from app.schemas.saved_candidate_set import SavedSetView


def metadata(item, query):
    return SavedSetView.model_validate(
        {
            "id": item.id,
            "query_id": item.query_id,
            "activity_id": query.activity_id,
            "name": item.name,
            "candidate_ids": item.candidate_ids,
            "count": len(item.candidate_ids),
            "created_at": item.created_at,
        }
    ).model_dump(mode="json")


def save(session, query_id, value):
    query = _get(session, DiscoveryQuery, query_id)
    digest = request_hash(
        method="POST",
        path=f"/api/v2/discovery/queries/{query_id}/saved-sets",
        canonical_request=value.model_dump(mode="json"),
    )
    old = session.scalar(
        select(SavedCandidateSet).where(
            SavedCandidateSet.request_id == value.request_id
        )
    )
    if old:
        if old.query_id != query_id or old.request_hash != digest:
            raise _error(
                409,
                "saved_set_request_conflict",
                "This request ID already belongs to another saved set.",
            )
        return metadata(old, query)
    actual = set(
        session.scalars(
            select(DiscoveryCandidate.id).where(
                DiscoveryCandidate.query_id == query_id,
                DiscoveryCandidate.id.in_(value.candidate_ids),
            )
        )
    )
    if actual != set(value.candidate_ids):
        raise _error(
            422,
            "saved_set_members_invalid",
            "Choose only candidates belonging to this query.",
        )
    item = SavedCandidateSet(
        query_id=query_id,
        request_id=value.request_id,
        request_hash=digest,
        name=value.name,
        candidate_ids=[str(i) for i in value.candidate_ids],
    )
    session.add(item)
    session.flush()
    return metadata(item, query)
