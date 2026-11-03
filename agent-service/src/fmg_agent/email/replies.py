"""Reply drafts bind one owned incoming message to an immutable outbound message."""

from sqlalchemy import select, func

from ..errors import ApiError
from .inbox import EmailReply
from .models import EmailPreview, EmailSend, EmailBounceRetry
from .threading import valid_message_id, reply_subject, reply_references


def check_reply_template(profile, template_id, *, status_code=422):
    if template_id == "custom-reply":
        return  # An explicitly confirmed body, bound to an owned human reply.
    if template_id not in profile.allowed_reply_templates or (
        template_id == "thieves-demo-access-reply"
        and (
            profile.id != "second"
            or profile.smtp_from.casefold() != "norestforthieves@ontologyplay.com"
        )
    ):
        raise ApiError(
            status_code,
            "mailbox_template_not_allowed",
            "Reply template is not allowed for this mailbox.",
        )


def check_frozen_template(profile, preview, *, status_code=409):
    from .templates import check_mailbox_template

    if preview.message.get("reply_context"):
        check_reply_template(profile, preview.template_id, status_code=status_code)
    else:
        check_mailbox_template(profile, preview.template_id, status_code=status_code)


def owned_reply(session, reply_id, token_id):
    row = session.execute(
        select(EmailReply, EmailSend, EmailPreview)
        .join(EmailSend, EmailSend.id == EmailReply.send_id)
        .join(EmailPreview, EmailPreview.id == EmailSend.preview_id)
        .where(
            EmailReply.id == reply_id,
            EmailSend.token_id == token_id,
            EmailPreview.token_id == token_id,
        )
    ).first()
    if row is None:
        raise ApiError(404, "reply_not_found", "Reply was not found.")
    return row


def source_context(session, reply, send, preview):
    from ..outreach import OutreachRecipient

    previous = preview.message.get("reply_context") or {}
    root_send_id = previous.get("root_send_id", send.id)
    root_preview_id = preview.id
    # Replies to a bounce retry belong to the original campaign recipient too.
    retry = session.scalar(
        select(EmailBounceRetry).where(EmailBounceRetry.preview_id == preview.id)
    )
    if retry:
        original = session.get(EmailSend, retry.original_send_id)
        root_preview_id, root_send_id = original.preview_id, original.id
    recipient = session.scalar(
        select(OutreachRecipient).where(OutreachRecipient.preview_id == root_preview_id)
    )
    return {
        "reply_id": reply.id,
        "source_send_id": send.id,
        "root_send_id": root_send_id,
        "task_id": previous.get("task_id")
        or (recipient.task_id if recipient else None),
        "creator_id": previous.get("creator_id")
        or (recipient.creator_id if recipient else None),
        "original_sender": reply.sender,
        "original_subject": reply.subject,
        "original_body": reply.body,
        "received_at": reply.received_at,
    }


