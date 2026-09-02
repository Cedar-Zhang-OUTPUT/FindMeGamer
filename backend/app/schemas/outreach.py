"""Closed immutable values used by Outreach template rendering."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_ACCEPTED_LABEL = "Yes, I'm in"
DEFAULT_DECLINED_LABEL = "No, I'm not interested"

ACCEPTED_RESPONSE_URL_PLACEHOLDER = (
    "__FIND_ME_GAMER_ACCEPTED_RESPONSE_URL_PLACEHOLDER__"
)
DECLINED_RESPONSE_URL_PLACEHOLDER = (
    "__FIND_ME_GAMER_DECLINED_RESPONSE_URL_PLACEHOLDER__"
)
RESPONSE_URL_PLACEHOLDERS = frozenset(
    {
        ACCEPTED_RESPONSE_URL_PLACEHOLDER,
        DECLINED_RESPONSE_URL_PLACEHOLDER,
    }
)


def _contains_control_character(value: str) -> bool:
    return any(
        ord(character) < 32 or 127 <= ord(character) <= 159 for character in value
    )


def _validate_label(value: str) -> str:
    if not value.strip():
        raise ValueError("CTA labels must contain visible text")
    if _contains_control_character(value):
        raise ValueError("CTA labels must be plain text without control characters")
    if any(marker in value for marker in RESPONSE_URL_PLACEHOLDERS):
        raise ValueError("CTA labels cannot contain reserved placeholder markers")
    return value


def _normalize_template_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Template names must contain visible text")
    return normalized


def _validate_template_text(value: str) -> str:
    if not value.strip():
        raise ValueError("Template content must contain visible text")
    return value


def _validate_response_url(value: str, *, placeholder: str) -> str:
    if value == placeholder:
        return value
    if any(marker in value for marker in RESPONSE_URL_PLACEHOLDERS):
        raise ValueError("response URLs cannot contain reserved placeholder markers")
    if (
        "\\" in value
        or any(character.isspace() for character in value)
        or _contains_control_character(value)
    ):
        raise ValueError(
            "response URLs cannot contain backslashes, whitespace, or control characters"
        )

    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("response URLs must use HTTP or HTTPS with a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("response URLs cannot contain credentials")
    if parsed.fragment:
        raise ValueError("response URLs cannot contain fragments")
    if parsed.hostname is None:
        raise ValueError("response URLs must contain a valid host")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("response URLs must contain a valid port") from exc
    return value


class OutreachValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        hide_input_in_errors=True,
    )


class TemplateData(OutreachValue):
    subject_template: str
    body_markdown: str
    accepted_label: str = Field(default=DEFAULT_ACCEPTED_LABEL, max_length=255)
    declined_label: str = Field(default=DEFAULT_DECLINED_LABEL, max_length=255)

    @field_validator("accepted_label", "declined_label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _validate_label(value)


class TemplateContext(OutreachValue):
    creator_name: str
    channel_name: str
    game_name: str
    steam_url: str
    game_summary: str
    match_reason: str
    sender_name: str


class ResponseURLs(OutreachValue):
    accepted_url: str
    declined_url: str

    @field_validator("accepted_url")
    @classmethod
    def validate_accepted_url(cls, value: str) -> str:
        return _validate_response_url(
            value,
            placeholder=ACCEPTED_RESPONSE_URL_PLACEHOLDER,
        )

    @field_validator("declined_url")
    @classmethod
    def validate_declined_url(cls, value: str) -> str:
        return _validate_response_url(
            value,
            placeholder=DECLINED_RESPONSE_URL_PLACEHOLDER,
        )


class RenderedDelivery(OutreachValue):
    subject: str
    markdown: str
    html: str


class OutreachTemplateCreate(OutreachValue):
    name: str = Field(max_length=255)
    subject_template: str
    body_markdown: str
    accepted_label: str = Field(default=DEFAULT_ACCEPTED_LABEL, max_length=255)
    declined_label: str = Field(default=DEFAULT_DECLINED_LABEL, max_length=255)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalize_template_name(value)

    @field_validator("subject_template", "body_markdown")
    @classmethod
    def validate_visible_text(cls, value: str) -> str:
        return _validate_template_text(value)

    @field_validator("accepted_label", "declined_label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _validate_label(value)


class OutreachTemplateUpdate(OutreachValue):
    name: str | None = Field(default=None, max_length=255)
    subject_template: str | None = None
    body_markdown: str | None = None
    accepted_label: str | None = Field(default=None, max_length=255)
    declined_label: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return _normalize_template_name(value) if value is not None else None

    @field_validator("subject_template", "body_markdown")
    @classmethod
    def validate_visible_text(cls, value: str | None) -> str | None:
        return _validate_template_text(value) if value is not None else None

    @field_validator("accepted_label", "declined_label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        return _validate_label(value) if value is not None else None

    @model_validator(mode="after")
    def require_non_null_change(self) -> "OutreachTemplateUpdate":
        if not self.model_fields_set:
            raise ValueError("PATCH must contain at least one editable field")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("PATCH fields cannot be null")
        return self


class OutreachTemplatePreviewDraft(OutreachValue):
    subject_template: str | None = None
    body_markdown: str | None = None
    accepted_label: str | None = Field(default=None, max_length=255)
    declined_label: str | None = Field(default=None, max_length=255)

    @field_validator("subject_template", "body_markdown")
    @classmethod
    def validate_visible_text(cls, value: str | None) -> str | None:
        return _validate_template_text(value) if value is not None else None

    @field_validator("accepted_label", "declined_label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        return _validate_label(value) if value is not None else None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "OutreachTemplatePreviewDraft":
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Preview draft fields cannot be null")
        return self


class OutreachTemplateResponse(OutreachValue):
    id: UUID
    name: str
    version: int = Field(gt=0)
    subject_template: str
    body_markdown: str
    accepted_label: str
    declined_label: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class OutreachTemplateList(OutreachValue):
    items: list[OutreachTemplateResponse]


__all__ = [
    "ACCEPTED_RESPONSE_URL_PLACEHOLDER",
    "DEFAULT_ACCEPTED_LABEL",
    "DEFAULT_DECLINED_LABEL",
    "DECLINED_RESPONSE_URL_PLACEHOLDER",
    "OutreachTemplateCreate",
    "OutreachTemplateList",
    "OutreachTemplatePreviewDraft",
    "OutreachTemplateResponse",
    "OutreachTemplateUpdate",
    "RESPONSE_URL_PLACEHOLDERS",
    "RenderedDelivery",
    "ResponseURLs",
    "TemplateContext",
    "TemplateData",
]
