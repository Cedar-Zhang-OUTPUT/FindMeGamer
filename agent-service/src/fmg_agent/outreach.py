"""Frozen, explicitly approved batches; delivery reuses single-send reservations."""

from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import secrets
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
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
    preview_id: Mapped[str] = mapped_column(
        ForeignKey("email_previews.id"), unique=True
    )


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
        rows = session.execute(
            select(OutreachRecipient, EmailPreview, EmailSend)
            .join(EmailPreview, OutreachRecipient.preview_id == EmailPreview.id)
            .outerjoin(EmailSend, EmailSend.preview_id == EmailPreview.id)
            .where(OutreachRecipient.task_id == task_id)
            .order_by(EmailPreview.created_at, OutreachRecipient.id)
        ).all()
        from .email.inbox import EmailReply

        send_ids = [s.id for _, _, s in rows if s]
        replies = (
            session.scalars(
                select(EmailReply)
                .where(EmailReply.send_id.in_(send_ids))
                .order_by(EmailReply.received_at)
            ).all()
            if send_ids
            else []
        )
        grouped = {}
        for reply in replies:
            grouped.setdefault(reply.send_id, []).append(
                {
                    key: getattr(reply, key)
                    for key in (
                        "id",
                        "kind",
                        "sender",
                        "subject",
                        "body",
                        "received_at",
                    )
                }
            )
        recipients = []
        for r, p, s in rows:
            messages = grouped.get(s.id, []) if s else []
            kinds = {m["kind"] for m in messages}
            reply_state = (
                "replied"
                if "human" in kinds
                else (
                    "bounced"
                    if "bounce" in kinds
                    else "automatic" if "automatic" in kinds else "no_reply"
                )
            )
            recipients.append(
                {
                    "id": r.id,
                    "creator_id": r.creator_id,
                    "message": p.message,
                    "state": s.state if s else "pending",
                    "code": s.code if s else None,
                    "reply_state": reply_state,
                    "replies": messages,
                }
            )
        stats = {
            key: sum(r["state"] == key for r in recipients)
            for key in ("sent", "failed", "unknown", "sending", "pending")
        }
        stats.update(
            {
                key: sum(r["reply_state"] == value for r in recipients)
                for key, value in (
                    ("replied", "replied"),
                    ("automatic", "automatic"),
                    ("bounced", "bounced"),
                )
            }
        )
        replied_sent = sum(
            r["state"] == "sent" and r["reply_state"] == "replied" for r in recipients
        )
        stats["reply_rate"] = replied_sent / stats["sent"] if stats["sent"] else None
        state = task.state
        if state == "sending" and not stats["pending"] and not stats["sending"]:
            state = (
                "finished_with_issues"
                if stats["failed"] + stats["unknown"]
                else "completed"
            )
        return {
            "id": task.id,
            "name": task.name,
            "revision": task.revision,
            "state": state,
            "template": task.template,
            "stats": stats,
            "recipients": recipients,
        }


