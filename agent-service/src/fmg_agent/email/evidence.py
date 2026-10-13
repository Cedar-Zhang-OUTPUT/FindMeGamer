"""Bounded attributed public excerpts; not provider instructions or verification."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .urls import public_url


class ContactEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_url: str = Field(min_length=1, max_length=4096)
    text: str = Field(max_length=8000)
    kind: str | None = Field(default=None, max_length=80)

    @field_validator("source_url")
    @classmethod
    def validate_source(cls, value):
        return public_url(value)
