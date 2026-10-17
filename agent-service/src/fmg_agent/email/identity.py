"""Stable sender identities and atomic, verifiable historical association."""

from hashlib import sha256
import json

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from ..errors import ApiError
from .models import EmailPreview, EmailSend, MailboxIdentity


def normalized_sender(sender):
    from .sending import email_address

    return email_address(sender).casefold()


def _registrations(session, registry):
    stored = session.scalars(select(MailboxIdentity)).all()
    by_id = {row.id: row.sender for row in stored}
    by_sender = {row.sender: row.id for row in stored}
    additions = []
    for profile in registry.profiles():
        if not profile.smtp_from:
            if profile.enabled:
                from ..mailboxes import configuration_invalid

                raise configuration_invalid()
            continue
        sender = normalized_sender(profile.smtp_from)
        if (profile.id in by_id and by_id[profile.id] != sender) or (
            sender in by_sender and by_sender[sender] != profile.id
        ):
            raise ApiError(
                409,
                "mailbox_identity_conflict",
                "Mailbox identity cannot be reassigned.",
            )
        if profile.id not in by_id:
            additions.append(MailboxIdentity(id=profile.id, sender=sender))
        by_id[profile.id], by_sender[sender] = sender, profile.id
    return additions, by_sender


def register_identities(session, registry) -> None:
    additions, _ = _registrations(session, registry)
    if additions:
        try:
            with session.begin_nested():
                session.add_all(additions)
                session.flush()
        except IntegrityError:
            # A simultaneous request can register the same stable identity.
            remaining, _ = _registrations(session, registry)
            if remaining:
                raise


def preview_mailbox(session, preview, registry):
    if not preview.mailbox_id:
        raise ApiError(
            409,
            "mailbox_backfill_required",
            "Mailbox identity must be verified before sending.",
        )
    identity = session.get(MailboxIdentity, preview.mailbox_id)
    profile = registry.select(preview.mailbox_id, allow_legacy=False)
    try:
        matches = (
            identity is not None
            and identity.sender == normalized_sender(profile.smtp_from)
            and identity.sender == normalized_sender(preview.message.get("from"))
        )
    except ValueError:
        matches = False
    if not matches:
        raise ApiError(
            409,
            "mailbox_identity_conflict",
            "Frozen sender does not match its mailbox identity.",
        )
    # Legacy messages deliberately have no from_name; preserve their approval.
    if (
        "from_name" in preview.message
        and preview.message["from_name"] != profile.display_name
    ):
        raise ApiError(
            409,
            "mailbox_identity_conflict",
            "Frozen display name no longer matches this mailbox.",
        )
    return profile


def _snapshot(session):
    from ..outreach import OutreachTask

    tables = (OutreachTask.__table__, EmailPreview.__table__, EmailSend.__table__)
    digest = sha256()
    encoder = json.JSONEncoder(sort_keys=True, default=str)
    digest.update(b"[")
    for index, table in enumerate(tables):
        if index:
            digest.update(b", ")
        digest.update(b"[")
        columns = [column for column in table.columns if column.name != "mailbox_id"]
        # Server-side cursors keep large frozen image bodies out of aggregate RAM.
        rows = session.execute(
            select(*columns).order_by(table.c.id).execution_options(yield_per=1)
        )
        for number, row in enumerate(rows):
            if number:
                digest.update(b", ")
            for chunk in encoder.iterencode(list(row)):
                digest.update(chunk.encode())
        digest.update(b"]")
    digest.update(b"]")
    return digest.hexdigest()


def backfill_mailboxes(session, registry, *, apply: bool = False) -> dict:
    from ..outreach import OutreachTask, OutreachRecipient

    # Resolve every record and reject all ambiguity before making any writes.
    additions, by_sender = _registrations(session, registry)
    # Dry runs/readiness perform no frozen-data writes and need only identities.
    # Full-body before/after integrity is verified once during the locked apply.
    before = _snapshot(session) if apply else None
    json_type = (
        func.json_typeof
        if session.get_bind().dialect.name == "postgresql"
        else func.json_type
    )
    previews = session.execute(
        select(
            EmailPreview.id,
            EmailPreview.mailbox_id,
            EmailPreview.message["from"].as_string().label("sender"),
            json_type(EmailPreview.message).label("message_type"),
        )
    ).all()
    associated = set(session.scalars(select(EmailSend.preview_id))) | set(
        session.scalars(select(OutreachRecipient.preview_id))
    )
    preserved_unsendable = set()
    mapped = {}
    for preview in previews:
        if preview.message_type != "object":
            raise ValueError(f"unmapped preview sender: {preview.id}")
        # Early standalone previews could freeze a null/missing sender. Retain
        # them verbatim and unbound: preview_mailbox still refuses any send.
        # Never exempt a known identity, attempted send, or task association.
        if (
            preview.sender is None
            and preview.mailbox_id is None
            and preview.id not in associated
        ):
            preserved_unsendable.add(preview.id)
            continue
        try:
            identity = by_sender[normalized_sender(preview.sender)]
        except (ValueError, KeyError):
            raise ValueError(f"unmapped preview sender: {preview.id}") from None
        if preview.mailbox_id is not None and preview.mailbox_id != identity:
            raise ValueError(f"conflicting preview identity: {preview.id}")
        mapped[preview.id] = identity
    tasks = session.scalars(select(OutreachTask)).all()
    task_map = {}
    for task in tasks:
        ids = session.scalars(
            select(OutreachRecipient.preview_id).where(
                OutreachRecipient.task_id == task.id
            )
        ).all()
        identities = {mapped[preview_id] for preview_id in ids}
        if len(identities) != 1:
            raise ValueError(f"mixed or unmapped task sender: {task.id}")
        identity = identities.pop()
        if task.mailbox_id is not None and task.mailbox_id != identity:
            raise ValueError(f"conflicting task identity: {task.id}")
        task_map[task.id] = identity
    result = {
        "previews": sum(
            row.mailbox_id is None and row.id not in preserved_unsendable
            for row in previews
        ),
        "preserved_unsendable_previews": len(preserved_unsendable),
        "tasks": sum(row.mailbox_id is None for row in tasks),
        "unmapped": 0,
        "before": before,
        "after": before,
        "unchanged": True,
        "snapshot_verified": apply,
        "applied": apply,
    }
    if apply:
        with session.begin_nested():
            session.add_all(additions)
            session.flush()
            for preview in previews:
                if preview.id in mapped and preview.mailbox_id is None:
                    session.execute(
                        update(EmailPreview)
                        .where(EmailPreview.id == preview.id)
                        .values(mailbox_id=mapped[preview.id])
                    )
            for task in tasks:
                task.mailbox_id = task_map[task.id]
            session.flush()
            result["after"] = _snapshot(session)
            result["unchanged"] = result["after"] == before
            if not result["unchanged"]:
                raise ValueError("Frozen approval data changed during mailbox backfill")
    return result
