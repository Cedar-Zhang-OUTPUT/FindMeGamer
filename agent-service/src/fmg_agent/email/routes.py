from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..auth import Principal, require_scope, authenticate
from .templates import get_template, list_templates
from .jobs import JobStore
from .urls import public_url
from .sending import SendStore, email_address
from typing import Literal
from ..usage import Ledger

router = APIRouter(prefix="/v1/email")


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str = Field(max_length=100)
    template_version: str = Field(max_length=40)
    variables: dict[str, str]
    to: str = Field(max_length=254)

    @field_validator("to")
    @classmethod
    def validate_to(cls, value):
        return email_address(value)


class SendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(min_length=1, max_length=36)
    confirm: Literal[True]


@router.post("/previews", status_code=201)
def create_preview(
    request: Request,
    body: PreviewRequest,
    principal: Principal = Depends(require_scope("email:send")),
):
    return result(
        request,
        SendStore(request.app.state.sessions).preview(
            principal.id, body.model_dump(), request.app.state.settings
        ),
    )


@router.get("/previews/{preview_id}")
def read_preview(
    request: Request,
    preview_id: str,
    principal: Principal = Depends(require_scope("email:send")),
):
    return result(
        request,
        SendStore(request.app.state.sessions).get_preview(
            preview_id, principal.id, request.app.state.settings
        ),
    )


@router.post("/sends")
def create_send(
    request: Request,
    body: SendRequest,
    idempotency_key: str = Header(min_length=1, max_length=200),
    principal: Principal = Depends(require_scope("email:send")),
):
    from .smtp import deliver

    transport = getattr(request.app.state, "smtp_transport", None) or deliver

    def tracked(config, message, send_id):
        ledger = Ledger(request.app.state.sessions)
        key = "smtp:" + send_id
        ledger.start(key, principal.id, request.state.run_id, "smtp", "send")
        try:
            outcome = transport(config, message, send_id)
        except Exception:
            ledger.finish(key, "unknown")
            raise
        ledger.finish(key, outcome["state"])
        return outcome

    return result(
        request,
        SendStore(request.app.state.sessions).send(
            principal.id,
            body.preview_id,
            idempotency_key,
            request.app.state.settings,
            tracked,
        ),
    )


@router.get("/sends/{send_id}")
def read_send(
    request: Request,
    send_id: str,
    principal: Principal = Depends(require_scope("email:send")),
):
    return result(
        request,
        SendStore(request.app.state.sessions).get_receipt(send_id, principal.id),
    )


class EnrichRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, max_length=300)
    platform: str | None = Field(default=None, max_length=40)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        return public_url(value)


def result(request, data):
    return {"data": data, "meta": {"request_id": request.state.request_id}}


@router.get("/templates")
def templates(request: Request, principal: Principal = Depends(authenticate)):
    return result(request, list_templates())


@router.get("/templates/{template_id}")
def template(
    request: Request, template_id: str, principal: Principal = Depends(authenticate)
):
    return result(request, get_template(template_id))


@router.post("/enrich", status_code=202)
def enrich(
    request: Request,
    body: EnrichRequest,
    idempotency_key: str = Header(min_length=1, max_length=200),
    principal: Principal = Depends(require_scope("email:enrich")),
):
    store = JobStore(request.app.state.sessions)
    return result(
        request,
        store.create(
            principal.id, idempotency_key, body.model_dump(), request.state.run_id
        ),
    )


@router.get("/jobs/{job_id}")
def job(
    request: Request,
    job_id: str,
    principal: Principal = Depends(require_scope("email:enrich")),
):
    store = JobStore(request.app.state.sessions)
    return result(request, store.load(job_id, principal.id))


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(
    request: Request,
    job_id: str,
    principal: Principal = Depends(require_scope("email:enrich")),
):
    store = JobStore(request.app.state.sessions)
    return result(request, store.retry(job_id, principal.id))
