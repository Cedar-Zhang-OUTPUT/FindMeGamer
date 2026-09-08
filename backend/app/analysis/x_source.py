"""Explicit recent-account coverage, never a claim of complete X history."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.discovery import DiscoveredAccount, DiscoveredContent


class XCreatorSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: DiscoveredAccount
    contents: list[DiscoveredContent] = Field(max_length=50)
    coverage: Literal["recent_account_posts"] = "recent_account_posts"
    post_limit: Literal[50] = 50
    more_available: bool = False
