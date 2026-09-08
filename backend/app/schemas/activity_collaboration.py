"""Manual relationship state is independent of delivery and generated content."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)
from app.schemas.outreach_drafts import StrictInput
from app.schemas.activity_sending import DeliveryView

FollowUpState = Literal[
    "not_followed_up", "follow_up_needed", "followed_up", "no_follow_up_needed"
]
CooperationState = Literal[
    "not_started",
    "in_discussion",
    "collaboration_confirmed",
    "in_production",
    "awaiting_publication",
    "published",
    "settled",
    "closed",
]
SendingState = Literal["not_sent", "queued", "sending", "sent", "failed", "unknown"]
InvitationState = Literal["not_invited", "awaiting_response", "accepted", "declined"]


class CollaborationUpdate(StrictInput):
    expected_revision: StrictInt = Field(ge=0)
    follow_up_state: FollowUpState | None = None
    cooperation_state: CooperationState | None = None
    notes: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def explicit_changes(self):
        fields = self.model_fields_set - {"expected_revision"}
        if not fields or any(getattr(self, name) is None for name in fields):
            raise ValueError("Provide a non-null progress or notes change.")
        return self


class ManualActivityResponse(StrictInput):
    expected_revision: StrictInt = Field(ge=0)
    outcome: Literal["accepted", "declined"]
    source_note: str = Field(min_length=1, max_length=2000)
    responded_at: AwareDatetime

    @field_validator("source_note")
    @classmethod
    def recorded_source(cls, value):
        if not value.strip():
            raise ValueError("Record the source of this response.")
        return value.strip()


class ActivityResponseView(BaseModel):
    id: UUID
    revision: int
    outcome: Literal["accepted", "declined"]
    source_note: str
    responded_at: datetime
    recorded_at: datetime


class RecipientMembership(BaseModel):
    recipient_batch_id: UUID
    recipient_snapshot_id: UUID
    input_order: int
    created_at: datetime
    snapshot: dict[str, Any]


class InvitationSendHistory(BaseModel):
    send_batch_id: UUID
    composition_id: UUID
    draft_id: UUID
    recipient_snapshot_id: UUID
    created_at: datetime
    qualification_status: Literal["eligible", "needs_repair", "excluded"]
    exclusion_reason: str | None
    delivery: DeliveryView | None


class ActivityInvitation(BaseModel):
    selection_id: UUID
    creator_id: UUID
    activity_id: UUID
    activity_name: str
    selected: bool
    identity: dict[str, Any]
    display_name: str | None
    revision: int
    sending_state: SendingState
    invitation_state: InvitationState
    follow_up_state: FollowUpState
    cooperation_state: CooperationState
    notes: str
    invited_at: datetime | None
    responses: list[ActivityResponseView]
    memberships: list[RecipientMembership]
    send_history: list[InvitationSendHistory]


class ActivityInvitationPage(BaseModel):
    items: list[ActivityInvitation]
    total: int
    limit: int
    offset: int
