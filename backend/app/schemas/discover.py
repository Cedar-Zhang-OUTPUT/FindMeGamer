"""Native Discover wire contract. Candidate IDs remain stable across retries."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.analysis.targets import canonicalize_target
from app.db.models.enums import TargetType

Platform = Literal["youtube", "x", "twitch", "instagram"]


class DiscoverConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platforms: list[Platform] = Field(
        default_factory=lambda: ["youtube"], min_length=1, max_length=4
    )
    content_languages: list[str] = Field(default_factory=list, max_length=30)
    min_followers: int | None = Field(default=None, ge=0, le=1_000_000_000_000)
    max_followers: int | None = Field(default=None, ge=0, le=1_000_000_000_000)
    keywords: str = Field(default="", max_length=500)

    @field_validator("platforms")
    @classmethod
    def platforms_unique(cls, value):
        return sorted(set(value))

    @field_validator("content_languages")
    @classmethod
    def languages(cls, value):
        import re

        if any(
            not re.fullmatch(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*", item)
            for item in value
        ):
            raise ValueError("Use content language codes.")
        return sorted({item.lower().replace("_", "-").split("-")[0] for item in value})

    @model_validator(mode="after")
    def bounds(self):
        if (
            self.min_followers is not None
            and self.max_followers is not None
            and self.min_followers > self.max_followers
        ):
            raise ValueError("Minimum followers cannot exceed maximum followers.")
        self.keywords = self.keywords.strip()
        return self


class ResolveGameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steam_url: str = Field(max_length=2048)

    @field_validator("steam_url")
    @classmethod
    def canonical_url(cls, value):
        return canonicalize_target(TargetType.GAME, value).canonical_url


class ResolveGameResponse(BaseModel):
    steam_app_id: str
    name: str
    canonical_url: str
    game_id: UUID | None = None


class DiscoverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game_id: UUID | None = None
    steam_url: str | None = Field(default=None, max_length=2048)
    conditions: DiscoverConditions = Field(default_factory=DiscoverConditions)

    @model_validator(mode="after")
    def game_input(self):
        if (self.game_id is None) == (self.steam_url is None):
            raise ValueError("Choose a Library game or a Steam URL.")
        if self.steam_url is not None:
            self.steam_url = canonicalize_target(
                TargetType.GAME, self.steam_url
            ).canonical_url
        return self


class DiscoverCandidateResponse(BaseModel):
    id: UUID
    platform: Platform
    platform_account_id: str
    display_name: str
    canonical_url: str
    followers: int | None = None
    content_languages: list[str] = Field(default_factory=list)
    in_library: bool = False
    profile_id: UUID | None = None


class DiscoverIssue(BaseModel):
    platform: Platform | None = None
    code: str
    message: str


class DiscoverDetail(BaseModel):
    id: UUID
    game_id: UUID | None = None
    game_name: str
    status: Literal["queued", "running", "done", "partial", "failed"]
    stage: Literal["preparing_game", "finding_creators"] | None = None
    conditions: DiscoverConditions
    candidates: list[DiscoverCandidateResponse]
    issues: list[DiscoverIssue]
    created_at: datetime
    updated_at: datetime


class DiscoverSummary(BaseModel):
    id: UUID
    game_id: UUID | None = None
    game_name: str
    status: Literal["queued", "running", "done", "partial", "failed"]
    stage: Literal["preparing_game", "finding_creators"] | None = None
    candidate_count: int
    issue_count: int
    created_at: datetime
    updated_at: datetime


class DiscoverPage(BaseModel):
    items: list[DiscoverSummary]
    next_cursor: str | None = None


class DiscoverCapability(BaseModel):
    platform: Platform
    available: bool
    reason: str | None = None


class DiscoverCapabilities(BaseModel):
    platforms: list[DiscoverCapability]