@router.post("/v1/outreach/tasks", status_code=201)
def create_task(
    request: Request,
    body: TaskInput,
    idempotency_key: str = Header(min_length=1, max_length=200),
    principal: Principal = Depends(owner),
):
    settings, sessions = request.app.state.settings, request.app.state.sessions
    fingerprint = digest(json.dumps(body.model_dump(), sort_keys=True))

    def existing(session):
        task = session.scalar(
            select(OutreachTask).where(
                OutreachTask.token_id == principal.id,
                OutreachTask.idempotency_key == idempotency_key,
            )
        )
        if task and task.fingerprint != fingerprint:
            raise ApiError(
                409,
                "idempotency_conflict",
                "This key belongs to different task contents.",
            )
        return task

    with sessions() as session:
        old = existing(session)
        if old:
            return result(request, view(sessions, old.id, principal.id))
        definition = get_template(body.template_id, body.template_version)
        task = OutreachTask(
            id=str(uuid4()),
            token_id=principal.id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            revision=secrets.token_hex(32),
            name=body.name,
            state="awaiting_approval",
            run_id=request.state.run_id,
            template=definition,
        )
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
            validated = PreviewRequest(
                template_id=body.template_id,
                template_version=body.template_version,
                to=entry.to,
                variables=entry.variables,
            )
            identity = validated.to.casefold()
            if identity in seen:
                raise ApiError(
                    422,
                    "duplicate_recipient",
                    "Use each recipient email only once per task.",
                )
            seen.add(identity)
            message = render_template(definition, validated.variables)
            message.update({"to": validated.to, "from": settings.smtp_from or None})
            preview = EmailPreview(
                id=str(uuid4()),
                token_id=principal.id,
                template_id=body.template_id,
                template_version=body.template_version,
                message=message,
            )
            session.add(preview)
            session.flush()
            session.add(
                OutreachRecipient(
                    id=str(uuid4()),
                    task_id=task.id,
                    creator_id=entry.creator_id,
                    preview_id=preview.id,
                )
            )
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
        tasks = session.scalars(
            select(OutreachTask).where(OutreachTask.token_id == principal.id)
        ).all()
        return result(request, [{"id": t.id, "name": t.name} for t in tasks])


@router.get("/v1/outreach/tasks/{task_id}")
def get_task(request: Request, task_id: str, principal: Principal = Depends(owner)):
    data = view(request.app.state.sessions, task_id, principal.id)
    from .email.inbox import monitoring_status

    data["monitoring"] = monitoring_status(
        request.app.state.sessions, request.app.state.settings
    )
    return result(request, data)


@router.post("/v1/outreach/tasks/{task_id}/start")
def start_task(
    request: Request,
    task_id: str,
    body: Approval,
    principal: Principal = Depends(owner),
):
    sessions, settings = request.app.state.sessions, request.app.state.settings
    with sessions() as session:
        task = owned(session, task_id, principal.id)
        if task.revision != body.revision:
            raise ApiError(
                409, "revision_mismatch", "Review and confirm this exact task revision."
            )
        if task.state in {"awaiting_approval", "blocked"}:
            if not smtp_ready(settings):
                raise ApiError(
                    503, "smtp_not_configured", "Configure SMTP before starting."
                )
            for preview in session.scalars(
                select(EmailPreview)
                .join(OutreachRecipient)
                .where(OutreachRecipient.task_id == task_id)
            ):
                if preview.message.get("format") not in {"plain_text", "signature_image"}:
                    raise ApiError(
                        409,
                        "preview_format_retired",
                        "Create and review a task using a current supported template.",
                    )
                if preview.message["from"] != settings.smtp_from:
                    raise ApiError(
                        409,
                        "sender_changed",
                        "Create and review a new task with the configured sender.",
                    )
                created = (
                    preview.created_at.replace(tzinfo=timezone.utc)
                    if preview.created_at.tzinfo is None
                    else preview.created_at
                )
                if created < datetime.now(timezone.utc) - timedelta(days=30):
                    raise ApiError(
                        409, "preview_expired", "Create and review a fresh task."
                    )
            task.state = "sending"
            session.commit()
    return result(request, view(sessions, task_id, principal.id))


def pending(sessions):
    SendStore(sessions).recover_interrupted()
    with sessions() as session:
        return list(
            session.scalars(
                select(OutreachRecipient.id)
                .join(OutreachTask)
                .outerjoin(
                    EmailSend, EmailSend.preview_id == OutreachRecipient.preview_id
                )
                .where(OutreachTask.state == "sending", EmailSend.id.is_(None))
                .limit(20)
            )
        )


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
            SendStore(sessions).send(
                task.token_id,
                recipient.preview_id,
                "outreach:" + recipient.id,
                settings,
                tracked,
            )
        except ApiError:
            # Configuration/preflight failures must not spin endlessly in the dispatcher.
            session.execute(
                update(OutreachTask)
                .where(OutreachTask.id == task.id, OutreachTask.state == "sending")
                .values(state="blocked")
            )
            session.commit()
            raise
