"""Atomic composition and persistence of Outreach send batches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.core.errors import APIError
from app.db.models.match import MatchResultItem, MatchStatus, MatchTask
from app.db.models.outreach import (
    CampaignCreatorResponse,
    Delivery,
    DeliverySendState,
    OutreachCampaign,
    ResponseState,
    SendBatch,
    SendBatchState,
    Template,
)
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.db.models.settings import ServiceSecret, SharedSettings
from app.outreach.templates import TemplateValidationError, render_delivery
from app.repositories.outreach import template_data_from_row
from app.repositories.settings import SHARED_SETTINGS_ID, SMTP_PUBLIC_FIELDS
from app.schemas.ai_game import GameBrief
from app.schemas.match import MatchCreatorContact
from app.schemas.outreach import (
    ACCEPTED_RESPONSE_URL_PLACEHOLDER,
    DECLINED_RESPONSE_URL_PLACEHOLDER,
    OutreachDeliverySummary,
    OutreachSendBatchPreview,
    OutreachSendBatchPreviewItem,
    OutreachSendBatchRequest,
    OutreachSendBatchResponse,
    ResponseURLs,
    TemplateContext,
    TemplateData,
)


_PREVIEW_URLS = ResponseURLs(
    accepted_url="https://example.invalid/r/preview-accepted",
    declined_url="https://example.invalid/r/preview-declined",
)
_STORED_URLS = ResponseURLs(
    accepted_url=ACCEPTED_RESPONSE_URL_PLACEHOLDER,
    declined_url=DECLINED_RESPONSE_URL_PLACEHOLDER,
)


@dataclass(frozen=True, slots=True)
class _SMTPIdentity:
    sender_name: str
    sender_address: str
    reply_to: str


@dataclass(frozen=True, slots=True)
class _ComposedItem:
    creator_id: UUID
    creator_name: str
    recipient_email: str
    subject: str
    markdown: str
    html: str


@dataclass(frozen=True, slots=True)
class _Composition:
    task: MatchTask
    campaign: OutreachCampaign
    template: Template
    smtp: _SMTPIdentity
    items: tuple[_ComposedItem, ...]


def response_token_digest(raw_token: str) -> str:
    """Hash a derived response capability for persistence."""

    if not isinstance(raw_token, str) or not raw_token:
        raise ValueError("raw_token must be non-empty text")
    return hashlib.sha256(raw_token.encode("ascii")).hexdigest()


def _error(status: int, code: str, message: str) -> APIError:
    return APIError(status_code=status, code=code, message=message)


def _creator_is_stale(source_status: object) -> bool:
    def is_stale(value: object) -> bool:
        if isinstance(value, str):
            return value.casefold() == "stale"
        if isinstance(value, dict):
            return any(
                is_stale(value.get(key))
                for key in ("status", "state", "freshness")
                if key in value
            )
        return False

    if not isinstance(source_status, dict):
        return False
    direct = (
        "status",
        "state",
        "freshness",
        "youtube",
        "youtube_status",
        "youtube_state",
        "youtube_freshness",
    )
    if any(is_stale(source_status.get(key)) for key in direct if key in source_status):
        return True
    sources = source_status.get("sources")
    return isinstance(sources, dict) and is_stale(sources.get("youtube"))


def _available_contacts(
    contacts: list[CreatorContact], *, manual_only: bool
) -> list[MatchCreatorContact]:
    active = [value for value in contacts if value.is_active]
    if manual_only:
        active = [value for value in active if value.is_manual]
    validation_rank = {"verified": 3, "valid": 2, "unverified": 1, "invalid": 0}
    ordered = sorted(
        active,
        key=lambda value: (
            0 if value.is_manual else 1,
            -value.priority,
            -validation_rank.get(value.validation_state.casefold(), -1),
            value.created_at,
            str(value.id),
        ),
    )
    projected: list[MatchCreatorContact] = []
    seen: set[str] = set()
    for value in ordered:
        email_key = value.email.casefold()
        if email_key in seen:
            continue
        try:
            contact = MatchCreatorContact(
                email=value.email,
                purpose=value.purpose,
                source="manual" if value.is_manual else value.source_type,
                source_url=value.source_url,
                validation_state=value.validation_state,
            )
        except ValidationError:
            continue
        seen.add(email_key)
        projected.append(contact)
    return projected


def _smtp_identity(session: Session, *, lock: bool) -> _SMTPIdentity:
    statement = select(SharedSettings).where(SharedSettings.id == SHARED_SETTINGS_ID)
    if lock:
        statement = statement.with_for_update()
    settings = session.scalar(statement)
    stored = session.scalar(
        select(ServiceSecret).where(ServiceSecret.service == "smtp")
    )
    metadata = (
        settings.service_connection_state.get("smtp")
        if settings is not None and isinstance(settings.service_connection_state, dict)
        else None
    )
    if not isinstance(metadata, dict) or stored is None:
        raise _error(
            409, "smtp_not_configured", "Configure SMTP before creating Outreach."
        )
    public = {field: metadata.get(field) for field in SMTP_PUBLIC_FIELDS}
    required = ("host", "username", "from_name", "reply_to")
    if (
        any(
            not isinstance(public[name], str) or not public[name].strip()
            for name in required
        )
        or not isinstance(public["port"], int)
        or isinstance(public["port"], bool)
        or not 1 <= public["port"] <= 65_535
        or public["encryption"] not in {"tls", "starttls", "none"}
    ):
        raise _error(
            409, "smtp_not_configured", "Configure SMTP before creating Outreach."
        )
    return _SMTPIdentity(
        sender_name=str(public["from_name"]),
        sender_address=str(public["username"]),
        reply_to=str(public["reply_to"]),
    )


def _selected_template(
    session: Session, template_id: UUID | None, *, lock: bool
) -> Template:
    statement = select(Template)
    if template_id is None:
        statement = statement.where(Template.is_default.is_(True))
    else:
        statement = statement.where(Template.id == template_id)
    if lock:
        statement = statement.with_for_update()
    rows = list(session.scalars(statement).all())
    if len(rows) != 1:
        raise _error(404, "template_not_found", "The requested Template was not found.")
    return rows[0]


def _game_summary(task: MatchTask, game: GameProfile) -> str:
    try:
        brief = GameBrief.model_validate(task.locked_game_brief)
    except ValidationError:
        raise _error(
            409, "match_result_invalid", "The Match result is invalid."
        ) from None
    for claim in (brief.positioning_premise, brief.core_gameplay_loop):
        if claim.status == "available":
            return claim.value
    return game.sort_name


def _load_composition(
    session: Session,
    request: OutreachSendBatchRequest,
    *,
    lock: bool,
    preview: bool,
) -> _Composition:
    task_statement = select(MatchTask).where(MatchTask.id == request.match_task_id)
    if lock:
        task_statement = task_statement.with_for_update()
    task = session.scalar(task_statement)
    if task is None:
        raise _error(404, "match_not_found", "The Match was not found.")
    if task.status is not MatchStatus.SUCCEEDED:
        raise _error(409, "match_not_succeeded", "The Match is not ready for Outreach.")

    campaign_statement = select(OutreachCampaign).where(
        OutreachCampaign.match_task_id == task.id
    )
    if lock:
        campaign_statement = campaign_statement.with_for_update()
    campaigns = list(session.scalars(campaign_statement).all())
    if len(campaigns) != 1:
        raise _error(
            409, "outreach_campaign_invalid", "The Outreach Campaign is invalid."
        )
    campaign = campaigns[0]
    smtp = _smtp_identity(session, lock=lock)
    template = _selected_template(session, request.template_id, lock=lock)

    result_statement = (
        select(MatchResultItem)
        .where(
            MatchResultItem.match_task_id == task.id,
            MatchResultItem.creator_id.in_(request.creator_ids),
        )
        .order_by(MatchResultItem.creator_id)
    )
    if lock:
        result_statement = result_statement.with_for_update()
    results = {row.creator_id: row for row in session.scalars(result_statement).all()}
    if set(results) != set(request.creator_ids):
        raise _error(
            422,
            "creator_not_in_match",
            "Every Creator must belong to the Match result.",
        )

    creator_statement = (
        select(CreatorProfile)
        .where(CreatorProfile.id.in_(request.creator_ids))
        .order_by(CreatorProfile.id)
    )
    if lock:
        creator_statement = creator_statement.with_for_update()
    creators = {row.id: row for row in session.scalars(creator_statement).all()}
    contact_statement = (
        select(CreatorContact)
        .where(CreatorContact.creator_id.in_(request.creator_ids))
        .order_by(CreatorContact.creator_id, CreatorContact.id)
    )
    if lock:
        contact_statement = contact_statement.with_for_update()
    contacts: dict[UUID, list[CreatorContact]] = {
        value: [] for value in request.creator_ids
    }
    for row in session.scalars(contact_statement).all():
        contacts[row.creator_id].append(row)

    selections = {
        selection.creator_id: str(selection.email)
        for selection in request.recipient_selections
    }
    if not set(selections).issubset(request.creator_ids):
        raise _error(
            422,
            "recipient_email_selection_invalid",
            "Every recipient selection must belong to a requested Creator.",
        )

    game = session.get(GameProfile, task.game_id)
    if game is None:
        raise _error(409, "match_result_invalid", "The Match result is invalid.")
    game_summary = _game_summary(task, game)
    try:
        base_template = template_data_from_row(template).model_dump()
        if request.subject_override is not None:
            base_template["subject_template"] = request.subject_override
        if request.body_markdown_override is not None:
            base_template["body_markdown"] = request.body_markdown_override
        template_data = TemplateData(**base_template)
    except ValidationError:
        raise _error(
            422, "template_invalid", "The Template content is invalid."
        ) from None
    response_urls = _PREVIEW_URLS if preview else _STORED_URLS
    composed: list[_ComposedItem] = []
    for creator_id in request.creator_ids:
        creator = creators.get(creator_id)
        if creator is None:
            raise _error(
                422,
                "creator_not_in_match",
                "Every Creator must belong to the Match result.",
            )
        available = _available_contacts(
            contacts[creator_id], manual_only=_creator_is_stale(creator.source_status)
        )
        if not available:
            raise _error(
                422,
                "recipient_email_unavailable",
                "Every Creator must have an active email address.",
            )
        requested_email = selections.get(creator_id)
        if requested_email is None and len(available) > 1:
            raise _error(
                422,
                "recipient_email_selection_required",
                "Select exactly one active email for every Creator with multiple emails.",
            )
        selected = available[0]
        if requested_email is not None:
            selected = next(
                (
                    contact
                    for contact in available
                    if str(contact.email).casefold() == requested_email.casefold()
                ),
                None,
            )
            if selected is None:
                raise _error(
                    422,
                    "recipient_email_selection_invalid",
                    "The selected email is not active for this Creator.",
                )
        current = (
            creator.current_facts if isinstance(creator.current_facts, dict) else {}
        )
        channel_name = current.get("title")
        if not isinstance(channel_name, str) or not channel_name:
            channel_name = creator.sort_name
        reasons = results[creator_id].match_reasons
        if (
            not isinstance(reasons, list)
            or not reasons
            or any(not isinstance(value, str) or not value.strip() for value in reasons)
        ):
            raise _error(409, "match_result_invalid", "The Match result is invalid.")
        context = TemplateContext(
            creator_name=creator.sort_name,
            channel_name=channel_name,
            game_name=game.sort_name,
            steam_url=game.canonical_url,
            game_summary=game_summary,
            match_reason=" ".join(reasons),
            sender_name=smtp.sender_name,
        )
        try:
            rendered = render_delivery(template_data, context, response_urls)
        except (TemplateValidationError, ValidationError):
            raise _error(
                422, "template_invalid", "The Template content is invalid."
            ) from None
        composed.append(
            _ComposedItem(
                creator_id=creator.id,
                creator_name=creator.sort_name,
                recipient_email=str(selected.email),
                subject=rendered.subject,
                markdown=rendered.markdown,
                html=rendered.html,
            )
        )
    return _Composition(task, campaign, template, smtp, tuple(composed))


def preview_send_batch(
    session: Session, request: OutreachSendBatchRequest
) -> OutreachSendBatchPreview:
    composition = _load_composition(session, request, lock=False, preview=True)
    return OutreachSendBatchPreview(
        match_task_id=composition.task.id,
        template_id=composition.template.id,
        template_name=composition.template.name,
        template_version=composition.template.version,
        items=[
            OutreachSendBatchPreviewItem(
                creator_id=item.creator_id,
                creator_name=item.creator_name,
                recipient_email=item.recipient_email,
                subject=item.subject,
                markdown=item.markdown,
                html=item.html,
            )
            for item in composition.items
        ],
    )


def _project_batch(
    batch: SendBatch, match_task_id: UUID, deliveries: list[Delivery]
) -> OutreachSendBatchResponse:
    return OutreachSendBatchResponse(
        id=batch.id,
        campaign_id=batch.campaign_id,
        match_task_id=match_task_id,
        template_id=batch.template_id,
        state="queued",
        requested_creator_ids=[UUID(value) for value in batch.requested_creator_ids],
        requested_at=batch.requested_at,
        deliveries=[
            OutreachDeliverySummary(
                id=row.id,
                creator_id=row.creator_id,
                recipient_email=row.recipient_email,
                send_state="queued",
                response_state="no_response",
                resends_delivery_id=row.resends_delivery_id,
            )
            for row in deliveries
        ],
    )


def create_send_batch(
    session: Session,
    request: OutreachSendBatchRequest,
    *,
    secret_cipher: SecretCipher,
) -> OutreachSendBatchResponse:
    composition = _load_composition(session, request, lock=True, preview=False)
    prior = session.scalar(
        select(Delivery.id)
        .where(
            Delivery.campaign_id == composition.campaign.id,
            Delivery.creator_id.in_(request.creator_ids),
        )
        .limit(1)
    )
    confirmed = session.scalar(
        select(CampaignCreatorResponse.id)
        .where(
            CampaignCreatorResponse.campaign_id == composition.campaign.id,
            CampaignCreatorResponse.creator_id.in_(request.creator_ids),
            CampaignCreatorResponse.state.in_(
                (ResponseState.ACCEPTED, ResponseState.DECLINED)
            ),
        )
        .limit(1)
    )
    if prior is not None or confirmed is not None:
        raise _error(
            409,
            "explicit_resend_required",
            "Use the explicit Resend action for a prior Delivery.",
        )

    batch = SendBatch(
        campaign_id=composition.campaign.id,
        template_id=composition.template.id,
        requested_creator_ids=[str(value) for value in request.creator_ids],
        state=SendBatchState.QUEUED,
    )
    session.add(batch)
    session.flush()
    deliveries: list[Delivery] = []
    for item in composition.items:
        delivery_id = uuid4()
        raw_token = secret_cipher.derive_outreach_response_token(delivery_id)
        delivery = Delivery(
            id=delivery_id,
            campaign_id=composition.campaign.id,
            send_batch_id=batch.id,
            creator_id=item.creator_id,
            recipient_email=item.recipient_email,
            rendered_subject=item.subject,
            rendered_markdown=item.markdown,
            rendered_html=item.html,
            template_name=composition.template.name,
            template_version=composition.template.version,
            accepted_label=composition.template.accepted_label,
            declined_label=composition.template.declined_label,
            sender_name=composition.smtp.sender_name,
            sender_address=composition.smtp.sender_address,
            reply_to=composition.smtp.reply_to,
            send_state=DeliverySendState.QUEUED,
            response_state=ResponseState.NO_RESPONSE,
            response_token_digest=response_token_digest(raw_token),
        )
        del raw_token
        session.add(delivery)
        deliveries.append(delivery)
    session.flush()
    return _project_batch(batch, composition.task.id, deliveries)


def resend_delivery(
    session: Session,
    delivery_id: UUID,
    *,
    secret_cipher: SecretCipher,
    now: datetime | None = None,
) -> OutreachSendBatchResponse:
    located = session.get(Delivery, delivery_id)
    if located is None:
        raise _error(404, "delivery_not_found", "The Delivery was not found.")
    campaign = session.scalar(
        select(OutreachCampaign)
        .where(OutreachCampaign.id == located.campaign_id)
        .with_for_update()
    )
    if campaign is None:
        raise _error(404, "delivery_not_found", "The Delivery was not found.")
    delivery = session.scalar(
        select(Delivery)
        .where(Delivery.id == delivery_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    response = session.scalar(
        select(CampaignCreatorResponse).where(
            CampaignCreatorResponse.campaign_id == campaign.id,
            CampaignCreatorResponse.creator_id == located.creator_id,
        )
    )
    allowed_send_state = delivery is not None and delivery.send_state in {
        DeliverySendState.SENT,
        DeliverySendState.FAILED,
    }
    if (
        delivery is None
        or delivery.superseded_at is not None
        or not allowed_send_state
        or delivery.response_state is not ResponseState.NO_RESPONSE
        or (response is not None and response.state is not ResponseState.NO_RESPONSE)
    ):
        raise _error(409, "delivery_not_resendable", "The Delivery cannot be resent.")

    source_batch = session.get(SendBatch, delivery.send_batch_id)
    task = session.get(MatchTask, campaign.match_task_id)
    if source_batch is None or task is None:
        raise _error(
            409, "outreach_campaign_invalid", "The Outreach Campaign is invalid."
        )
    replacement_batch = SendBatch(
        campaign_id=campaign.id,
        template_id=source_batch.template_id,
        requested_creator_ids=[str(delivery.creator_id)],
        state=SendBatchState.QUEUED,
    )
    session.add(replacement_batch)
    session.flush()
    replacement_id = uuid4()
    raw_token = secret_cipher.derive_outreach_response_token(replacement_id)
    replacement = Delivery(
        id=replacement_id,
        campaign_id=delivery.campaign_id,
        send_batch_id=replacement_batch.id,
        creator_id=delivery.creator_id,
        resends_delivery_id=delivery.id,
        recipient_email=delivery.recipient_email,
        rendered_subject=delivery.rendered_subject,
        rendered_markdown=delivery.rendered_markdown,
        rendered_html=delivery.rendered_html,
        template_name=delivery.template_name,
        template_version=delivery.template_version,
        accepted_label=delivery.accepted_label,
        declined_label=delivery.declined_label,
        sender_name=delivery.sender_name,
        sender_address=delivery.sender_address,
        reply_to=delivery.reply_to,
        send_state=DeliverySendState.QUEUED,
        response_state=ResponseState.NO_RESPONSE,
        response_token_digest=response_token_digest(raw_token),
    )
    del raw_token
    delivery.superseded_at = (now or datetime.now(UTC)).astimezone(UTC)
    session.flush()
    session.add(replacement)
    session.flush()
    return _project_batch(replacement_batch, task.id, [replacement])


__all__ = [
    "create_send_batch",
    "preview_send_batch",
    "resend_delivery",
    "response_token_digest",
]
