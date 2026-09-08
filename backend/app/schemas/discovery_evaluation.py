from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.activity import StrictModel
from app.schemas.discovery_evaluation_output import EvaluationMatchBrief


class EvaluationCreate(StrictModel):
    candidate_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=600)

    @model_validator(mode="after")
    def unique_ids(self):
        if self.candidate_ids and len(self.candidate_ids) != len(
            set(self.candidate_ids)
        ):
            raise ValueError("Choose each candidate once.")
        return self


class EvaluationRetry(StrictModel):
    step_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=1000)


class EvaluationAccepted(BaseModel):
    evaluation_id: UUID
    status: str


class EvaluationStepView(BaseModel):
    id: UUID
    kind: str
    status: str
    error_code: str | None
    attempt: int


class EvaluationUsage(BaseModel):
    model_operations_started: int
    succeeded_steps: int
    failed_steps: int
    pending_steps: int
    running_steps: int


class EvaluationView(BaseModel):
    id: UUID
    query_id: UUID
    status: Literal["queued", "running", "completed", "partial", "failed", "no_matches"]
    stage: str
    method_version: str
    models: dict[str, str]
    conditions: dict[str, Any]
    source_snapshot: dict[str, Any]
    candidate_count: int
    matched_count: int
    retryable: bool
    usage: EvaluationUsage
    steps: list[EvaluationStepView]
    created_at: datetime


class EvaluationPage(BaseModel):
    items: list[EvaluationView]
    total: int
    limit: int
    offset: int


class KnownEvaluationEvidence(BaseModel):
    work_id: UUID
    source_url: str | None
    content_title: str | None
    timestamp_seconds: float | None
    relation: Literal["current_game", "reference_game", "related_content"]
    status: Literal["metadata_only", "recorded_evidence"]


class EvaluationResult(BaseModel):
    candidate_id: UUID
    creator_id: UUID
    platform: str
    account_id: str
    name: str | None
    status: str
    fit_group: Literal["strong_fit", "potential_fit", "limited_fit", "unranked"]
    match_brief: EvaluationMatchBrief | None
    evidence_status: Literal["unknown", "metadata_only", "recorded_evidence"]
    evidence: list[KnownEvaluationEvidence]
    needs_enrichment: bool
    stale: bool
    identity_changed: bool
    sender_watched: Literal[False] = False
    selected: Literal[False] = False


class EvaluationResultPage(BaseModel):
    items: list[EvaluationResult]
    total: int
    limit: int
    offset: int
