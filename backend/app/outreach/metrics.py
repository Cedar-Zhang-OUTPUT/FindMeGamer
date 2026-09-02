"""Deterministic unique-Creator Campaign metrics."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, TypeAlias


DeliveryState: TypeAlias = Literal["queued", "sending", "sent", "failed"]
ResponseState: TypeAlias = Literal["no_response", "accepted", "declined"]
CampaignState: TypeAlias = Literal[
    "not_started", "queued", "sending", "completed", "failed"
]


@dataclass(frozen=True, slots=True)
class DeliveryProjection:
    creator_id: Hashable
    send_state: DeliveryState
    response_state: ResponseState = "no_response"
    is_current: bool = True


@dataclass(frozen=True, slots=True)
class CampaignMetrics:
    sent_creators: int
    accepted: int
    declined: int
    no_response: int
    failed: int
    response_rate: Decimal


@dataclass(slots=True)
class _CreatorMetrics:
    sent: bool = False
    current_failed: bool = False
    responses: set[ResponseState] = field(default_factory=set)


def calculate_campaign_metrics(
    rows: Iterable[DeliveryProjection],
) -> CampaignMetrics:
    creators: dict[Hashable, _CreatorMetrics] = {}
    for row in rows:
        state = _enum_value(row.send_state)
        response = _enum_value(row.response_state)
        creator = creators.setdefault(row.creator_id, _CreatorMetrics())
        if state == "sent":
            creator.sent = True
        if row.is_current and state == "failed":
            creator.current_failed = True
        if response in {"accepted", "declined"}:
            creator.responses.add(response)

    sent = {creator_id for creator_id, value in creators.items() if value.sent}
    accepted = {
        creator_id
        for creator_id in sent
        if "accepted" in creators[creator_id].responses
    }
    declined = {
        creator_id
        for creator_id in sent
        if "declined" in creators[creator_id].responses
    }
    if accepted & declined:
        raise ValueError("a Creator cannot have conflicting final responses")
    failed = {
        creator_id
        for creator_id, value in creators.items()
        if value.current_failed and creator_id not in sent and not value.responses
    }
    sent_count = len(sent)
    responded_count = len(accepted) + len(declined)
    response_rate = (
        Decimal(responded_count) / Decimal(sent_count) if sent_count else Decimal("0")
    )
    return CampaignMetrics(
        sent_creators=sent_count,
        accepted=len(accepted),
        declined=len(declined),
        no_response=sent_count - responded_count,
        failed=len(failed),
        response_rate=response_rate,
    )


def derive_campaign_state(rows: Iterable[DeliveryProjection]) -> CampaignState:
    history = tuple(rows)
    if not history:
        return "not_started"
    current_states = {_enum_value(row.send_state) for row in history if row.is_current}
    if "sending" in current_states:
        return "sending"
    if "queued" in current_states:
        return "queued"
    if any(_enum_value(row.send_state) == "sent" for row in history):
        return "completed"
    if "failed" in current_states:
        return "failed"
    return "not_started"


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


__all__ = [
    "CampaignMetrics",
    "CampaignState",
    "DeliveryProjection",
    "calculate_campaign_metrics",
    "derive_campaign_state",
]
