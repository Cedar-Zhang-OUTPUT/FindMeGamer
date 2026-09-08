"""Pure read-query helpers for the bounded internal Library, never acquisition."""

from datetime import datetime


def descending(value):
    if value is None:
        return (True, 0)
    return (False, -(value.timestamp() if isinstance(value, datetime) else value))


def current_works(creator):
    from app.repositories.creator_library import work_detail

    return [
        work_detail(w, creator)
        for w in creator.works
        if w.identity_revision == creator.identity_revision
    ]


def creator_summary(creator):
    works = current_works(creator)
    works.sort(key=lambda w: (*descending(w.published_at), str(w.id)))
    contacts = [
        c
        for c in creator.contacts
        if c.identity_revision == creator.identity_revision and c.is_active
    ]
    return {
        "created_at": creator.created_at,
        "updated_at": max(
            [creator.updated_at]
            + [
                w.updated_at
                for w in creator.works
                if w.identity_revision == creator.identity_revision
            ]
            + [c.updated_at for c in contacts]
        ),
        "latest_published_at": next(
            (w.published_at for w in works if w.published_at), None
        ),
        "active_email_count": len(contacts),
        "contact_status": "available" if contacts else "missing",
        "recent_works": [
            dict(
                id=w.id,
                work_name=w.work_name,
                content_title=w.content_title,
                source_url=w.source_url,
                published_at=w.published_at,
                content_type=w.content_type,
            )
            for w in works[:3]
        ],
    }


def creator_sort_key(item, sort, query):
    name = (
        item.name or item.profile_url or item.source_identity.account_id or ""
    ).casefold()
    tie = (name, str(item.id))
    if sort == "followers":
        return (*descending(item.follower_count), *tie)
    if sort == "recent_publish":
        return (*descending(item.latest_published_at), *tie)
    if sort == "recent_added":
        return (*descending(item.created_at), *tie)
    if sort == "relevance" and query:
        identities = [
            str(v or "").casefold()
            for v in (item.name, item.handle, item.source_identity.account_id)
        ]
        relevance = (
            3
            if query in identities
            else 2 if any(query in v for v in identities) else 1
        )
        return (-relevance, *tie)
    return tie


def game_sort_key(item, sort):
    tie = ((item.name or item.website_url or "").casefold(), str(item.id))
    if sort == "recent_updated":
        return (*descending(item.updated_at), *tie)
    if sort == "recent_added":
        return (*descending(item.created_at), *tie)
    return tie
