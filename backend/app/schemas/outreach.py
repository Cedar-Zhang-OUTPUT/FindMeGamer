"""Closed immutable values used by Outreach template rendering."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from app.outreach.smtp import normalize_smtp_host


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


class SMTPSettingsUpdate(OutreachValue):
    host: str = Field(max_length=253)
    port: int = Field(default=465, ge=1, le=65_535)
    encryption: Literal["tls", "starttls", "none"] = "tls"
    username: EmailStr
    password: str | None = Field(
        default=None,
        min_length=1,
        max_length=16_384,
        json_schema_extra={"writeOnly": True},
    )
    from_name: str = Field(max_length=255)
    reply_to: EmailStr
    emails_per_minute: int = Field(default=10, ge=1, le=60)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        normalized = value.strip()
        return normalize_smtp_host(normalized)

    @field_validator("username", "reply_to", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("from_name")
    @classmethod
    def normalize_from_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or _contains_control_character(normalized):
            raise ValueError("From Name must contain safe visible text")
        return normalized

    @field_validator("password")
    @classmethod
    def normalize_password(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("SMTP password must contain visible text")
        return normalized


class SMTPSettingsResponse(OutreachValue):
    configured: bool
    host: str | None
    port: int | None
    encryption: Literal["tls", "starttls", "none"] | None
    username: str | None
    from_name: str | None
    reply_to: str | None
    emails_per_minute: int = Field(ge=1, le=60)
    last_test_status: Literal["success", "failure"] | None
    last_tested_at: datetime | None


class SMTPTestEmailRequest(OutreachValue):
    recipient: EmailStr

    @field_validator("recipient", mode="before")
    @classmethod
    def normalize_recipient(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SMTPTestResult(OutreachValue):
    succeeded: bool
    last_test_status: Literal["success", "failure"]
    last_tested_at: datetime


class OutreachSendBatchRequest(OutreachValue):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=False,
        validate_default=True,
        hide_input_in_errors=True,
    )

    match_task_id: UUID
    creator_ids: list[UUID] = Field(min_length=1, max_length=30)
    template_id: UUID | None = None
    subject_override: str | SkipJsonSchema[None] = None
    body_markdown_override: str | SkipJsonSchema[None] = None

    @field_validator("creator_ids")
    @classmethod
    def require_unique_creators(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("Creator IDs must be unique")
        return values

    @field_validator("subject_override", "body_markdown_override")
    @classmethod
    def validate_override(cls, value: str | None) -> str | None:
        return _validate_template_text(value) if value is not None else None

    @model_validator(mode="after")
    def reject_explicit_null_overrides(self) -> "OutreachSendBatchRequest":
        for field in ("subject_override", "body_markdown_override"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError("Send overrides cannot be null")
        return self


class OutreachSendBatchPreviewItem(OutreachValue):
    creator_id: UUID
    creator_name: str
    recipient_email: EmailStr
    subject: str
    markdown: str
    html: str


class OutreachSendBatchPreview(OutreachValue):
    match_task_id: UUID
    template_id: UUID
    template_name: str
    template_version: int = Field(gt=0)
    items: list[OutreachSendBatchPreviewItem]


class OutreachDeliverySummary(OutreachValue):
    id: UUID
    creator_id: UUID
    recipient_email: EmailStr
    send_state: Literal["queued"]
    response_state: Literal["no_response"]
    resends_delivery_id: UUID | None


class OutreachSendBatchResponse(OutreachValue):
    id: UUID
    campaign_id: UUID
    match_task_id: UUID
    template_id: UUID | None
    state: Literal["queued"]
    requested_creator_ids: list[UUID]
    requested_at: datetime
    deliveries: list[OutreachDeliverySummary]


class OutreachCampaignMetrics(OutreachValue):
    sent_creators: int = Field(ge=0)
    accepted: int = Field(ge=0)
    declined: int = Field(ge=0)
    no_response: int = Field(ge=0)
    failed: int = Field(ge=0)
    response_rate: float = Field(ge=0, le=1)


class OutreachCampaignGame(OutreachValue):
    id: UUID
    name: str
    steam_app_id: str
    steam_url: str
    cover_url: str | None


class OutreachCampaignSummary(OutreachValue):
    id: UUID
    match_task_id: UUID
    game: OutreachCampaignGame
    state: Literal["not_started", "queued", "sending", "completed", "failed"]
    send_batch_count: int = Field(ge=0)
    metrics: OutreachCampaignMetrics
    created_at: datetime
    latest_activity_at: datetime


class OutreachCampaignPage(OutreachValue):
    items: list[OutreachCampaignSummary]
    cursor: str | None
    has_more: bool


class OutreachCreatorIdentity(OutreachValue):
    id: UUID
    name: str
    youtube_channel_id: str
    canonical_url: str
    avatar_url: str | None


class OutreachSMTPError(OutreachValue):
    code: Literal[
        "smtp_rejected",
        "smtp_temporarily_unavailable",
        "outreach_delivery_invalid",
    ]
    message: Literal[
        "SMTP rejected the request.",
        "SMTP is temporarily unavailable.",
        "Outreach delivery could not be prepared.",
    ]
    retryable: bool


class OutreachDeliveryDetail(OutreachValue):
    id: UUID
    campaign_id: UUID
    send_batch_id: UUID
    creator: OutreachCreatorIdentity
    recipient_email: EmailStr
    rendered_subject: str
    rendered_markdown: str
    rendered_html: str
    template_name: str
    template_version: int = Field(gt=0)
    accepted_label: str
    declined_label: str
    sender_name: str
    sender_address: EmailStr
    reply_to: EmailStr
    send_state: Literal["queued", "sending", "sent", "failed"]
    response_state: Literal["no_response", "accepted", "declined"]
    resends_delivery_id: UUID | None
    superseded_by_delivery_id: UUID | None
    is_current: bool
    can_resend: bool
    smtp_error: OutreachSMTPError | None
    created_at: datetime
    sending_at: datetime | None
    sent_at: datetime | None
    failed_at: datetime | None
    responded_at: datetime | None
    superseded_at: datetime | None


class OutreachSendBatchDetail(OutreachValue):
    id: UUID
    campaign_id: UUID
    template_id: UUID | None
    template_name: str
    template_version: int = Field(gt=0)
    requested_creator_ids: list[UUID]
    requested_at: datetime
    state: Literal["queued", "sending", "sent", "partially_failed", "failed"]
    deliveries: list[OutreachDeliveryDetail]


class OutreachCampaignDetail(OutreachCampaignSummary):
    send_batches: list[OutreachSendBatchDetail]


__all__ = [
    "ACCEPTED_RESPONSE_URL_PLACEHOLDER",
    "DEFAULT_ACCEPTED_LABEL",
    "DEFAULT_DECLINED_LABEL",
    "DECLINED_RESPONSE_URL_PLACEHOLDER",
    "OutreachCampaignDetail",
    "OutreachCampaignGame",
    "OutreachCampaignMetrics",
    "OutreachCampaignPage",
    "OutreachCampaignSummary",
    "OutreachCreatorIdentity",
    "OutreachDeliveryDetail",
    "OutreachTemplateCreate",
    "OutreachTemplateList",
    "OutreachTemplatePreviewDraft",
    "OutreachTemplateResponse",
    "OutreachTemplateUpdate",
    "OutreachDeliverySummary",
    "OutreachSendBatchPreview",
    "OutreachSendBatchPreviewItem",
    "OutreachSendBatchRequest",
    "OutreachSendBatchResponse",
    "OutreachSendBatchDetail",
    "OutreachSMTPError",
    "RESPONSE_URL_PLACEHOLDERS",
    "RenderedDelivery",
    "ResponseURLs",
    "SMTPSettingsResponse",
    "SMTPSettingsUpdate",
    "SMTPTestEmailRequest",
    "SMTPTestResult",
    "TemplateContext",
    "TemplateData",
]
