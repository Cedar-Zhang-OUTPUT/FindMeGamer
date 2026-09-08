"""Authenticated Outreach Template and SMTP configuration API."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from datetime import UTC, datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
import hashlib
import hmac
import json
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.crypto import EncryptedValue, SecretCipher
from app.core.errors import APIError
from app.core.idempotency import (
    IDEMPOTENCY_RETENTION,
    InvalidIdempotencyKey,
    request_hash,
    utc_now,
    validate_idempotency_key,
)
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.outreach import (
    CampaignCreatorResponse,
    Delivery,
    DeliverySendState,
    OutreachCampaign,
    ResponseState,
    SendBatch,
    Template,
)
from app.db.models.profiles import CreatorProfile, GameProfile
from app.db.models.settings import ServiceSecret
from app.outreach.batches import (
    create_send_batch,
    preview_send_batch,
    resend_delivery,
)
from app.outreach.metrics import (
    CampaignMetrics,
    DeliveryProjection,
    calculate_campaign_metrics,
    derive_campaign_state,
)
from app.outreach.rate_limit import SMTPRateLimitError, SMTPRateLimiter
from app.outreach.smtp import SMTPConfig, SMTPError, SMTPGateway
from app.outreach.templates import TemplateValidationError, render_delivery
from app.repositories.outreach import (
    DefaultTemplateDeleteError,
    LastTemplateError,
    OutreachRepository,
    TemplateNameConflictError,
    template_data_from_row,
)
from app.repositories.settings import (
    SHARED_SETTINGS_ID,
    SMTP_PUBLIC_FIELDS,
    SettingsRepository,
)
from app.schemas.outreach import (
    OutreachCampaignDetail,
    OutreachCampaignGame,
    OutreachCampaignMetrics,
    OutreachCampaignPage,
    OutreachCampaignSummary,
    OutreachCreatorIdentity,
    OutreachDeliveryDetail,
    OutreachSendBatchDetail,
    OutreachSMTPError,
    OutreachTemplateCreate,
    OutreachTemplateList,
    OutreachTemplatePreviewDraft,
    OutreachTemplateResponse,
    OutreachTemplateUpdate,
    OutreachSendBatchPreview,
    OutreachSendBatchRequest,
    OutreachSendBatchResponse,
    RenderedDelivery,
    ResponseURLs,
    SMTPSettingsResponse,
    SMTPSettingsUpdate,
    SMTPTestEmailRequest,
    SMTPTestResult,
    TemplateContext,
    TemplateData,
)


_PREVIEW_CONTEXT = TemplateContext(
    creator_name="Sample Creator",
    channel_name="Sample Channel",
    game_name="Sample Game",
    steam_url="https://store.steampowered.com/app/000000",
    game_summary="Sample Game is a short cooperative adventure.",
    match_reason="This creator is a strong sample match for the game.",
    sender_name="Sample Sender",
)
_PREVIEW_URLS = ResponseURLs(
    accepted_url="https://example.invalid/r/preview-accepted",
    declined_url="https://example.invalid/r/preview-declined",
)
_CURSOR_LIMIT = 2048
_SAFE_SMTP_ERRORS = frozenset(
    {
        (
            "smtp_outcome_unknown",
            "SMTP submission outcome is unknown. Verify before sending again.",
            False,
        ),
        ("smtp_rejected", "SMTP rejected the request.", False),
        ("smtp_temporarily_unavailable", "SMTP is temporarily unavailable.", True),
        (
            "outreach_delivery_invalid",
            "Outreach delivery could not be prepared.",
            False,
        ),
    }
)


class OutreachBatchDispatcher(Protocol):
    def dispatch(self, send_batch_id: UUID) -> int: ...


class CeleryOutreachBatchDispatcher:
    def dispatch(self, send_batch_id: UUID) -> int:
        from app.workers.outreach_tasks import enqueue_send_batch

        return enqueue_send_batch(send_batch_id)


def _idempotency_key(raw: str | None) -> str:
    try:
        return validate_idempotency_key(raw)
    except InvalidIdempotencyKey:
        raise APIError(
            status_code=400,
            code="idempotency_key_invalid",
            message="A valid Idempotency-Key is required.",
        ) from None


def _idempotency_conflict() -> APIError:
    return APIError(
        status_code=409,
        code="idempotency_key_conflict",
        message="The Idempotency-Key was already used for another request.",
    )


def _lock_idempotency_key(session: Session, key: str) -> None:
    session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0x464D474F)))
    )


def _idempotent_replay(
    session: Session, *, key: str, digest: str, now: datetime
) -> dict[str, object] | None:
    record = session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.key == key).with_for_update()
    )
    if record is None:
        return None
    if record.expires_at is not None and record.expires_at <= now:
        session.delete(record)
        session.flush()
        return None
    if record.request_hash != digest:
        raise _idempotency_conflict()
    try:
        return OutreachSendBatchResponse.model_validate_json(
            json.dumps(record.response_body)
        ).model_dump(mode="json")
    except ValidationError:
        raise APIError(
            status_code=500,
            code="outreach_state_invalid",
            message="The Outreach state is invalid.",
        ) from None


def _store_batch_idempotency(
    session: Session,
    *,
    key: str,
    digest: str,
    path: str,
    body: dict[str, object],
    now: datetime,
) -> None:
    session.add(
        IdempotencyRecord(
            key=key,
            request_hash=digest,
            method="POST",
            path=path,
            response_status=201,
            response_body=body,
            expires_at=now + IDEMPOTENCY_RETENTION,
        )
    )
    session.flush()


def _stable_json_response(body: dict[str, object]) -> Response:
    return Response(
        content=json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        status_code=201,
        media_type="application/json",
    )


def _dispatch_committed_batch(
    body: dict[str, object], dispatcher: OutreachBatchDispatcher
) -> Response:
    try:
        send_batch_id = UUID(str(body["id"]))
        if str(send_batch_id) != body["id"] or send_batch_id.int == 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise APIError(
            status_code=500,
            code="outreach_state_invalid",
            message="The Outreach state is invalid.",
        ) from None
    try:
        dispatcher.dispatch(send_batch_id)
    except Exception:
        raise APIError(
            status_code=503,
            code="outreach_queue_unavailable",
            message="Outreach could not be queued. Please retry.",
            retryable=True,
        ) from None
    return _stable_json_response(body)


def _not_found() -> APIError:
    return APIError(
        status_code=404,
        code="template_not_found",
        message="The requested Template was not found.",
    )


def _invalid_template() -> APIError:
    return APIError(
        status_code=422,
        code="template_invalid",
        message="The Template content is invalid.",
    )


def _name_conflict() -> APIError:
    return APIError(
        status_code=409,
        code="template_name_conflict",
        message="A Template with that name already exists.",
    )


def _constraint_conflict() -> APIError:
    return APIError(
        status_code=409,
        code="template_conflict",
        message="The Template changed while the request was being completed.",
    )


def _project_template(row: Template) -> OutreachTemplateResponse:
    return OutreachTemplateResponse(
        id=row.id,
        name=row.name,
        version=row.version,
        subject_template=row.subject_template,
        body_markdown=row.body_markdown,
        accepted_label=row.accepted_label,
        declined_label=row.declined_label,
        is_default=row.is_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_renderable(template: TemplateData) -> RenderedDelivery:
    try:
        return render_delivery(template, _PREVIEW_CONTEXT, _PREVIEW_URLS)
    except (TemplateValidationError, ValidationError):
        raise _invalid_template() from None


def _template_data(values: dict[str, str]) -> TemplateData:
    try:
        return TemplateData(
            subject_template=values["subject_template"],
            body_markdown=values["body_markdown"],
            accepted_label=values["accepted_label"],
            declined_label=values["declined_label"],
        )
    except ValidationError:
        raise _invalid_template() from None


def _rollback_and_raise(database_session: Session, error: APIError) -> None:
    database_session.rollback()
    raise error


def _smtp_not_configured() -> APIError:
    return APIError(
        status_code=409,
        code="smtp_not_configured",
        message="Configure SMTP before testing it.",
    )


def _smtp_configuration_changed() -> APIError:
    return APIError(
        status_code=409,
        code="smtp_configuration_changed",
        message="The SMTP configuration changed while it was being tested.",
        retryable=True,
    )


def _public_smtp_metadata(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    public = {field: value.get(field) for field in SMTP_PUBLIC_FIELDS}
    required_strings = ("host", "username", "from_name", "reply_to")
    if (
        any(
            not isinstance(public[field], str) or not public[field].strip()
            for field in required_strings
        )
        or not isinstance(public["port"], int)
        or isinstance(public["port"], bool)
        or not 1 <= public["port"] <= 65_535
        or public["encryption"] not in {"tls", "starttls", "none"}
    ):
        return None
    return public


def _test_status(stored: ServiceSecret | None) -> tuple[str | None, datetime | None]:
    if stored is None or stored.last_test_succeeded is None:
        return None, None
    return (
        "success" if stored.last_test_succeeded else "failure",
        stored.last_test_at,
    )


def _smtp_response(settings, stored: ServiceSecret | None) -> SMTPSettingsResponse:
    metadata = _public_smtp_metadata(settings.service_connection_state.get("smtp"))
    configured = metadata is not None and stored is not None
    status, tested_at = _test_status(stored)
    return SMTPSettingsResponse(
        configured=configured,
        host=metadata["host"] if configured else None,
        port=metadata["port"] if configured else None,
        encryption=metadata["encryption"] if configured else None,
        username=metadata["username"] if configured else None,
        from_name=metadata["from_name"] if configured else None,
        reply_to=metadata["reply_to"] if configured else None,
        emails_per_minute=settings.smtp_rate_per_minute,
        last_test_status=status if configured else None,
        last_tested_at=tested_at if configured else None,
    )


def _load_smtp_config(
    database_session: Session,
    secret_cipher: SecretCipher,
) -> tuple[SMTPConfig, EncryptedValue, dict[str, object], int]:
    repository = SettingsRepository(database_session)
    settings = repository.get_smtp_settings()
    stored = repository.get_connection("smtp")
    public = _public_smtp_metadata(settings.service_connection_state.get("smtp"))
    if stored is None or public is None:
        raise _smtp_not_configured()
    encrypted = EncryptedValue(
        ciphertext=bytes(stored.ciphertext), nonce=bytes(stored.nonce)
    )
    rate = settings.smtp_rate_per_minute
    database_session.commit()
    try:
        password = secret_cipher.decrypt(encrypted)
    except Exception:
        raise APIError(
            status_code=500,
            code="internal_error",
            message="The request could not be completed.",
            retryable=True,
        ) from None
    return (
        SMTPConfig(
            host=str(public["host"]),
            port=int(public["port"]),
            encryption=public["encryption"],
            username=str(public["username"]),
            password=password,
            from_name=str(public["from_name"]),
            reply_to=str(public["reply_to"]),
        ),
        encrypted,
        public,
        rate,
    )


def _record_smtp_result(
    database_session: Session,
    *,
    encrypted: EncryptedValue,
    public: dict[str, object],
    succeeded: bool,
) -> SMTPTestResult:
    tested_at = datetime.now(timezone.utc)
    stored = SettingsRepository(database_session).record_smtp_test(
        expected_secret=encrypted,
        expected_public_metadata=public,
        succeeded=succeeded,
        tested_at=tested_at,
    )
    if stored is None:
        database_session.rollback()
        raise _smtp_configuration_changed()
    database_session.commit()
    return SMTPTestResult(
        succeeded=succeeded,
        last_test_status="success" if succeeded else "failure",
        last_tested_at=tested_at,
    )


def _redact_config(config: SMTPConfig) -> SMTPConfig:
    return SMTPConfig(
        host=config.host,
        port=config.port,
        encryption=config.encryption,
        username=config.username,
        password="",
        from_name=config.from_name,
        reply_to=config.reply_to,
    )


def _cursor_timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _cursor_signature(payload: dict[str, object], key: bytes) -> str:
    return hmac.new(
        key,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()


def _encode_campaign_cursor(value: tuple[datetime, UUID], key: bytes) -> str:
    signed: dict[str, object] = {
        "v": 1,
        "key": [_cursor_timestamp(value[0]), str(value[1])],
        "scope": "outreach-campaigns",
    }
    payload = {**signed, "signature": _cursor_signature(signed, key)}
    return (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


def _invalid_campaign_cursor() -> APIError:
    return APIError(
        status_code=400,
        code="outreach_campaign_cursor_invalid",
        message="The Outreach Campaign cursor is invalid.",
    )


def _decode_campaign_cursor(
    raw: str | None, key: bytes
) -> tuple[datetime, UUID] | None:
    if raw is None:
        return None
    if not raw or len(raw) > _CURSOR_LIMIT:
        raise _invalid_campaign_cursor()
    try:
        decoded = base64.b64decode(
            raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True
        )
        if base64.urlsafe_b64encode(decoded).decode().rstrip("=") != raw:
            raise ValueError
        value = json.loads(decoded)
        if (
            not isinstance(value, dict)
            or set(value) != {"v", "key", "scope", "signature"}
            or value["v"] != 1
            or value["scope"] != "outreach-campaigns"
            or not isinstance(value["key"], list)
            or len(value["key"]) != 2
        ):
            raise ValueError
        signed = {"v": value["v"], "key": value["key"], "scope": value["scope"]}
        signature = value["signature"]
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, _cursor_signature(signed, key)
        ):
            raise ValueError
        timestamp_text, id_text = value["key"]
        if (
            not isinstance(timestamp_text, str)
            or not timestamp_text.endswith("Z")
            or not isinstance(id_text, str)
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(timestamp_text[:-1] + "+00:00")
        campaign_id = UUID(id_text)
        if (
            _cursor_timestamp(timestamp) != timestamp_text
            or str(campaign_id) != id_text
        ):
            raise ValueError
        return timestamp, campaign_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        raise _invalid_campaign_cursor() from None


def _game_identity(game: GameProfile) -> OutreachCampaignGame:
    facts = game.current_facts if isinstance(game.current_facts, dict) else {}
    cover = next(
        (
            value
            for name in (
                "cover_image_url",
                "cover_url",
                "header_image",
                "header_image_url",
                "image_url",
            )
            if isinstance((value := facts.get(name)), str) and value
        ),
        None,
    )
    return OutreachCampaignGame(
        id=game.id,
        name=game.sort_name,
        steam_app_id=game.steam_app_id,
        steam_url=game.canonical_url,
        cover_url=cover,
    )


def _creator_identity(creator: CreatorProfile) -> OutreachCreatorIdentity:
    facts = creator.current_facts if isinstance(creator.current_facts, dict) else {}
    title = facts.get("title")
    avatar = facts.get("avatar_url")
    return OutreachCreatorIdentity(
        id=creator.id,
        name=title if isinstance(title, str) and title else creator.sort_name,
        youtube_channel_id=creator.youtube_channel_id,
        canonical_url=creator.canonical_url,
        avatar_url=avatar if isinstance(avatar, str) and avatar else None,
    )


def _metric_rows(
    deliveries: list[Delivery], responses: list[CampaignCreatorResponse]
) -> list[DeliveryProjection]:
    final_states = {row.creator_id: row.state.value for row in responses}
    return [
        DeliveryProjection(
            creator_id=row.creator_id,
            send_state=row.send_state.value,
            response_state=final_states.get(row.creator_id, "no_response"),
            is_current=row.superseded_at is None,
        )
        for row in deliveries
    ]


def _public_metrics(metrics: CampaignMetrics) -> OutreachCampaignMetrics:
    return OutreachCampaignMetrics(
        sent_creators=metrics.sent_creators,
        accepted=metrics.accepted,
        declined=metrics.declined,
        no_response=metrics.no_response,
        failed=metrics.failed,
        response_rate=float(metrics.response_rate),
    )


def _latest_activity(
    campaign: OutreachCampaign,
    batches: list[SendBatch],
    deliveries: list[Delivery],
    responses: list[CampaignCreatorResponse],
) -> datetime:
    values = [campaign.created_at, campaign.updated_at]
    for batch in batches:
        values.extend((batch.created_at, batch.updated_at, batch.requested_at))
    for delivery in deliveries:
        values.extend(
            value
            for value in (
                delivery.created_at,
                delivery.updated_at,
                delivery.sending_at,
                delivery.sent_at,
                delivery.failed_at,
                delivery.responded_at,
                delivery.superseded_at,
            )
            if value is not None
        )
    for response in responses:
        values.extend(
            value
            for value in (
                response.created_at,
                response.updated_at,
                response.responded_at,
            )
            if value is not None
        )
    return max(values)


def _project_campaign_summary(
    campaign: OutreachCampaign,
    game: GameProfile,
    batches: list[SendBatch],
    deliveries: list[Delivery],
    responses: list[CampaignCreatorResponse],
) -> OutreachCampaignSummary:
    rows = _metric_rows(deliveries, responses)
    return OutreachCampaignSummary(
        id=campaign.id,
        match_task_id=campaign.match_task_id,
        game=_game_identity(game),
        state=derive_campaign_state(rows),
        send_batch_count=len(batches),
        metrics=_public_metrics(calculate_campaign_metrics(rows)),
        created_at=campaign.created_at,
        latest_activity_at=_latest_activity(campaign, batches, deliveries, responses),
    )


def _smtp_error(delivery: Delivery) -> OutreachSMTPError | None:
    value = (
        delivery.smtp_error_code,
        delivery.smtp_error_message,
        delivery.smtp_retryable,
    )
    if (
        delivery.send_state is not DeliverySendState.FAILED
        or value not in _SAFE_SMTP_ERRORS
    ):
        return None
    code, message, retryable = value
    return OutreachSMTPError(code=code, message=message, retryable=retryable)


def _project_delivery(
    delivery: Delivery,
    creator: CreatorProfile,
    *,
    final_response: CampaignCreatorResponse | None,
    superseded_by_delivery_id: UUID | None,
) -> OutreachDeliveryDetail:
    has_final_response = final_response is not None and final_response.state in {
        ResponseState.ACCEPTED,
        ResponseState.DECLINED,
    }
    is_current = delivery.superseded_at is None
    return OutreachDeliveryDetail(
        id=delivery.id,
        campaign_id=delivery.campaign_id,
        send_batch_id=delivery.send_batch_id,
        creator=_creator_identity(creator),
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
        send_state=delivery.send_state.value,
        response_state=delivery.response_state.value,
        resends_delivery_id=delivery.resends_delivery_id,
        superseded_by_delivery_id=superseded_by_delivery_id,
        is_current=is_current,
        can_resend=(
            is_current
            and delivery.send_state
            in {DeliverySendState.SENT, DeliverySendState.FAILED}
            and delivery.response_state is ResponseState.NO_RESPONSE
            and not has_final_response
        ),
        smtp_error=_smtp_error(delivery),
        created_at=delivery.created_at,
        sending_at=delivery.sending_at,
        sent_at=delivery.sent_at,
        failed_at=delivery.failed_at,
        responded_at=delivery.responded_at,
        superseded_at=delivery.superseded_at,
    )


def _outreach_state_invalid() -> APIError:
    return APIError(
        status_code=500,
        code="outreach_state_invalid",
        message="The Outreach state is invalid.",
    )


def create_router(
    authenticate_workspace: Callable,
    *,
    secret_cipher: SecretCipher,
    smtp_gateway: SMTPGateway,
    smtp_rate_limiter: SMTPRateLimiter,
    batch_dispatcher: OutreachBatchDispatcher | None = None,
    cursor_signing_secret: str,
) -> APIRouter:
    effective_batch_dispatcher = batch_dispatcher or CeleryOutreachBatchDispatcher()
    cursor_key = hashlib.sha256(
        b"find-me-gamer/outreach-campaign-cursor/v1\0" + cursor_signing_secret.encode()
    ).digest()
    router = APIRouter(
        prefix="/api/v1/outreach",
        tags=["outreach"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get(
        "/campaigns",
        response_model=OutreachCampaignPage,
        operation_id="listOutreachCampaigns",
    )
    def list_campaigns(
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        database_session: Session = Depends(get_session),
    ) -> OutreachCampaignPage:
        decoded = _decode_campaign_cursor(cursor, cursor_key)
        repository = OutreachRepository(database_session)
        roots = repository.list_campaign_roots(cursor=decoded, limit=limit + 1)
        page = roots[:limit]
        campaign_ids = {campaign.id for campaign, _task, _game in page}
        batches = repository.list_send_batches(campaign_ids)
        deliveries = repository.list_deliveries(campaign_ids)
        responses = repository.list_campaign_responses(campaign_ids)
        items = [
            _project_campaign_summary(
                campaign,
                game,
                [row for row in batches if row.campaign_id == campaign.id],
                [row for row in deliveries if row.campaign_id == campaign.id],
                [row for row in responses if row.campaign_id == campaign.id],
            )
            for campaign, _task, game in page
        ]
        next_cursor = (
            _encode_campaign_cursor(
                (page[-1][0].created_at, page[-1][0].id), cursor_key
            )
            if len(roots) > limit
            else None
        )
        return OutreachCampaignPage(
            items=items,
            cursor=next_cursor,
            has_more=len(roots) > limit,
        )

    @router.get(
        "/campaigns/{campaign_id}",
        response_model=OutreachCampaignDetail,
        operation_id="getOutreachCampaign",
    )
    def get_campaign(
        campaign_id: UUID,
        database_session: Session = Depends(get_session),
    ) -> OutreachCampaignDetail:
        repository = OutreachRepository(database_session)
        root = repository.get_campaign_root(campaign_id)
        if root is None:
            raise APIError(
                status_code=404,
                code="outreach_campaign_not_found",
                message="The Outreach Campaign was not found.",
            )
        campaign, _task, game = root
        batches = repository.list_send_batches({campaign_id})
        deliveries = repository.list_deliveries({campaign_id})
        responses = repository.list_campaign_responses({campaign_id})
        creators = {
            row.id: row
            for row in repository.list_creators(
                {delivery.creator_id for delivery in deliveries}
            )
        }
        final_responses = {row.creator_id: row for row in responses}
        superseded_by = {
            row.resends_delivery_id: row.id
            for row in deliveries
            if row.resends_delivery_id is not None
        }
        delivery_projections: dict[UUID, OutreachDeliveryDetail] = {}
        for delivery in deliveries:
            creator = creators.get(delivery.creator_id)
            if creator is None:
                raise _outreach_state_invalid()
            delivery_projections[delivery.id] = _project_delivery(
                delivery,
                creator,
                final_response=final_responses.get(delivery.creator_id),
                superseded_by_delivery_id=superseded_by.get(delivery.id),
            )
        batch_projections: list[OutreachSendBatchDetail] = []
        for batch in batches:
            batch_deliveries = [
                row for row in deliveries if row.send_batch_id == batch.id
            ]
            if not batch_deliveries:
                raise _outreach_state_invalid()
            snapshot = batch_deliveries[0]
            batch_projections.append(
                OutreachSendBatchDetail(
                    id=batch.id,
                    campaign_id=batch.campaign_id,
                    template_id=batch.template_id,
                    template_name=snapshot.template_name,
                    template_version=snapshot.template_version,
                    requested_creator_ids=[
                        UUID(value) for value in batch.requested_creator_ids
                    ],
                    requested_at=batch.requested_at,
                    state=batch.state.value,
                    deliveries=[
                        delivery_projections[row.id] for row in batch_deliveries
                    ],
                )
            )
        summary = _project_campaign_summary(
            campaign, game, batches, deliveries, responses
        )
        return OutreachCampaignDetail(
            **summary.model_dump(), send_batches=batch_projections
        )

    @router.get(
        "/deliveries/{delivery_id}",
        response_model=OutreachDeliveryDetail,
        operation_id="getOutreachDelivery",
    )
    def get_delivery(
        delivery_id: UUID,
        database_session: Session = Depends(get_session),
    ) -> OutreachDeliveryDetail:
        repository = OutreachRepository(database_session)
        delivery = repository.get_delivery(delivery_id)
        if delivery is None:
            raise APIError(
                status_code=404,
                code="delivery_not_found",
                message="The Delivery was not found.",
            )
        creators = repository.list_creators({delivery.creator_id})
        responses = repository.list_campaign_responses({delivery.campaign_id})
        history = repository.list_deliveries({delivery.campaign_id})
        creator = creators[0] if creators else None
        if creator is None:
            raise _outreach_state_invalid()
        final_response = next(
            (row for row in responses if row.creator_id == delivery.creator_id), None
        )
        superseded_by = next(
            (row.id for row in history if row.resends_delivery_id == delivery.id),
            None,
        )
        return _project_delivery(
            delivery,
            creator,
            final_response=final_response,
            superseded_by_delivery_id=superseded_by,
        )

    @router.post(
        "/send-batches/preview",
        response_model=OutreachSendBatchPreview,
        operation_id="previewOutreachSendBatch",
    )
    def preview_batch(
        payload: OutreachSendBatchRequest,
        database_session: Session = Depends(get_session),
    ) -> OutreachSendBatchPreview:
        return preview_send_batch(database_session, payload)

    @router.post(
        "/send-batches",
        response_model=OutreachSendBatchResponse,
        status_code=201,
        operation_id="createOutreachSendBatch",
    )
    def create_batch(
        payload: OutreachSendBatchRequest,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        database_session: Session = Depends(get_session),
    ) -> Response:
        key = _idempotency_key(idempotency_key)
        path = "/api/v1/outreach/send-batches"
        digest = request_hash(
            method="POST",
            path=path,
            canonical_request=payload.model_dump(mode="json"),
        )
        now = utc_now()
        try:
            _lock_idempotency_key(database_session, key)
            replay = _idempotent_replay(
                database_session, key=key, digest=digest, now=now
            )
            if replay is not None:
                database_session.commit()
                return _dispatch_committed_batch(replay, effective_batch_dispatcher)
            projection = create_send_batch(
                database_session, payload, secret_cipher=secret_cipher
            )
            body = projection.model_dump(mode="json")
            _store_batch_idempotency(
                database_session,
                key=key,
                digest=digest,
                path=path,
                body=body,
                now=now,
            )
            database_session.commit()
            return _dispatch_committed_batch(body, effective_batch_dispatcher)
        except APIError:
            database_session.rollback()
            raise
        except IntegrityError:
            database_session.rollback()
            replay = _idempotent_replay(
                database_session, key=key, digest=digest, now=now
            )
            if replay is not None:
                database_session.commit()
                return _dispatch_committed_batch(replay, effective_batch_dispatcher)
            database_session.rollback()
            raise APIError(
                status_code=409,
                code="outreach_creation_conflict",
                message="The Outreach request could not be committed safely.",
                retryable=True,
            ) from None

    @router.post(
        "/deliveries/{delivery_id}/resend",
        response_model=OutreachSendBatchResponse,
        status_code=201,
        operation_id="resendOutreachDelivery",
    )
    def resend(
        delivery_id: UUID,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        database_session: Session = Depends(get_session),
    ) -> Response:
        key = _idempotency_key(idempotency_key)
        path = f"/api/v1/outreach/deliveries/{delivery_id}/resend"
        digest = request_hash(
            method="POST",
            path=path,
            canonical_request={"delivery_id": str(delivery_id)},
        )
        now = utc_now()
        try:
            _lock_idempotency_key(database_session, key)
            replay = _idempotent_replay(
                database_session, key=key, digest=digest, now=now
            )
            if replay is not None:
                database_session.commit()
                return _dispatch_committed_batch(replay, effective_batch_dispatcher)
            projection = resend_delivery(
                database_session,
                delivery_id,
                secret_cipher=secret_cipher,
                now=now,
            )
            body = projection.model_dump(mode="json")
            _store_batch_idempotency(
                database_session,
                key=key,
                digest=digest,
                path=path,
                body=body,
                now=now,
            )
            database_session.commit()
            return _dispatch_committed_batch(body, effective_batch_dispatcher)
        except APIError:
            database_session.rollback()
            raise
        except IntegrityError:
            database_session.rollback()
            replay = _idempotent_replay(
                database_session, key=key, digest=digest, now=now
            )
            if replay is not None:
                database_session.commit()
                return _dispatch_committed_batch(replay, effective_batch_dispatcher)
            database_session.rollback()
            raise APIError(
                status_code=409,
                code="delivery_resend_conflict",
                message="The Delivery could not be resent safely.",
                retryable=True,
            ) from None

    @router.get(
        "/templates",
        response_model=OutreachTemplateList,
        operation_id="listOutreachTemplates",
    )
    def list_templates(
        database_session: Session = Depends(get_session),
    ) -> OutreachTemplateList:
        rows = OutreachRepository(database_session).list_templates()
        return OutreachTemplateList(items=[_project_template(row) for row in rows])

    @router.post(
        "/templates",
        response_model=OutreachTemplateResponse,
        status_code=201,
        operation_id="createOutreachTemplate",
    )
    def create_template(
        create: OutreachTemplateCreate,
        database_session: Session = Depends(get_session),
    ) -> OutreachTemplateResponse:
        values = create.model_dump()
        _validate_renderable(_template_data(values))
        try:
            row = OutreachRepository(database_session).create_template(values)
            database_session.commit()
        except TemplateNameConflictError:
            _rollback_and_raise(database_session, _name_conflict())
        except IntegrityError:
            _rollback_and_raise(database_session, _name_conflict())
        return _project_template(row)

    @router.get(
        "/templates/{template_id}",
        response_model=OutreachTemplateResponse,
        operation_id="getOutreachTemplate",
    )
    def get_template(
        template_id: UUID,
        database_session: Session = Depends(get_session),
    ) -> OutreachTemplateResponse:
        row = OutreachRepository(database_session).get_template(template_id)
        if row is None:
            raise _not_found()
        return _project_template(row)

    @router.patch(
        "/templates/{template_id}",
        response_model=OutreachTemplateResponse,
        operation_id="updateOutreachTemplate",
    )
    def update_template(
        template_id: UUID,
        update: OutreachTemplateUpdate,
        database_session: Session = Depends(get_session),
    ) -> OutreachTemplateResponse:
        repository = OutreachRepository(database_session)
        row = repository.get_template_for_mutation(template_id)
        if row is None:
            _rollback_and_raise(database_session, _not_found())
        changes = update.model_dump(exclude_unset=True)
        merged = {
            **template_data_from_row(row).model_dump(),
            **changes,
        }
        try:
            _validate_renderable(_template_data(merged))
            row = repository.update_template(row, changes)
            database_session.commit()
        except APIError as error:
            _rollback_and_raise(database_session, error)
        except TemplateNameConflictError:
            _rollback_and_raise(database_session, _name_conflict())
        except IntegrityError:
            _rollback_and_raise(database_session, _name_conflict())
        return _project_template(row)

    @router.delete(
        "/templates/{template_id}",
        status_code=204,
        operation_id="deleteOutreachTemplate",
    )
    def delete_template(
        template_id: UUID,
        database_session: Session = Depends(get_session),
    ) -> Response:
        repository = OutreachRepository(database_session)
        row = repository.get_template_for_mutation(template_id)
        if row is None:
            _rollback_and_raise(database_session, _not_found())
        try:
            repository.delete_template(row)
            database_session.commit()
        except LastTemplateError:
            _rollback_and_raise(
                database_session,
                APIError(
                    status_code=409,
                    code="template_last_remaining",
                    message="The only remaining Template cannot be deleted.",
                ),
            )
        except DefaultTemplateDeleteError:
            _rollback_and_raise(
                database_session,
                APIError(
                    status_code=409,
                    code="template_default_delete_forbidden",
                    message="Select another default Template before deleting this one.",
                ),
            )
        except IntegrityError:
            _rollback_and_raise(database_session, _constraint_conflict())
        return Response(status_code=204)

    @router.post(
        "/templates/{template_id}/duplicate",
        response_model=OutreachTemplateResponse,
        status_code=201,
        operation_id="duplicateOutreachTemplate",
    )
    def duplicate_template(
        template_id: UUID,
        database_session: Session = Depends(get_session),
    ) -> OutreachTemplateResponse:
        repository = OutreachRepository(database_session)
        source = repository.get_template_for_mutation(template_id)
        if source is None:
            _rollback_and_raise(database_session, _not_found())
        try:
            row = repository.duplicate_template(source)
            database_session.commit()
        except IntegrityError:
            _rollback_and_raise(database_session, _name_conflict())
        return _project_template(row)

    @router.post(
        "/templates/{template_id}/default",
        response_model=OutreachTemplateResponse,
        operation_id="setDefaultOutreachTemplate",
    )
    def set_default_template(
        template_id: UUID,
        database_session: Session = Depends(get_session),
    ) -> OutreachTemplateResponse:
        repository = OutreachRepository(database_session)
        row = repository.get_template_for_mutation(template_id)
        if row is None:
            _rollback_and_raise(database_session, _not_found())
        try:
            row = repository.set_default_template(row)
            database_session.commit()
        except IntegrityError:
            _rollback_and_raise(database_session, _constraint_conflict())
        return _project_template(row)

    @router.post(
        "/templates/{template_id}/preview",
        response_model=RenderedDelivery,
        operation_id="previewOutreachTemplate",
    )
    def preview_template(
        template_id: UUID,
        draft: Annotated[OutreachTemplatePreviewDraft | None, Body()] = None,
        database_session: Session = Depends(get_session),
    ) -> RenderedDelivery:
        row = OutreachRepository(database_session).get_template(template_id)
        if row is None:
            raise _not_found()
        values = template_data_from_row(row).model_dump()
        if draft is not None:
            values.update(draft.model_dump(exclude_unset=True))
        return _validate_renderable(_template_data(values))

    @router.get(
        "/smtp",
        response_model=SMTPSettingsResponse,
        operation_id="getOutreachSMTPSettings",
    )
    def get_smtp_settings(
        database_session: Session = Depends(get_session),
    ) -> SMTPSettingsResponse:
        repository = SettingsRepository(database_session)
        settings = repository.get_smtp_settings()
        stored = repository.get_connection("smtp")
        return _smtp_response(settings, stored)

    @router.put(
        "/smtp",
        response_model=SMTPSettingsResponse,
        operation_id="updateOutreachSMTPSettings",
    )
    def update_smtp_settings(
        update: SMTPSettingsUpdate,
        database_session: Session = Depends(get_session),
    ) -> SMTPSettingsResponse:
        repository = SettingsRepository(database_session)
        existing = repository.get_connection("smtp")
        if existing is None and update.password is None:
            raise APIError(
                status_code=409,
                code="smtp_password_required",
                message="A password is required when SMTP is first configured.",
            )
        encrypted = (
            secret_cipher.encrypt(update.password)
            if update.password is not None
            else None
        )
        values = update.model_dump(exclude={"password"})
        public = {field: values[field] for field in SMTP_PUBLIC_FIELDS}
        settings, stored = repository.save_smtp_configuration(
            public_metadata=public,
            emails_per_minute=update.emails_per_minute,
            encrypted_password=encrypted,
        )
        database_session.commit()
        return _smtp_response(settings, stored)

    @router.post(
        "/smtp/test-connection",
        response_model=SMTPTestResult,
        operation_id="testOutreachSMTPConnection",
    )
    def test_smtp_connection(
        database_session: Session = Depends(get_session),
    ) -> SMTPTestResult:
        config, encrypted, public, _rate = _load_smtp_config(
            database_session, secret_cipher
        )
        try:
            smtp_gateway.probe(config)
            succeeded = True
        except Exception:
            succeeded = False
        finally:
            config = _redact_config(config)
        return _record_smtp_result(
            database_session,
            encrypted=encrypted,
            public=public,
            succeeded=succeeded,
        )

    @router.post(
        "/smtp/test-email",
        response_model=SMTPTestResult,
        operation_id="sendOutreachSMTPTestEmail",
    )
    def send_smtp_test_email(
        request: SMTPTestEmailRequest,
        database_session: Session = Depends(get_session),
    ) -> SMTPTestResult:
        config, encrypted, public, rate = _load_smtp_config(
            database_session, secret_cipher
        )
        try:
            try:
                delay = smtp_rate_limiter.acquire(str(SHARED_SETTINGS_ID), rate)
            except SMTPRateLimitError:
                raise APIError(
                    status_code=503,
                    code="smtp_rate_limit_unavailable",
                    message="SMTP rate limiting is temporarily unavailable.",
                    retryable=True,
                ) from None
            if delay > 0:
                raise APIError(
                    status_code=429,
                    code="smtp_rate_limited",
                    message="The SMTP send rate is temporarily limited.",
                    retryable=True,
                )
            message = EmailMessage()
            message["From"] = formataddr((config.from_name, config.username))
            message["Reply-To"] = config.reply_to
            message["To"] = str(request.recipient)
            message["Subject"] = "Find Me Gamer SMTP Test"
            message.set_content(
                "Find Me Gamer SMTP configuration is working.\n\n"
                "This diagnostic message confirms the configured sender can deliver mail."
            )
            try:
                smtp_gateway.send(config, message)
                succeeded = True
            except SMTPError:
                succeeded = False
            except Exception:
                succeeded = False
        finally:
            config = _redact_config(config)
        return _record_smtp_result(
            database_session,
            encrypted=encrypted,
            public=public,
            succeeded=succeeded,
        )

    return router


__all__ = ["create_router"]
