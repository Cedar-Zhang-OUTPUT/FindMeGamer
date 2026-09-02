"""Authenticated shared Outreach Template management and preview API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.errors import APIError
from app.db.models.outreach import Template
from app.outreach.templates import TemplateValidationError, render_delivery
from app.repositories.outreach import (
    DefaultTemplateDeleteError,
    LastTemplateError,
    OutreachRepository,
    TemplateNameConflictError,
    template_data_from_row,
)
from app.schemas.outreach import (
    OutreachTemplateCreate,
    OutreachTemplateList,
    OutreachTemplatePreviewDraft,
    OutreachTemplateResponse,
    OutreachTemplateUpdate,
    RenderedDelivery,
    ResponseURLs,
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


def create_router(authenticate_workspace: Callable) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/outreach/templates",
        tags=["outreach"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get(
        "",
        response_model=OutreachTemplateList,
        operation_id="listOutreachTemplates",
    )
    def list_templates(
        database_session: Session = Depends(get_session),
    ) -> OutreachTemplateList:
        rows = OutreachRepository(database_session).list_templates()
        return OutreachTemplateList(items=[_project_template(row) for row in rows])

    @router.post(
        "",
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
        "/{template_id}",
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
        "/{template_id}",
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
        "/{template_id}",
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
        "/{template_id}/duplicate",
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
        "/{template_id}/default",
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
        "/{template_id}/preview",
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

    return router


__all__ = ["create_router"]
