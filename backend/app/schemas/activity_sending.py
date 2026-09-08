"""Full-set qualification is separate from draft generation and final authorization."""

from typing import Any, Literal
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, StrictInt, field_validator
from app.schemas.outreach_drafts import StrictInput, SlotValues


class Exclusion(StrictInput):
    draft_id: UUID
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def filled_reason(cls, value):
        if not value.strip():
            raise ValueError("Record why this member is excluded.")
        return value.strip()


class QualificationRequest(StrictInput):
    excluded: list[Exclusion] = Field(default_factory=list, max_length=600)

    @field_validator("excluded")
    @classmethod
    def unique_members(cls, value):
        if len({member.draft_id for member in value}) != len(value):
            raise ValueError("Exclude each member once.")
        return value


class SendingIdentity(BaseModel):
    address: str | None
    name: str | None
    reply_to: str | None


class QualifiedMember(BaseModel):
    draft_id: UUID
    recipient_snapshot_id: UUID
    status: Literal["eligible", "needs_repair", "excluded"]
    missing_fields: list[str]
    exclusion_reason: str | None
    recipient_email: str | None
    subject: str
    html: str | None
    text: str | None
    values: SlotValues | None
    slot_sources: dict[str, Any]
    template_version_id: UUID
    fixed_hash: str
    revision: int
    context_token: str
    sender_facts: dict[str, Any]
    identity: dict[str, Any]
    blocking_delivery_id: UUID | None


class Qualification(BaseModel):
    composition_id: UUID
    activity_id: UUID
    qualification_token: str
    sending_account_token: str
    total_count: int
    eligible_count: int
    repair_count: int
    excluded_count: int
    sender: SendingIdentity
    members: list[QualifiedMember]
    send_ready: bool


class FinalSendRequest(QualificationRequest):
    request_id: UUID
    qualification_token: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeliveryView(BaseModel):
    id: UUID
    send_batch_id: UUID
    draft_id: UUID
    recipient_snapshot_id: UUID
    snapshot: dict[str, Any]
    state: Literal["queued", "sending", "sent", "failed", "unknown"]
    attempt: int
    retryable: bool
    error_code: str | None
    sending_at: datetime | None
    sent_at: datetime | None
    failed_at: datetime | None
    resolution: dict[str, Any]


class SendBatchView(BaseModel):
    id: UUID
    activity_id: UUID
    composition_id: UUID
    created_at: datetime
    qualification: Qualification
    deliveries: list[DeliveryView]


class SendBatchPage(BaseModel):
    items: list[SendBatchView]
    total: int
    limit: int
    offset: int


class DeliveryRetry(StrictInput):
    expected_attempt: StrictInt = Field(ge=0)


class DeliveryResolution(DeliveryRetry):
    outcome: Literal["sent", "not_sent"]
    source_note: str = Field(min_length=1, max_length=2000)

    @field_validator("source_note")
    @classmethod
    def filled_source(cls, value):
        if not value.strip():
            raise ValueError("Record how the submission outcome was verified.")
        return value.strip()
