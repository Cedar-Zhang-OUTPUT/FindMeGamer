"""Frozen discovery inputs; UI presets translate into inclusive range unions."""

from typing import Annotated, Literal
from uuid import UUID
from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    BeforeValidator,
    model_validator,
)

from app.schemas.discovery import DiscoveryRequest
from app.schemas.creator_library import CreatorDetail


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FollowerRange(StrictModel):
    minimum: Annotated[StrictInt, Field(ge=0)] | None = None
    maximum: Annotated[StrictInt, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("Supply at least one range bound.")
        if self.maximum is not None and (self.minimum or 0) > self.maximum:
            raise ValueError("Minimum must not exceed maximum.")
        return self


class CandidateFilters(StrictModel):
    countries: list[Annotated[str, Field(pattern=r"^[A-Z]{2}$")]] = Field(
        default_factory=list, max_length=30
    )
    languages: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=30
    )
    follower_ranges: list[FollowerRange] = Field(default_factory=list, max_length=7)
    include_unknown_country: bool = False
    include_unknown_language: bool = False
    include_unknown_followers: bool = False
    contact: Literal["any", "available", "missing"] = "any"
    pending_country_labels: list[
        Annotated[str, Field(min_length=1, max_length=100)]
    ] = Field(default_factory=list, max_length=30)


CampaignBrief = Annotated[
    StrictStr | None,
    Field(max_length=5000),
    BeforeValidator(
        lambda value: value.strip() or None if isinstance(value, str) else value
    ),
]


class CampaignBriefUpdate(StrictModel):
    campaign_brief: CampaignBrief
    expected_revision: Annotated[StrictInt, Field(ge=0)]


class ActivityCreate(StrictModel):
    game_id: UUID
    name: str = Field(min_length=1, max_length=255)
    reference_work_ids: list[UUID] = Field(default_factory=list, max_length=100)
    campaign_brief: CampaignBrief = None


class DiscoveryOptions(StrictModel):
    filters: CandidateFilters = Field(default_factory=CandidateFilters)
    batch_target: Annotated[StrictInt, Field(ge=1, le=100)] = 100
    result_limit: Annotated[StrictInt, Field(ge=1, le=600)] = 600
    batch_request_budget: Annotated[StrictInt, Field(ge=1, le=40)] = 20
    batch_scan_budget: Annotated[StrictInt, Field(ge=1, le=2000)] = 1000
    total_request_budget: Annotated[StrictInt, Field(ge=1, le=240)] = 120
    total_scan_budget: Annotated[StrictInt, Field(ge=1, le=12000)] = 6000


class QueryCreate(DiscoveryOptions):
    providers: list[DiscoveryRequest] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def sources(self):
        if len({p.platform for p in self.providers}) != len(self.providers):
            raise ValueError("Choose each platform once.")
        if any(p.cursor is not None for p in self.providers):
            raise ValueError("Provider cursors are managed by the server.")
        return self


class ContinueDiscovery(StrictModel):
    acknowledge_unknown: bool = False


class ActivityView(BaseModel):
    id: UUID
    game_id: UUID
    name: str
    source_snapshot: dict[str, Any]
    campaign_brief: CampaignBrief = None
    revision: int = 0
    initial_selection_initialized: bool = False
    created_at: datetime


class BatchView(BaseModel):
    id: UUID
    query_id: UUID
    ordinal: int
    status: str
    target_count: int
    initial_result_count: int
    requests_reserved: int
    scanned_reserved: int
    reason: str | None
    created_at: datetime


class QueryUsage(BaseModel):
    requests_used: int
    provider_items_received: int
    unknown_requests_reserved: int


class QueryView(BaseModel):
    id: UUID
    activity_id: UUID
    conditions: QueryCreate
    source_snapshot: dict[str, Any]
    status: str
    stop_requested: bool
    requires_acknowledgement: bool
    result_count: int
    requests_reserved: int
    scanned_reserved: int
    sources: dict[str, Any]
    batches: list[BatchView]
    usage: QueryUsage
    created_at: datetime


class ActivityDetail(ActivityView):
    queries: list[QueryView]


class ActivityPage(BaseModel):
    items: list[ActivityView]
    total: int
    limit: int
    offset: int


class DiscoveryAccepted(BaseModel):
    query_id: UUID
    batch_id: UUID
    status: str


class DiscoveryStopped(BaseModel):
    query_id: UUID
    status: str
    stop_requested: bool


class CandidateView(BaseModel):
    id: UUID
    creator_id: UUID
    platform: str
    account_id: str
    account: dict[str, Any]
    creator: CreatorDetail | None
    filter_notes: dict[str, Any]
    identity_revision: int
    identity_changed: bool
    selected: Literal[False] = False
    added_at: datetime
    evidence_groups: list[
        Literal["current_game", "reference_game", "related_content"]
    ] = Field(default_factory=list)
    relevance_status: Literal["not_evaluated", "available", "stale"] = "not_evaluated"


CandidateEvidence = Literal[
    "all", "current_game", "reference_game", "related_content", "none"
]
CandidateSort = Literal[
    "added", "relevance", "followers", "recent_publish", "recent_added"
]


class CandidatePage(BaseModel):
    items: list[CandidateView]
    total: int
    limit: int
    offset: int
