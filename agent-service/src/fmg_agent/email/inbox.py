"""Bounded read-only IMAP synchronization. Unrelated message bodies are not stored."""

from datetime import datetime, timezone, timedelta
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from hashlib import sha256
from html.parser import HTMLParser
import imaplib
import re
import ssl
from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base
from .models import EmailSend, EmailPreview


class EmailReply(Base):
    __tablename__ = "email_replies"
    __table_args__ = (UniqueConstraint("send_id", "message_key"),)
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    send_id: Mapped[str] = mapped_column(ForeignKey("email_sends.id"), index=True)
    message_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    sender: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[str] = mapped_column(String(40))


class InboxCursor(Base):
    __tablename__ = "inbox_cursors"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    uidvalidity: Mapped[str] = mapped_column(String(40), default="")
    last_uid: Mapped[int] = mapped_column(Integer, default=0)
    last_success: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(String(60))


def mailbox_key(settings):
    return sha256(
        f"{settings.imap_host}:{settings.imap_port}:{settings.imap_username}:{settings.imap_folder}".encode()
    ).hexdigest()


def configured(settings):
    return bool(
        settings.imap_host
        and settings.imap_username
        and settings.imap_password.get_secret_value()
    )


def monitoring_status(sessions, settings):
    if not configured(settings):
        return {"state": "not_configured", "last_success": None, "error": None}
    with sessions() as session:
        cursor = session.get(InboxCursor, mailbox_key(settings))
        if cursor is None:
            return {"state": "waiting", "last_success": None, "error": None}
        stale = not cursor.last_success or (
            datetime.now(timezone.utc) - datetime.fromisoformat(cursor.last_success)
        ).total_seconds() > max(180, settings.imap_poll_seconds * 3)
        return {
            "state": "error" if cursor.error else "stale" if stale else "active",
            "last_success": cursor.last_success,
            "error": cursor.error,
        }


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag in {"p", "br", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def matching_send(session, message):
    sender = parseaddr(str(message.get("From", "")))[1].casefold()
    refs = re.findall(r"<[^<>\s]+>", str(message.get("In-Reply-To", "")))
    refs += list(
        reversed(re.findall(r"<[^<>\s]+>", str(message.get("References", ""))))
    )
    bounce = any(
        p.get_content_type() == "message/delivery-status" for p in message.walk()
    )
    # Delivery reports often embed the original message headers rather than References.
    if bounce:
        for part in message.walk():
            if part is not message:
                refs += re.findall(r"<[^<>\s]+>", str(part.get("Message-ID", "")))
                if part.get_content_type() == "text/rfc822-headers":
                    original = BytesParser(policy=policy.default).parsebytes(
                        part.get_payload(decode=True) or b""
                    )
                    refs += re.findall(
                        r"<[^<>\s]+>", str(original.get("Message-ID", ""))
                    )
    kind = (
        "bounce"
        if bounce
        else (
            "automatic"
            if str(message.get("Auto-Submitted", "no")).lower() != "no"
            or str(message.get("Precedence", "")).lower() in {"bulk", "list", "junk"}
            else "human"
        )
    )
    for ref in refs:
        match = re.fullmatch(r"<fmg-([0-9a-f-]{36})@([^<>]+)>", ref, re.I)
        if not match:
            continue
        row = session.get(EmailSend, match[1])
        if row is None or row.state not in {"sent", "unknown", "sending"}:
            continue
        preview = session.get(EmailPreview, row.preview_id)
        expected = f'<fmg-{row.id}@{preview.message["from"].split("@", 1)[1]}>'
        if ref.casefold() != expected.casefold():
            continue
        if kind != "bounce" and sender != preview.message["to"].casefold():
            continue
        return row, kind, sender
    return None, kind, sender


def ingest(sessions, mailbox, validity, uid, raw):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    with sessions() as session:
        send, kind, sender = matching_send(session, message)
        if send is None:
            return "unmatched"
        identity = str(message.get("Message-ID", "")) or sha256(raw).hexdigest()
        key = sha256(identity.encode()).hexdigest()
        if session.scalar(
            select(EmailReply.id).where(
                EmailReply.send_id == send.id, EmailReply.message_key == key
            )
        ):
            return "duplicate"
        part = message.get_body(preferencelist=("plain", "html"))
        content = ""
        if part is not None:
            try:
                content = part.get_content(errors="replace")
            except LookupError:
                content = (part.get_payload(decode=True) or b"").decode(
                    "utf-8", errors="replace"
                )
            if not isinstance(content, str):
                content = ""
            if part.get_content_type() == "text/html":
                parser = PlainHTML()
                parser.feed(content)
                content = "".join(parser.parts)
        session.add(
            EmailReply(
                send_id=send.id,
                message_key=key,
                kind=kind,
                sender=sender[:254],
                subject=str(message.get("Subject", ""))[:2000],
                body=content[:50000],
                received_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return "duplicate"
        return kind


def fetch_part(client, uid, section, limit=65536):
    status, parts = client.uid("fetch", str(uid), f"(BODY.PEEK[{section}]<0.{limit}>)")
    if status != "OK":
        raise RuntimeError("fetch")
    return next(
        (p[1] for p in parts if isinstance(p, tuple) and isinstance(p[1], bytes)), None
    )


def read_reply(client, uid, header):
    """Fetch MIME headers and text only; never fetch attachment payloads or set Seen."""
    budget = [64]

    def read_part(headers, path, depth=0):
        message = BytesParser(policy=policy.default).parsebytes(headers)
        if depth > 8 or budget[0] <= 0:
            raise RuntimeError("mime_structure_limit")
        budget[0] -= 1
        typ = message.get_content_type()
        if message.get_content_disposition() == "attachment" and typ not in {
            "message/rfc822",
            "text/rfc822-headers",
        }:
            return None
        if typ.startswith("multipart/"):
            children = []
            for index in range(1, 65):
                childpath = f"{path}.{index}" if path else str(index)
                childheaders = fetch_part(client, uid, childpath + ".MIME", 16384)
                if childheaders is None:
                    break
                child = read_part(childheaders, childpath, depth + 1)
                if child is not None:
                    children.append(child)
            else:
                raise RuntimeError("mime_structure_limit")
            message.set_payload(children)
        elif typ == "message/rfc822":
            # A delivery report can quote original headers; body/attachments are unnecessary.
            original = fetch_part(client, uid, path + ".HEADER", 16384)
            message.set_payload(
                [BytesParser(policy=policy.default).parsebytes(original or b"")]
            )
        elif typ in {
            "text/plain",
            "text/html",
            "text/rfc822-headers",
            "message/delivery-status",
        }:
            body = fetch_part(client, uid, path or "TEXT")
            message = BytesParser(policy=policy.default).parsebytes(
                headers.rstrip(b"\r\n") + b"\r\n\r\n" + (body or b"")
            )
        else:
            return None
        return message

    message = read_part(header, "")
    return message.as_bytes() if message else header


def sync_once(sessions, settings, connect=None):
    if not configured(settings):
        return {"state": "not_configured"}
    key = mailbox_key(settings)
    with sessions() as session:
        if session.get(InboxCursor, key) is None:
            session.add(InboxCursor(id=key))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
    client = None
    try:
        factory = connect or imaplib.IMAP4_SSL
        client = factory(
            settings.imap_host,
            settings.imap_port,
            ssl_context=ssl.create_default_context(),
            timeout=20,
        )
        client.login(settings.imap_username, settings.imap_password.get_secret_value())
        if client.select(settings.imap_folder, readonly=True)[0] != "OK":
            raise RuntimeError("folder")
        validity = client.response("UIDVALIDITY")[1][0].decode()
        with sessions() as session:
            cursor = session.get(InboxCursor, key)
            last = cursor.last_uid if cursor.uidvalidity == validity else 0
            if cursor.uidvalidity != validity:
                cursor.uidvalidity = validity
                cursor.last_uid = 0
                session.commit()
        since = (
            datetime.now(timezone.utc) - timedelta(days=settings.imap_lookback_days)
        ).strftime("%d-%b-%Y")
        criteria = f"(UID {last+1}:*)" if last else f"(SINCE {since})"
        status, result = client.uid("search", None, criteria)
        if status != "OK":
            raise RuntimeError("search")
        uids = sorted(int(x) for x in result[0].split() if int(x) > last)[:100]
        for uid in uids:
            header = fetch_part(client, uid, "HEADER", 16384)
            if header is None:
                raise RuntimeError("fetch")
            message = BytesParser(policy=policy.default).parsebytes(header)
            with sessions() as session:
                match, _, _ = matching_send(session, message)
            if match is not None or message.get_content_type() == "multipart/report":
                ingest(sessions, key, validity, uid, read_reply(client, uid, header))
            with sessions() as session:
                cursor = session.get(InboxCursor, key)
                cursor.uidvalidity = validity
                cursor.last_uid = uid
                session.commit()
        with sessions() as session:
            cursor = session.get(InboxCursor, key)
            cursor.uidvalidity = validity
            cursor.last_success = datetime.now(timezone.utc).isoformat()
            cursor.error = None
            session.commit()
        return {"state": "active", "processed": len(uids)}
    except Exception as exc:
        code = (
            "imap_auth_or_protocol_error"
            if isinstance(exc, imaplib.IMAP4.error)
            else (
                "imap_message_too_large"
                if str(exc) == "message_too_large"
                else "imap_sync_failed"
            )
        )
        with sessions() as session:
            cursor = session.get(InboxCursor, key)
            cursor.error = code
            session.commit()
        return {"state": "error", "error": code}
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass
