"""Frozen, explicitly approved batches; delivery reuses single-send reservations."""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from html import escape
import json
import secrets
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .auth import Principal, require_scope
from .db import Base
from .email.models import EmailPreview, EmailSend
from .email.routes import PreviewRequest, result
from .email.sending import SendStore, smtp_ready, email_address
from .email.templates import get_template, render_template
from .email.urls import public_url
from .errors import ApiError
from .usage import Ledger


class OutreachTask(Base):
    __tablename__ = "outreach_tasks"
    __table_args__ = (UniqueConstraint("token_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_id: Mapped[str] = mapped_column(ForeignKey("access_tokens.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    run_id: Mapped[str] = mapped_column(String(100))
    template: Mapped[dict] = mapped_column(JSON)


class OutreachRecipient(Base):
    __tablename__ = "outreach_recipients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("outreach_tasks.id"), index=True)
    creator_id: Mapped[str] = mapped_column(String(300))
    preview_id: Mapped[str] = mapped_column(ForeignKey("email_previews.id"), unique=True)
    response_digest: Mapped[str] = mapped_column(String(64), unique=True)
    response: Mapped[str | None] = mapped_column(String(3))
    responded_at: Mapped[str | None] = mapped_column(String(40))


class RecipientInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    creator_id: str = Field(min_length=1, max_length=300)
    to: str = Field(max_length=254)
    variables: dict[str, str]

    @field_validator("to")
    @classmethod
    def validate_to(cls, value):
        return email_address(value)


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    template_id: str = Field(max_length=100)
    template_version: str = Field(max_length=40)
    recipients: list[RecipientInput] = Field(min_length=1, max_length=1000)


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]
    revision: str


router = APIRouter()
owner = require_scope("email:send")


def digest(value):
    return sha256(value.encode()).hexdigest()


def owned(session, task_id, token_id):
    task = session.get(OutreachTask, task_id)
    if task is None or task.token_id != token_id:
        raise ApiError(404, "task_not_found", "Task was not found.")
    return task


def view(sessions, task_id, token_id):
    SendStore(sessions).recover_interrupted()
    with sessions() as session:
        task = owned(session, task_id, token_id)
        rows = session.execute(select(OutreachRecipient, EmailPreview, EmailSend).join(
            EmailPreview, OutreachRecipient.preview_id == EmailPreview.id
        ).outerjoin(EmailSend, EmailSend.preview_id == EmailPreview.id).where(
            OutreachRecipient.task_id == task_id
        ).order_by(EmailPreview.created_at, OutreachRecipient.id)).all()
        recipients = [{"id": r.id, "creator_id": r.creator_id, "message": p.message,
                       "state": s.state if s else "pending", "code": s.code if s else None,
                       "response": r.response, "responded_at": r.responded_at}
                      for r, p, s in rows]
        stats = {key: sum(r["state"] == key for r in recipients)
                 for key in ("sent", "failed", "unknown", "sending", "pending")}
        stats.update({key: sum(r["response"] == key for r in recipients) for key in ("yes", "no")})
        # Unknown deliveries can receive responses; exclude them from both terms of this rate.
        confirmed_sent = sum(r["state"] == "sent" and r["response"] is not None for r in recipients)
        stats["response_rate"] = confirmed_sent / stats["sent"] if stats["sent"] else None
        state = task.state
        if state == "sending" and not stats["pending"] and not stats["sending"]:
            state = "finished_with_issues" if stats["failed"] + stats["unknown"] else "completed"
        return {"id": task.id, "name": task.name, "revision": task.revision,
                "state": state, "template": task.template, "stats": stats, "recipients": recipients}


@router.post("/v1/outreach/tasks", status_code=201)
def create_task(request: Request, body: TaskInput,
                idempotency_key: str = Header(min_length=1, max_length=200),
                principal: Principal = Depends(owner)):
    settings, sessions = request.app.state.settings, request.app.state.sessions
    try:
        base = public_url(settings.outreach_public_url).rstrip("/")
    except ValueError:
        raise ApiError(503, "callback_not_configured", "Configure the public response URL.") from None
    if not base.startswith("https://") or "?" in base or "#" in base:
        raise ApiError(503, "callback_not_configured", "Use a public HTTPS response base URL.")
    fingerprint = digest(json.dumps(body.model_dump(), sort_keys=True))
    def existing(session):
        task = session.scalar(select(OutreachTask).where(OutreachTask.token_id == principal.id,
                              OutreachTask.idempotency_key == idempotency_key))
        if task and task.fingerprint != fingerprint:
            raise ApiError(409, "idempotency_conflict", "This key belongs to different task contents.")
        return task
    with sessions() as session:
        old = existing(session)
        if old:
            return result(request, view(sessions, old.id, principal.id))
        definition = get_template(body.template_id, body.template_version)
        task = OutreachTask(id=str(uuid4()), token_id=principal.id, idempotency_key=idempotency_key,
                            fingerprint=fingerprint, revision=secrets.token_hex(32), name=body.name,
                            state="awaiting_approval", run_id=request.state.run_id, template=definition)
        session.add(task)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            old = existing(session)
            if old is None:
                raise
            return result(request, view(sessions, old.id, principal.id))
        seen = set()
        for entry in body.recipients:
            validated = PreviewRequest(template_id=body.template_id, template_version=body.template_version,
                                       to=entry.to, variables=entry.variables)
            identity = validated.to.casefold()
            if identity in seen:
                raise ApiError(422, "duplicate_recipient", "Use each recipient email only once per task.")
            seen.add(identity)
            secret = secrets.token_urlsafe(32)
            url = base + "/v1/outreach/respond/" + secret
            message = render_template(definition, validated.variables)
            message.update({"to": validated.to, "from": settings.smtp_from or None})
            message["text"] += f"\n\nYes: {url}?choice=yes\nNo: {url}?choice=no\nConfirm your choice on the linked page."
            actions = ''.join(
                f'<a href="{escape(url)}?choice={choice}" style="display:inline-block;padding:12px 18px;margin:4px 8px 4px 0;border:1px solid #27644f;border-radius:6px;background:{background};color:{color};font:14px Arial,sans-serif;text-decoration:none">{label}</a>'
                for choice, label, background, color in (
                    ("yes", "Yes, I’m in", "#27644f", "#ffffff"),
                    ("no", "No, not interested", "#ffffff", "#27644f")))
            actions += '<p style="font:12px Arial,sans-serif;color:#697870">Your choice is recorded only after confirmation on the next page.</p>'
            if "<!--FMG_RESPONSE_ACTIONS-->" in message["html"]:
                message["html"] = message["html"].replace("<!--FMG_RESPONSE_ACTIONS-->", actions)
            else:
                message["html"] += actions
            preview = EmailPreview(id=str(uuid4()), token_id=principal.id, template_id=body.template_id,
                                   template_version=body.template_version, message=message)
            session.add(preview)
            session.flush()
            session.add(OutreachRecipient(id=str(uuid4()), task_id=task.id, creator_id=entry.creator_id,
                                           preview_id=preview.id, response_digest=digest(secret)))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            task = existing(session)
            if task is None:
                raise
        return result(request, view(sessions, task.id, principal.id))


@router.get("/v1/outreach/tasks")
def list_tasks(request: Request, principal: Principal = Depends(owner)):
    with request.app.state.sessions() as session:
        tasks = session.scalars(select(OutreachTask).where(OutreachTask.token_id == principal.id)).all()
        return result(request, [{"id": t.id, "name": t.name} for t in tasks])


@router.get("/v1/outreach/tasks/{task_id}")
def get_task(request: Request, task_id: str, principal: Principal = Depends(owner)):
    return result(request, view(request.app.state.sessions, task_id, principal.id))


@router.post("/v1/outreach/tasks/{task_id}/start")
def start_task(request: Request, task_id: str, body: Approval, principal: Principal = Depends(owner)):
    sessions, settings = request.app.state.sessions, request.app.state.settings
    with sessions() as session:
        task = owned(session, task_id, principal.id)
        if task.revision != body.revision:
            raise ApiError(409, "revision_mismatch", "Review and confirm this exact task revision.")
        if task.state in {"awaiting_approval", "blocked"}:
            if not smtp_ready(settings):
                raise ApiError(503, "smtp_not_configured", "Configure SMTP before starting.")
            for preview in session.scalars(select(EmailPreview).join(OutreachRecipient).where(OutreachRecipient.task_id == task_id)):
                if preview.message["from"] != settings.smtp_from:
                    raise ApiError(409, "sender_changed", "Create and review a new task with the configured sender.")
                created = preview.created_at.replace(tzinfo=timezone.utc) if preview.created_at.tzinfo is None else preview.created_at
                if created < datetime.now(timezone.utc) - timedelta(days=30):
                    raise ApiError(409, "preview_expired", "Create and review a fresh task.")
            task.state = "sending"
            session.commit()
    return result(request, view(sessions, task_id, principal.id))


def pending(sessions):
    SendStore(sessions).recover_interrupted()
    with sessions() as session:
        return list(session.scalars(select(OutreachRecipient.id).join(OutreachTask).outerjoin(
            EmailSend, EmailSend.preview_id == OutreachRecipient.preview_id
        ).where(OutreachTask.state == "sending", EmailSend.id.is_(None)).limit(20)))


def process_recipient(sessions, recipient_id, settings, transport):
    with sessions() as session:
        recipient = session.get(OutreachRecipient, recipient_id)
        if recipient is None:
            return
        task = session.get(OutreachTask, recipient.task_id)
        if task.state != "sending":
            return
        def tracked(config, message, send_id):
            ledger = Ledger(sessions)
            key = "smtp:" + send_id
            ledger.start(key, task.token_id, task.run_id, "smtp", "send")
            try:
                outcome = transport(config, message, send_id)
            except Exception:
                ledger.finish(key, "unknown")
                raise
            ledger.finish(key, outcome["state"])
            return outcome
        try:
            SendStore(sessions).send(task.token_id, recipient.preview_id, "outreach:" + recipient.id, settings, tracked)
        except ApiError:
            # Configuration/preflight failures must not spin endlessly in the dispatcher.
            session.execute(update(OutreachTask).where(OutreachTask.id == task.id,
                OutreachTask.state == "sending").values(state="blocked"))
            session.commit()
            raise


@router.api_route("/v1/outreach/respond/{secret}", methods=["GET", "POST"], response_class=HTMLResponse)
def respond(request: Request, secret: str, choice: Literal["yes", "no"]):
    with request.app.state.sessions() as session:
        recipient = session.scalar(select(OutreachRecipient).where(OutreachRecipient.response_digest == digest(secret)))
        if recipient is None:
            raise ApiError(404, "invitation_not_found", "Invitation was not found.")
        receipt = session.scalar(select(EmailSend).where(EmailSend.preview_id == recipient.preview_id))
        if receipt is None or receipt.state not in {"sent", "unknown", "sending"}:
            raise ApiError(409, "invitation_not_sent", "Invitation has not been sent.")
        if request.method == "POST":
            session.execute(update(OutreachRecipient).where(OutreachRecipient.id == recipient.id,
                OutreachRecipient.response.is_(None)).values(response=choice, responded_at=datetime.now(timezone.utc).isoformat()))
            session.commit()
            session.refresh(recipient)
            if recipient.response != choice:
                raise ApiError(409, "response_already_recorded", "A different response is already recorded. Contact the sender to change it.")
            content = "Your response has been recorded. Thank you."
        else:
            content = f'<h1>Confirm your response: {choice.title()}</h1><form method="post"><button type="submit">Confirm {choice.title()}</button></form>'
        return HTMLResponse('<!doctype html><meta name="viewport" content="width=device-width"><title>Invitation response</title>' + content,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; form-action 'self'; frame-ancestors 'none'"})
