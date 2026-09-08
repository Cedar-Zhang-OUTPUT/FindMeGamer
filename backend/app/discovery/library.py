"""Transaction-local metadata import; discovery never establishes gameplay evidence.

The caller holds acquire_job_change_lock for the entire page transaction.
These functions neither commit nor perform network I/O or schedule analysis.
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.core.languages import language_key, language_keys

from app.db.models.profiles import (
    CreatorContact,
    CreatorIdentityBinding,
    CreatorProfile,
    CreatorWork,
)
from app.repositories.creator_library import (
    effective_fields,
    normalized_identity,
    safe_fields,
)
from app.schemas.creator_library import CreatorFields
from app.schemas.discovery import DiscoveredAccount, DiscoveredContent


def _time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return None


def _fresh(collected_at, previous):
    previous = _time(previous)
    return previous is None or _time(collected_at) >= previous


def import_discovered_account(
    session: Session,
    account: DiscoveredAccount,
    contents: list[DiscoveredContent],
) -> CreatorProfile | None:
    account_id, canonical = normalized_identity(
        account.platform, account.account_id, account.profile_url
    )
    identities = [CreatorProfile.platform_account_id == account_id]
    if account.platform == "youtube":
        identities.append(CreatorProfile.youtube_channel_id == account_id)
    creator = session.scalar(
        select(CreatorProfile).where(
            CreatorProfile.platform == account.platform, or_(*identities)
        )
    )
    if creator is None:
        # An explicit prior rebind or unresolved manual URL needs human resolution.
        if (
            session.scalar(
                select(CreatorIdentityBinding.creator_id)
                .where(
                    CreatorIdentityBinding.platform == account.platform,
                    or_(
                        CreatorIdentityBinding.account_id == account_id,
                        CreatorIdentityBinding.canonical_url.in_(
                            [canonical, account.profile_url]
                        ),
                    ),
                )
                .limit(1)
            )
            is not None
        ):
            return None
        if (
            session.scalar(
                select(CreatorProfile.id)
                .where(
                    CreatorProfile.platform == account.platform,
                    CreatorProfile.canonical_url.in_([canonical, account.profile_url]),
                )
                .limit(1)
            )
            is not None
        ):
            return None
        creator = CreatorProfile(
            id=uuid4(),
            platform=account.platform,
            platform_account_id=account_id,
            youtube_channel_id=account_id if account.platform == "youtube" else None,
            canonical_url=canonical,
            sort_name=(account.display_name or account_id)[:255],
            identity_revision=0,
            current_facts={},
            source_status={},
            next_analysis_at=None,
        )
        session.add(creator)
        session.flush()

    facts = dict(creator.current_facts or {})
    previous = facts.get("metadata_collected_at") or creator.last_analyzed_at
    if _fresh(account.collected_at, previous):
        public = safe_fields(
            CreatorFields,
            {
                "name": account.display_name,
                "handle": account.handle,
                "description": account.description,
                "follower_count": account.follower_count,
                "country_code": account.country,
                "avatar_url": account.avatar_url,
            },
        )
        updates = {
            "title": public.name,
            "custom_url": public.handle,
            "description": public.description,
            "subscriber_count": public.follower_count,
            "country": public.country_code,
            "location_text": account.location_text,
            "avatar_url": public.avatar_url,
        }
        # Empty public text is missing metadata, not an instruction to erase it.
        facts.update({k: v for k, v in updates.items() if v is not None and v != ""})
        facts["metadata_collected_at"] = account.collected_at.isoformat()
        if public.follower_count is not None:
            facts["follower_count_collected_at"] = account.collected_at.isoformat()
        creator.current_facts = facts
        creator.source_status = dict(creator.source_status or {}) | {
            "discovery": {
                "status": "metadata_only",
                "metadata_complete": account.metadata_complete,
                "collected_at": account.collected_at.isoformat(),
                "evidence_status": "unverified",
            }
        }
        creator.sort_name = (effective_fields(creator).name or canonical or account_id)[
            :255
        ]

    works = session.scalars(
        select(CreatorWork).where(
            CreatorWork.creator_id == creator.id,
            CreatorWork.identity_revision == creator.identity_revision,
            CreatorWork.platform == account.platform,
        )
    ).all()
    by_id = {work.source_content_id: work for work in works if work.source_content_id}
    for item in contents:
        if item.platform != account.platform or item.account_id != account.account_id:
            continue
        work = by_id.get(item.content_id)
        if work is None:
            work = CreatorWork(
                creator_id=creator.id,
                platform=account.platform,
                identity_revision=creator.identity_revision,
                source_content_id=item.content_id,
                origin="source",
                source_fields={"content_type": "unverified"},
            )
            # Language projection may already have loaded this relationship.
            # Keep same-transaction reads coherent with the newly imported work.
            creator.works.append(work)
            by_id[item.content_id] = work
        if not _fresh(item.collected_at, work.source_collected_at):
            continue
        source = dict(work.source_fields or {})
        updates = {
            "content_id": item.content_id,
            "content_title": item.title,
            "source_url": item.source_url,
            "published_at": (
                item.published_at.isoformat() if item.published_at else None
            ),
            "collected_at": item.collected_at.isoformat(),
            "language": item.language,
            "text": item.text,
        }
        source.update({k: v for k, v in updates.items() if v is not None and v != ""})
        if item.public_metrics:
            metrics = {m["name"]: m["value"] for m in source.get("metrics", [])}
            metrics.update(item.public_metrics)
            source["metrics"] = [{"name": k, "value": v} for k, v in metrics.items()]
        work.source_fields = source
        work.source_collected_at = item.collected_at
    session.flush()
    return creator


def evaluate_candidate(
    session: Session,
    creator: CreatorProfile,
    account: DiscoveredAccount,
    contents: list[DiscoveredContent],
    filters: dict,
) -> tuple[bool, dict]:
    fields = effective_fields(creator)
    languages = language_keys(fields.languages)
    if "languages" not in (creator.manual_overrides or {}):
        # ISO 639 und (undetermined) and zxx (no linguistic content) provide
        # no evidence of this account's language. Preserve the raw work metadata.
        languages.update(
            language_key(item.language)
            for item in contents
            if item.language
            and language_key(item.language) not in {"", "und", "zxx"}
            and item.platform == account.platform
            and item.account_id == account.account_id
        )
    country = fields.country_code
    followers = fields.follower_count
    has_contact = (
        session.scalar(
            select(CreatorContact.id)
            .where(
                CreatorContact.creator_id == creator.id,
                CreatorContact.identity_revision == creator.identity_revision,
                CreatorContact.is_active.is_(True),
                CreatorContact.validation_state == "valid",
            )
            .limit(1)
        )
        is not None
    )
    unknown = [
        name
        for name, missing in (
            ("country", country is None),
            ("language", not languages),
            ("followers", followers is None),
        )
        if missing
    ]
    failed = []
    countries = filters.get("countries", [])
    if countries and not (
        country in countries
        if country
        else filters.get("include_unknown_country", False)
    ):
        failed.append("country")
    requested_languages = language_keys(filters.get("languages", []))
    if requested_languages and not (
        bool(languages & requested_languages)
        if languages
        else filters.get("include_unknown_language", False)
    ):
        failed.append("language")
    ranges = filters.get("follower_ranges", [])
    if ranges:
        matches = (
            filters.get("include_unknown_followers", False)
            if followers is None
            else any(
                (r.get("minimum") is None or followers >= r["minimum"])
                and (r.get("maximum") is None or followers <= r["maximum"])
                for r in ranges
            )
        )
        if not matches:
            failed.append("followers")
    contact = filters.get("contact", "any")
    if (contact == "available" and not has_contact) or (
        contact == "missing" and has_contact
    ):
        failed.append("contact")
    return not failed, {
        "unknown_fields": unknown,
        "failed_filters": failed,
        "pending_country_labels": filters.get("pending_country_labels", []),
        "evidence_status": "unverified",
        "contact_available": has_contact,
    }
