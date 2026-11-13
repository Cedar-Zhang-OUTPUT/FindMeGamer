from fastapi import APIRouter, Depends, Header, Request, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..auth import Principal, require_scope, authenticate
from .templates import get_template, list_templates
from .jobs import JobStore
from .urls import public_url
from .evidence import ContactEvidence
from .sending import SendStore, email_address
from typing import Literal
from ..usage import Ledger

router = APIRouter(prefix="/v1/email")


@router.get("/inbox")
def inbox_messages(
    request: Request,
    mailbox_id: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=80),
    message_id: str | None = Query(default=None, max_length=80),
    principal: Principal = Depends(require_scope("email:read")),
):
    from .folders import read_inbox
    from ..errors import ApiError

    if cursor and message_id:
        raise ApiError(
            422, "inbox_reference_invalid", "Use cursor or message_id, not both."
        )
    config = request.app.state.mailboxes.current().settings_for(mailbox_id)
    return result(
        request,
        read_inbox(
            config, mailbox_id, limit=limit, cursor=cursor, message_id=message_id
        ),
    )


@router.get("/sent")
def sent_messages(
    request: Request,
    mailbox_id: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=80),
    message_id: str | None = Query(default=None, max_length=80),
    principal: Principal = Depends(require_scope("email:read")),
):
    from .sent import read_sent
    from ..errors import ApiError

    if cursor and message_id:
        raise ApiError(
            422, "sent_reference_invalid", "Use cursor or message_id, not both."
        )
    config = request.app.state.mailboxes.current().settings_for(mailbox_id)
    return result(
        request,
        read_sent(
            config, mailbox_id, limit=limit, cursor=cursor, message_id=message_id
        ),
    )


@router.get("/mailboxes")
def mailboxes(request: Request, principal: Principal = Depends(authenticate)):
    from ..errors import ApiError

    if not {"email:send", "email:read"}.intersection(principal.scopes):
        raise ApiError(
            403, "insufficient_scope", "This token does not allow this operation."
        )
    return {
        "data": request.app.state.mailboxes.current().public_entries(),
        "meta": {"request_id": request.state.request_id, "mailboxes_version": 1},
    }


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mailbox_id: str | None = Field(default=None, max_length=40)
    template_id: str = Field(max_length=100)
    template_version: str = Field(max_length=40)
    variables: dict[str, str]
    to: str = Field(max_length=254)

    @field_validator("to")
    @classmethod
    def validate_to(cls, value):
        return email_address(value)


class ReplyPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply_id: str = Field(min_length=1, max_length=36)
    mailbox_id: str = Field(min_length=1, max_length=40)
    template_id: str | None = Field(default=None, max_length=100)
    template_version: str | None = Field(default=None, max_length=40)
    variables: dict[str, str] = Field(default_factory=dict)
    text: str | None = Field(default=None, min_length=1, max_length=50000)
    text_confirmed: Literal[True] | None = None
    recipient_mode: Literal["sender", "reply_to"] = "sender"

    @model_validator(mode="after")
    def content_choice(self):
        if self.template_id:
            if (
                self.template_id == "custom-reply"
                or not self.template_version
                or self.text is not None
                or self.text_confirmed is not None
            ):
                raise ValueError(
                    "Choose a versioned reply template or confirmed custom text, not both."
                )
        elif (
            not self.text
            or not self.text.strip()
            or self.text_confirmed is not True
            or self.template_version
            or self.variables
        ):
            raise ValueError(
                "Custom text requires text_confirmed=true and no template variables."
            )
        if any(len(v) > 300 or "\r" in v or "\n" in v for v in self.variables.values()):
            raise ValueError(
                "Reply template variables must be single-line text up to 300 characters."
            )
        return self


@router.post("/reply-previews", status_code=201)
def create_reply_preview(
    request: Request,
    body: ReplyPreviewRequest,
    principal: Principal = Depends(require_scope("email:send")),
):
    from .replies import create_reply_preview as prepare

    return result(
        request,
        prepare(
            request.app.state.sessions,
            principal.id,
            body.model_dump(),
            request.app.state.settings,
            request.app.state.mailboxes.current(),
        ),
    )


@router.get("/reply-history")
def read_reply_history(
    request: Request,
    task_id: str = Query(min_length=1, max_length=36),
    creator_id: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=10, ge=1, le=20),
    cursor: str | None = Query(default=None, max_length=36),
    principal: Principal = Depends(require_scope("email:send")),
):
    from .replies import reply_history

    return result(
        request,
        reply_history(
            request.app.state.sessions,
            principal.id,
            task_id,
            creator_id=creator_id,
            limit=limit,
            cursor=cursor,
        ),
    )


@router.get("/replies/{reply_id}")
def read_reply(
    request: Request,
    reply_id: str,
    principal: Principal = Depends(require_scope("email:send")),
):
    from .replies import owned_reply, source_context

    with request.app.state.sessions() as session:
        reply, send, preview = owned_reply(session, reply_id, principal.id)
        return result(
            request,
            {
                **source_context(session, reply, send, preview),
                "mailbox_id": preview.mailbox_id,
                "kind": reply.kind,
                "thread_headers": (reply.diagnostics or {}).get("thread_headers"),
            },
        )


@router.get("/receipts")
def read_receipt_by_key(
    request: Request,
    idempotency_key: str = Query(min_length=1, max_length=200),
    principal: Principal = Depends(require_scope("email:send")),
):
    return result(
        request,
        SendStore(request.app.state.sessions).get_receipt_by_key(
            idempotency_key, principal.id
        ),
    )


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
            principal.id,
            body.model_dump(),
            request.app.state.settings,
            registry=request.app.state.mailboxes.current(),
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
            preview_id,
            principal.id,
            request.app.state.settings,
            registry=request.app.state.mailboxes.current(),
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
            registry=request.app.state.mailboxes,
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
    evidence: list[ContactEvidence] | None = Field(default=None, max_length=10)

    @field_validator("evidence")
    @classmethod
    def validate_evidence_size(cls, value):
        if value is not None and sum(len(item.text) for item in value) > 32000:
            raise ValueError("Evidence text exceeds 32000 characters.")
        return value

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
    request: Request,
    template_id: str,
    version: str | None = Query(default=None, max_length=40),
    principal: Principal = Depends(authenticate),
):
    return result(request, get_template(template_id, version))


@router.post("/enrich", status_code=202)
def enrich(
    request: Request,
    body: EnrichRequest,
    idempotency_key: str = Header(min_length=1, max_length=200),
    principal: Principal = Depends(require_scope("email:enrich")),
):
    store = JobStore(request.app.state.sessions)
    payload = body.model_dump()
    if payload["evidence"] is None:
        del payload["evidence"]
    return result(
        request,
        store.create(principal.id, idempotency_key, payload, request.state.run_id),
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
