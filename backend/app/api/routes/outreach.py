"""Authenticated Outreach Template and SMTP configuration API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.crypto import EncryptedValue, SecretCipher
from app.core.errors import APIError
from app.db.models.outreach import Template
from app.db.models.settings import ServiceSecret
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
    OutreachTemplateCreate,
    OutreachTemplateList,
    OutreachTemplatePreviewDraft,
    OutreachTemplateResponse,
    OutreachTemplateUpdate,
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


def create_router(
    authenticate_workspace: Callable,
    *,
    secret_cipher: SecretCipher,
    smtp_gateway: SMTPGateway,
    smtp_rate_limiter: SMTPRateLimiter,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/outreach",
        tags=["outreach"],
        dependencies=[Depends(authenticate_workspace)],
    )

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
