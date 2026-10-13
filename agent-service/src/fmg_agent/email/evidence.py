"""Bounded attributed public excerpts; not provider instructions or verification."""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from urllib.parse import urlsplit

from .urls import public_url


def platform_url(value):
    try:
        host = (urlsplit(value).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(
        host == domain or host.endswith("." + domain)
        for domain in ("youtube.com", "youtu.be", "x.com", "twitter.com", "twitch.tv")
    )


class ContactEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_url: str = Field(min_length=1, max_length=4096)
    text: str = Field(max_length=8000)
    kind: str | None = Field(default=None, max_length=80)

    @field_validator("source_url")
    @classmethod
    def validate_source(cls, value):
        return public_url(value)
