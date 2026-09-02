"""Read-only response previews and atomic Creator response confirmation."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hmac
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.outreach import (
    CampaignCreatorResponse,
    Delivery,
    DeliverySendState,
    OutreachCampaign,
    ResponseState,
)
from app.outreach.batches import response_token_digest


_CAPABILITY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_FINAL_STATES = frozenset({ResponseState.ACCEPTED, ResponseState.DECLINED})


@dataclass(frozen=True, slots=True)
class ResponseConfirmation:
    kind: str
    state: ResponseState | None = None
    accepted_label: str = ""
    declined_label: str = ""


def parse_response_capability(raw_token: object) -> str | None:
    """Return the capability's persistence digest only for canonical tokens."""

    if (
        not isinstance(raw_token, str)
        or _CAPABILITY_PATTERN.fullmatch(raw_token) is None
    ):
        return None
    try:
        material = base64.b64decode(raw_token + "=", altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError):
        return None
    if len(material) != 32:
        return None
    return response_token_digest(raw_token)


def _delivery_for_digest(
    session: Session, digest: str, *, lock: bool = False
) -> Delivery | None:
    statement = select(Delivery).where(Delivery.response_token_digest == digest)
    if lock:
        statement = statement.with_for_update()
    delivery = session.scalar(statement.execution_options(populate_existing=lock))
    if delivery is None or not hmac.compare_digest(
        digest, delivery.response_token_digest
    ):
        return None
    return delivery


def _final_response(
    session: Session, delivery: Delivery, *, lock: bool = False
) -> CampaignCreatorResponse | None:
    statement = select(CampaignCreatorResponse).where(
        CampaignCreatorResponse.campaign_id == delivery.campaign_id,
        CampaignCreatorResponse.creator_id == delivery.creator_id,
    )
    if lock:
        statement = statement.with_for_update()
    response = session.scalar(statement.execution_options(populate_existing=lock))
    if response is not None and response.state in _FINAL_STATES:
        return response
    return None


def _is_eligible(delivery: Delivery) -> bool:
    return (
        delivery.superseded_at is None
        and delivery.send_state is DeliverySendState.SENT
        and delivery.response_state is ResponseState.NO_RESPONSE
    )


def _view(session: Session, delivery: Delivery) -> ResponseConfirmation:
    final = _final_response(session, delivery)
    if final is not None:
        return ResponseConfirmation(kind="final", state=final.state)
    if not _is_eligible(delivery):
        return ResponseConfirmation(kind="inactive")
    return ResponseConfirmation(
        kind="confirm",
        accepted_label=delivery.accepted_label,
        declined_label=delivery.declined_label,
    )


def show_response_confirmation(session: Session, digest: str) -> ResponseConfirmation:
    delivery = _delivery_for_digest(session, digest)
    if delivery is None:
        return ResponseConfirmation(kind="not_found")
    return _view(session, delivery)


def confirm_response(
    session: Session,
    digest: str,
    choice: ResponseState,
    *,
    now: datetime | None = None,
) -> ResponseConfirmation:
    """Atomically record the first final response using campaign-first locking."""

    if choice not in _FINAL_STATES:
        raise ValueError("choice must be accepted or declined")
    located = _delivery_for_digest(session, digest)
    if located is None:
        return ResponseConfirmation(kind="not_found")
    campaign = session.scalar(
        select(OutreachCampaign)
        .where(OutreachCampaign.id == located.campaign_id)
        .with_for_update()
    )
    if campaign is None:
        return ResponseConfirmation(kind="not_found")
    delivery = session.scalar(
        select(Delivery)
        .where(Delivery.id == located.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if delivery is None or not hmac.compare_digest(
        digest, delivery.response_token_digest
    ):
        return ResponseConfirmation(kind="not_found")
    statement = (
        select(CampaignCreatorResponse)
        .where(
            CampaignCreatorResponse.campaign_id == campaign.id,
            CampaignCreatorResponse.creator_id == delivery.creator_id,
        )
        .with_for_update()
    )
    campaign_response = session.scalar(
        statement.execution_options(populate_existing=True)
    )
    if campaign_response is not None and campaign_response.state in _FINAL_STATES:
        return ResponseConfirmation(kind="final", state=campaign_response.state)
    if not _is_eligible(delivery):
        return ResponseConfirmation(kind="inactive")

    responded_at = (now or datetime.now(UTC)).astimezone(UTC)
    if campaign_response is None:
        campaign_response = CampaignCreatorResponse(
            campaign_id=campaign.id,
            creator_id=delivery.creator_id,
        )
        session.add(campaign_response)
    campaign_response.state = choice
    campaign_response.final_delivery_id = delivery.id
    campaign_response.responded_at = responded_at
    delivery.response_state = choice
    delivery.responded_at = responded_at
    session.flush()
    return ResponseConfirmation(kind="final", state=choice)


__all__ = [
    "ResponseConfirmation",
    "confirm_response",
    "parse_response_capability",
    "show_response_confirmation",
]
