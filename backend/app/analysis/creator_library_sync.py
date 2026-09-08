"""Refresh source-only Library layers within the analysis publication transaction."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.profiles import CreatorContact, CreatorProfile, CreatorWork
from app.schemas.ai_creator import EmailContactCandidate

if TYPE_CHECKING:
    from app.analysis.service import CreatorAnalysisPublication


CONTACT_FIELDS = ("email", "purpose", "source_url", "validation_state", "is_active")


def _apply_contact(contact: CreatorContact, source: dict) -> None:
    contact.source_fields = source
    effective = source | (contact.manual_overrides or {})
    for field in CONTACT_FIELDS:
        setattr(contact, field, effective[field])


def sync_creator_library(
    session: Session,
    profile: CreatorProfile,
    publication: "CreatorAnalysisPublication",
    analyzed_at: datetime,
) -> None:
    """Never promote human notes into source evidence or replace human decisions."""
    profile.platform = "youtube"
    profile.platform_account_id = publication.source.channel_id
    manual_name = (profile.manual_overrides or {}).get("name")
    if manual_name:
        profile.sort_name = manual_name[:255]
    session.flush()
    generation = profile.identity_revision

    contacts = session.scalars(
        select(CreatorContact).where(
            CreatorContact.creator_id == profile.id,
            CreatorContact.identity_revision == generation,
            CreatorContact.is_manual.is_(False),
        )
    ).all()
    by_email = {}
    for contact in contacts:
        key = (contact.source_fields.get("email") or contact.email).casefold()
        by_email.setdefault(key, contact)
    selected = publication.contacts.public_email
    seen = set()
    for position, candidate in enumerate(publication.contact_evidence.candidates):
        if not isinstance(candidate, EmailContactCandidate):
            continue
        key = candidate.value.casefold()
        if key in seen:
            continue
        seen.add(key)
        contact = by_email.get(key)
        if contact is None:
            contact = CreatorContact(
                creator_id=profile.id,
                identity_revision=generation,
                is_manual=False,
                manual_overrides={},
            )
            session.add(contact)
        contact.source_type = candidate.source_type
        contact.priority = (
            10
            if selected and selected.candidate_id == candidate.candidate_id
            else max(1, 9 - position)
        )
        _apply_contact(
            contact,
            {
                "email": candidate.value,
                "purpose": candidate.purpose,
                "source_url": candidate.source_url,
                "validation_state": (
                    "valid"
                    if candidate.validation_state == "validated"
                    else "unverified"
                ),
                "is_active": True,
            },
        )
    for contact in contacts:
        key = (contact.source_fields.get("email") or contact.email).casefold()
        if key not in seen:
            source = {field: getattr(contact, field) for field in CONTACT_FIELDS}
            source.update(contact.source_fields)
            source["is_active"] = False
            _apply_contact(contact, source)

    works = session.scalars(
        select(CreatorWork).where(
            CreatorWork.creator_id == profile.id,
            CreatorWork.identity_revision == generation,
            CreatorWork.platform == "youtube",
            CreatorWork.origin == "source",
        )
    ).all()
    by_content = {work.source_content_id: work for work in works}
    for video in publication.source.videos:
        work = by_content.get(video.id)
        if work is None:
            work = CreatorWork(
                creator_id=profile.id,
                identity_revision=generation,
                platform="youtube",
                source_content_id=video.id,
                origin="source",
            )
            session.add(work)
            by_content[video.id] = work
        work.source_collected_at = analyzed_at
        work.source_fields = {
            "content_title": video.title,
            "content_id": video.id,
            "source_url": f"https://www.youtube.com/watch?v={video.id}",
            "published_at": (
                video.published_at.isoformat() if video.published_at else None
            ),
            "collected_at": analyzed_at.isoformat(),
            "metrics": [
                {"name": name, "value": value}
                for name, value in (
                    ("views", video.view_count),
                    ("likes", video.like_count),
                    ("comments", video.comment_count),
                )
                if value is not None
            ],
            "content_type": "unverified",
            "work_name": None,
            "game_id": None,
            "verification_notes": None,
            "evidence_excerpt": None,
            "timestamp_seconds": None,
        }
