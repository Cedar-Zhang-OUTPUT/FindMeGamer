from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, StrictInt, StrictBool, model_validator
from app.schemas.activity import StrictModel
from app.schemas.creator_library import WorkDetail, Platform
from app.schemas.discovery_evaluation import EvaluationResult


class SelectionCreate(StrictModel):
    candidate_id: UUID


class SelectionIdentity(BaseModel):
    platform: Platform
    account_id: str
    revision: int


class SelectionRevision(StrictModel):
    expected_revision: StrictInt = Field(ge=0)


class SelectionUpdate(SelectionRevision):
    context_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    contact_id: UUID | None = None
    evaluation_run_id: UUID | None = None
    work_ids: list[UUID] = Field(default_factory=list, max_length=100)
    confirm_public_name: StrictBool = False


class SelectionCancelChoice(SelectionRevision):
    selection_id: UUID


class SelectionBulkChange(StrictModel):
    add_candidate_ids: list[UUID] = Field(default_factory=list, max_length=600)
    cancel_selections: list[SelectionCancelChoice] = Field(
        default_factory=list, max_length=600
    )

    @model_validator(mode="after")
    def explicit_changes(self):
        if not self.add_candidate_ids and not self.cancel_selections:
            raise ValueError("Specify the members to add or cancel.")
        if len(set(self.add_candidate_ids)) != len(self.add_candidate_ids) or len(
            {s.selection_id for s in self.cancel_selections}
        ) != len(self.cancel_selections):
            raise ValueError("Choose each member once.")
        return self


class SelectionBulkResult(BaseModel):
    added_selection_ids: list[UUID]
    cancelled_selection_ids: list[UUID]


class PreparationContact(BaseModel):
    id: UUID
    email: str
    purpose: str | None
    source_url: str | None
    source_type: str
    source_fields: dict[str, Any]
    manual_overrides: dict[str, Any]
    validation_state: str
    identity_revision: int
    updated_at: datetime
    status: Literal["eligible", "inactive", "invalid", "historical"]


class PreparationWork(WorkDetail):
    relation: Literal["current_game", "reference_game", "related_content"]
    evidence_status: Literal["recorded_evidence", "metadata_only"]


class Preparation(BaseModel):
    id: UUID
    activity_id: UUID
    creator_id: UUID
    candidate_id: UUID
    active: bool
    revision: int
    identity: SelectionIdentity
    identity_changed: bool
    game_changed: bool
    name: str | None
    public_name: str | None
    public_name_confirmed: bool
    name_confirmed_at: datetime | None
    contact_options: list[PreparationContact]
    selected_contact: PreparationContact | None
    contact_status: Literal[
        "not_selected",
        "eligible",
        "changed",
        "inactive",
        "invalid",
        "historical",
        "missing",
    ]
    works: list[PreparationWork]
    missing_work_ids: list[UUID]
    evaluation: EvaluationResult | None
    evaluation_run_id: UUID | None
    missing_fields: list[str]
    context_token: str
    freeze_ready: bool
    send_ready: Literal[False] = False
    sender_watched: Literal[False] = False
    pending_send_requirements: list[str]


class SelectionPage(BaseModel):
    items: list[Preparation]
    total: int
    limit: int
    offset: int


class RecipientChoice(SelectionRevision):
    selection_id: UUID
    context_token: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecipientBatchCreate(StrictModel):
    request_id: UUID
    recipients: list[RecipientChoice] = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def unique_choices(self):
        if len({r.selection_id for r in self.recipients}) != len(self.recipients):
            raise ValueError("Choose each selection once.")
        return self


class FrozenRecipient(BaseModel):
    id: UUID
    selection_id: UUID
    snapshot: Preparation
    preparation: Preparation
    source_changed: bool
    current_missing_fields: list[str]


class RecipientBatchSummary(BaseModel):
    id: UUID
    activity_id: UUID
    request_id: UUID
    status: Literal["frozen"] = "frozen"
    send_ready: Literal[False] = False
    recipient_count: int
    send_ready_count: Literal[0] = 0
    needs_repair_count: int
    created_at: datetime


class RecipientBatchDetail(RecipientBatchSummary):
    source_snapshot: dict[str, Any]
    recipients: list[FrozenRecipient]


class RecipientBatchPage(BaseModel):
    items: list[RecipientBatchSummary]
    total: int
    limit: int
    offset: int