def create_reply_preview(
    sessions, token_id, payload, settings, registry, *, header_loader=None
):
    from .sending import SendStore, email_address
    from .identity import preview_mailbox
    from .templates import get_template, render_template
    from .reply_headers import recover_headers

    with sessions() as session:
        reply, source_send, source_preview = owned_reply(
            session, payload["reply_id"], token_id
        )
        if reply.kind != "human":
            raise ApiError(
                409,
                "reply_not_human",
                "Only human replies can be answered; delivery reports and automatic messages cannot be used.",
            )
        if payload["mailbox_id"] != source_preview.mailbox_id:
            raise ApiError(
                409,
                "reply_mailbox_mismatch",
                "Use the mailbox that received this reply.",
            )
        profile = preview_mailbox(session, source_preview, registry)
        cfg = registry.settings_for(profile.id)
        template_id = payload.get("template_id") or "custom-reply"
        check_reply_template(profile, template_id)
        if template_id == "custom-reply":
            message = {"text": payload["text"], "format": "plain_text"}
            version = "1"
        else:
            definition = get_template(template_id, payload["template_version"])
            if definition.get("purpose") != "reply":
                raise ApiError(
                    422, "reply_template_required", "Select a reply template."
                )
            message = render_template(definition, payload.get("variables", {}))
            version = definition["version"]
        stored = (reply.diagnostics or {}).get("thread_headers")
        context = source_context(session, reply, source_send, source_preview)
        original_id = (
            f'<fmg-{source_send.id}@{source_preview.message["from"].split("@", 1)[1]}>'
        )
    # Do not hold a DB transaction while fetching legacy headers.
    if stored is None:
        stored = (header_loader or recover_headers)(cfg, reply, original_id)
        with sessions() as session:
            current, _, _ = owned_reply(session, reply.id, token_id)
            current.diagnostics = {
                **(current.diagnostics or {}),
                "thread_headers": stored,
            }
            session.commit()
    if not valid_message_id(stored.get("message_id")):
        raise ApiError(
            409,
            "reply_message_id_missing",
            "The incoming message has no valid Message-ID; a threaded reply cannot be prepared.",
        )
    sender = email_address(reply.sender)
    alternatives = stored.get("reply_to") or []
    recipient = sender
    if payload.get("recipient_mode", "sender") == "reply_to":
        if stored.get("reply_to_invalid") or len(alternatives) != 1:
            raise ApiError(
                422,
                "reply_to_ambiguous",
                "Reply-To must contain exactly one valid address to select it.",
            )
        recipient = email_address(alternatives[0])
    context.update(
        original_message_id=stored["message_id"],
        reply_to=alternatives,
        reply_to_invalid=bool(stored.get("reply_to_invalid")),
        reply_to_differs=any(a.casefold() != sender.casefold() for a in alternatives),
        recipient_mode=payload.get("recipient_mode", "sender"),
    )
    message.update(
        {
            "from": profile.smtp_from,
            "from_name": profile.display_name,
            "to": recipient,
            "subject": reply_subject(reply.subject),
            "in_reply_to": stored["message_id"],
            "references": reply_references(stored),
            "reply_context": context,
        }
    )
    with sessions() as session:
        preview = EmailPreview(
            token_id=token_id,
            mailbox_id=profile.id,
            template_id=template_id,
            template_version=version,
            message=message,
        )
        session.add(preview)
        session.commit()
        preview_id = preview.id
    return SendStore(sessions).get_preview(
        preview_id, token_id, settings, registry=registry
    )


def history_query(token_id, task_id, creator_id=None):
    from .templates import REPLY_TEMPLATE_FILES

    context = EmailPreview.message["reply_context"]
    query = (
        select(EmailPreview, EmailSend)
        .join(EmailSend, EmailSend.preview_id == EmailPreview.id)
        .where(
            EmailPreview.token_id == token_id,
            EmailSend.token_id == token_id,
            EmailPreview.template_id.in_(["custom-reply", *REPLY_TEMPLATE_FILES]),
            context["task_id"].as_string() == task_id,
        )
    )
    if creator_id is not None:
        query = query.where(context["creator_id"].as_string() == creator_id)
    return query


def reply_history(
    sessions, token_id, task_id, *, creator_id=None, limit=10, cursor=None
):
    from ..outreach import owned
    from .sending import receipt, SendStore

    SendStore(sessions).recover_interrupted()
    with sessions() as session:
        owned(session, task_id, token_id)
        query = history_query(token_id, task_id, creator_id)
        if cursor:
            anchor = session.scalar(
                query.with_only_columns(EmailSend.created_at).where(
                    EmailSend.id == cursor
                )
            )
            if anchor is None:
                raise ApiError(
                    422,
                    "reply_history_cursor_invalid",
                    "Cursor does not belong to this reply history.",
                )
            query = query.where(
                (EmailSend.created_at > anchor)
                | ((EmailSend.created_at == anchor) & (EmailSend.id > cursor))
            )
        rows = session.execute(
            query.order_by(EmailSend.created_at, EmailSend.id).limit(limit + 1)
        ).all()
        items = []
        for preview, send in rows[:limit]:
            items.append(
                {
                    "preview_id": preview.id,
                    "mailbox_id": preview.mailbox_id,
                    "message": preview.message,
                    "receipt": receipt(send, preview),
                }
            )
        return {
            "items": items,
            "next_cursor": rows[limit - 1][1].id if len(rows) > limit else None,
        }


def history_summary(session, token_id, task_id):
    from urllib.parse import urlencode

    query = history_query(token_id, task_id).with_only_columns(EmailSend.id).subquery()
    count = session.scalar(select(func.count()).select_from(query))
    return {
        "outgoing_reply_count": count,
        "reply_history_url": "/v1/email/reply-history?"
        + urlencode({"task_id": task_id}),
    }
