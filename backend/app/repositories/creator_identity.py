"""Explicit identity correction, under the caller's job-change/profile lock."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.db.models.enums import JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.outreach import Delivery, DeliverySendState
from app.db.models.activity_sending import ActivityDelivery
from app.db.models.profiles import (
    CreatorContact,
    CreatorIdentityBinding,
    CreatorProfile,
)


def rebind_creator(
    session: Session,
    creator: CreatorProfile,
    *,
    platform: str,
    account_id: str | None,
    canonical_url: str,
    now: datetime,
) -> CreatorProfile:
    """Caller validates confirmation, revision, syntax and identity uniqueness.

    A binding is only a small identity audit, never a historical Profile copy.
    Old contacts/works remain attached to their original identity generation.
    """
    old_account = creator.platform_account_id or (
        creator.youtube_channel_id if creator.platform == "youtube" else None
    )
    if (creator.platform, old_account, creator.canonical_url) == (
        platform,
        account_id,
        canonical_url,
    ):
        return creator
    youtube_ids = set()
    if creator.platform == "youtube" and old_account:
        youtube_ids.add(old_account)
    if platform == "youtube" and account_id:
        youtube_ids.add(account_id)
    if creator.platform == "x" and old_account:
        youtube_ids.add(f"x:{old_account}")
    if platform == "x" and account_id:
        youtube_ids.add(f"x:{account_id}")
    if (
        youtube_ids
        and session.scalar(
            select(AnalysisJob.id)
            .where(
                AnalysisJob.target_type == TargetType.CREATOR,
                AnalysisJob.canonical_target_id.in_(youtube_ids),
                AnalysisJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
            .limit(1)
        )
        is not None
    ):
        raise APIError(
            status_code=409,
            code="creator_analysis_in_progress",
            message="Wait for the active Creator analysis before changing identity.",
        )
    if (
        session.scalar(
            select(Delivery.id)
            .where(
                Delivery.creator_id == creator.id,
                Delivery.send_state.in_(
                    [DeliverySendState.QUEUED, DeliverySendState.SENDING]
                ),
            )
            .limit(1)
        )
        is not None
        or session.scalar(
            select(ActivityDelivery.id)
            .where(
                ActivityDelivery.state.in_(["queued", "sending"]),
                ActivityDelivery.snapshot["identity"]["platform"].astext
                == creator.platform,
                ActivityDelivery.snapshot["identity"]["account_id"].astext
                == old_account,
            )
            .limit(1)
        )
        is not None
    ):
        raise APIError(
            status_code=409,
            code="creator_delivery_in_progress",
            message="Wait for pending deliveries before changing Creator identity.",
        )
    session.add(
        CreatorIdentityBinding(
            creator_id=creator.id,
            revision=creator.identity_revision,
            platform=creator.platform,
            account_id=old_account,
            canonical_url=creator.canonical_url,
            changed_at=now,
        )
    )
    for contact in session.scalars(
        select(CreatorContact).where(CreatorContact.creator_id == creator.id)
    ):
        contact.is_active = False
    creator.identity_revision += 1
    creator.manual_revision += 1
    creator.identity_changed_at = now
    creator.platform = platform
    creator.platform_account_id = account_id
    creator.youtube_channel_id = account_id if platform == "youtube" else None
    creator.canonical_url = canonical_url
    for field in (
        "current_facts",
        "analysis",
        "brief",
        "source_status",
        "model_metadata",
        "prompt_metadata",
    ):
        setattr(creator, field, {})
    creator.last_analyzed_at = None
    creator.next_analysis_at = None
    creator.sort_name = str(
        creator.manual_overrides.get("name")
        or account_id
        or canonical_url
        or creator.id
    )[:255]
    session.flush()
    return creator
