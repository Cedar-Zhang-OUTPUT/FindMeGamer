"""One official provider page. No persistence, automatic retries or AI evidence."""

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Platform = Literal["youtube", "x", "twitch", "instagram"]


class DiscoveryCursor(BaseModel):
    token: str = Field(min_length=1, max_length=2048, repr=False)
    query_fingerprint: str


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Platform
    query: str = Field(min_length=1, max_length=512)
    page_size: int = Field(default=25, ge=1, le=100)
    search_mode: Literal["video", "channel"] = "video"
    region_hint: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    language_hint: str | None = Field(default=None, pattern=r"^[a-zA-Z-]{2,12}$")
    cursor: DiscoveryCursor | None = None
    max_requests: int = Field(default=2, ge=0, le=3)

    def fingerprint(self) -> str:
        value = self.model_dump(exclude={"cursor", "max_requests"})
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    @model_validator(mode="after")
    def validate_provider(self):
        if not self.query.strip():
            raise ValueError("A search query is required.")
        if self.platform == "youtube" and self.page_size > 50:
            raise ValueError("YouTube pages contain at most 50 search items.")
        if self.platform == "x" and self.page_size < 10:
            raise ValueError("X pages require at least 10 results.")
        if self.platform != "youtube" and (
            self.region_hint or self.language_hint or self.search_mode != "video"
        ):
            raise ValueError("These search hints are only supported by YouTube.")
        if self.cursor and self.cursor.query_fingerprint != self.fingerprint():
            raise ValueError("Continue with the original query and page settings.")
        return self


class DiscoveredAccount(BaseModel):
    platform: Platform
    account_id: str
    profile_url: str
    display_name: str | None = None
    handle: str | None = None
    description: str | None = None
    follower_count: int | None = None
    country: str | None = None
    location_text: str | None = None
    avatar_url: str | None = None
    collected_at: datetime
    metadata_complete: bool = True


class DiscoveredContent(BaseModel):
    platform: Platform
    content_id: str
    account_id: str | None = None
    source_url: str
    title: str | None = None
    text: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    language_source: (
        Literal["defaultAudioLanguage", "defaultLanguage", "tweet.lang"] | None
    ) = None
    public_metrics: dict[str, int] = Field(default_factory=dict)
    collected_at: datetime
    evidence_status: Literal["unverified"] = "unverified"


class DiscoveryIssue(BaseModel):
    code: Literal[
        "unauthorized",
        "forbidden",
        "rate_limited",
        "timeout",
        "unavailable",
        "invalid_response",
        "invalid_request",
        "partial_data",
        "budget_exhausted",
        "not_supported",
    ]
    retryable: bool = False
    retry_after_seconds: int | None = None


class DiscoveryPage(BaseModel):
    platform: Platform
    accounts: list[DiscoveredAccount] = Field(default_factory=list)
    contents: list[DiscoveredContent] = Field(default_factory=list)
    next_cursor: DiscoveryCursor | None = None
    status: Literal[
        "complete", "more", "partial", "failed", "budget_exhausted", "unavailable"
    ]
    issues: list[DiscoveryIssue] = Field(default_factory=list)
    requests_used: int = 0
    provider_items_received: int = 0
    estimated_cost: None = None
    coverage: Literal["search_index", "recent_7_days", "unavailable"]


class DiscoveryCapability(BaseModel):
    platform: Platform
    metadata_discovery_available: bool
    analysis_available: bool
    requires_connection: bool = True


def platform_capabilities() -> list[DiscoveryCapability]:
    return [
        DiscoveryCapability(
            platform=p,
            metadata_discovery_available=p in {"youtube", "x"},
            analysis_available=p in {"youtube", "x"},
        )
        for p in ("youtube", "x", "twitch", "instagram")
    ]
