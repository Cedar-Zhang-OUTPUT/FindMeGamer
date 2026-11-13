"""Bounded, read-only access to the configured IMAP Inbox and Sent folders.

UID windows deliberately allow sparse/empty pages: never download an entire
mailbox's UID list just to paginate. Cursor identities include UIDVALIDITY.
"""

import hashlib
import imaplib
import re
import ssl
from threading import BoundedSemaphore
from email import policy
from email.parser import BytesParser

from ..errors import ApiError
from .sent_copy import _quote

HEADER_LIMIT = 4096
BODY_LIMIT = 131072
# Leave API threads available for task/receipt/send operations during slow IMAP.
_READ_SLOTS = BoundedSemaphore(2)


def _error(kind, code="read_failed", status=502):
    return ApiError(
        status,
        f"{kind}_{code}",
        f"Could not read the {kind.title()} folder; no email was sent or changed.",
        retryable=code in {"read_failed", "read_busy"},
        retry_after_seconds=2 if code == "read_busy" else None,
    )


def _number(client, name, kind):
    _, values = client.response(name)
    if not values or not values[0] or not values[0].isdigit():
        raise _error(kind)
    return int(values[0])


def _identity(mailbox_id, folder, account=""):
    return hashlib.sha256(f"{mailbox_id}\0{folder}\0{account}".encode()).hexdigest()[
        :16
    ]


def _decode(value, identity, validity, kind):
    parts = value.split(":")
    if (
        len(parts) != 3
        or parts[0] != identity
        or not all(re.fullmatch(r"[1-9][0-9]{0,9}", p) for p in parts[1:])
    ):
        raise _error(kind, "reference_invalid", 422)
    if int(parts[1]) != validity:
        raise _error(kind, "folder_changed", 409)
    return int(parts[2])


def _records(data, prefix, kind, *, full=False):
    records = []
    for item in data or []:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        metadata, raw = item
        uid = re.search(rb"\bUID (\d+)\b", metadata)
        size = re.search(rb"\bRFC822.SIZE (\d+)\b", metadata)
        if not uid or not size or not isinstance(raw, bytes):
            raise _error(kind)
        message = BytesParser(policy=policy.default).parsebytes(raw)
        header_names = (
            "From",
            "To",
            "Cc",
            "Bcc",
            "Subject",
            "Date",
            "Message-ID",
            "In-Reply-To",
            "Reply-To",
            "References",
        )
        headers = {name: str(message.get(name, "")) for name in header_names}
        record = {
            "id": f"{prefix}:{int(uid[1])}",
            "uid": int(uid[1]),
            "size": int(size[1]),
            "headers": {name: value[:2000] for name, value in headers.items()},
            "headers_truncated": any(len(value) > 2000 for value in headers.values())
            or (not full and len(raw) >= HEADER_LIMIT),
        }
        if full:
            record["body_omitted"] = int(size[1]) > len(raw)
            record["text"] = None
            record["html"] = None
            if not record["body_omitted"]:
                for body_kind in ("plain", "html"):
                    part = message.get_body(preferencelist=(body_kind,))
                    if part is not None:
                        content = part.get_content()
                        record["text" if body_kind == "plain" else "html"] = (
                            content[:BODY_LIMIT] if isinstance(content, str) else None
                        )
        records.append(record)
    return sorted(records, key=lambda r: r["uid"], reverse=True)


def read_folder(
    settings, mailbox_id, kind, *, limit=20, cursor=None, message_id=None, connect=None
):
    if kind not in {"inbox", "sent"}:
        raise ValueError("Only Inbox and Sent reads are supported")
    folder_name = settings.imap_folder if kind == "inbox" else settings.imap_sent_folder
    if cursor and message_id:
        raise _error(kind, "reference_invalid", 422)
    if not 1 <= limit <= 50:
        raise _error(kind, "reference_invalid", 422)
    if (
        not settings.imap_host
        or not settings.imap_username
        or settings.imap_username.casefold() != settings.smtp_from.casefold()
    ):
        raise _error(kind, "not_configured", 503)
    if (
        settings.imap_auth != "password"
        or not settings.imap_password.get_secret_value()
    ):
        raise _error(kind, "auth_not_configured", 503)
    if not _READ_SLOTS.acquire(blocking=False):
        raise _error(kind, "read_busy", 503)
    client = None
    try:
        folder = _quote(folder_name)
        identity = _identity(
            mailbox_id,
            folder_name,
            f"{settings.imap_host.lower()}:{settings.imap_port}:{settings.imap_username.casefold()}",
        )
        client = (connect or imaplib.IMAP4_SSL)(
            settings.imap_host,
            settings.imap_port,
            ssl_context=ssl.create_default_context(),
            timeout=10,
        )
        try:
            client.login(
                settings.imap_username, settings.imap_password.get_secret_value()
            )
        except imaplib.IMAP4.error:
            raise _error(kind, "auth_failed", 503) from None
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            raise _error(kind, "folder_unavailable", 503)
        validity = _number(client, "UIDVALIDITY", kind)
        uidnext = _number(client, "UIDNEXT", kind)
        prefix = f"{identity}:{validity}"
        if message_id:
            uid = _decode(message_id, identity, validity, kind)
            if uid >= uidnext:
                raise _error(kind, "message_not_found", 404)
            status, data = client.uid(
                "FETCH", str(uid), f"(UID RFC822.SIZE BODY.PEEK[]<0.{BODY_LIMIT}>)"
            )
            if status != "OK":
                raise _error(kind)
            records = [
                r for r in _records(data, prefix, kind, full=True) if r["uid"] == uid
            ]
            if not records:
                raise _error(kind, "message_not_found", 404)
            return {
                "mailbox_id": mailbox_id,
                "folder": folder_name,
                "message": records[0],
            }
        before = _decode(cursor, identity, validity, kind) if cursor else uidnext
        if before > uidnext:
            raise _error(kind, "reference_invalid", 422)
        low, high = max(1, before - limit), before - 1
        records = []
        if high >= low:
            status, data = client.uid(
                "FETCH",
                f"{low}:{high}",
                f"(UID RFC822.SIZE BODY.PEEK[HEADER]<0.{HEADER_LIMIT}>)",
            )
            if status != "OK":
                raise _error(kind)
            records = [
                r for r in _records(data, prefix, kind) if low <= r["uid"] <= high
            ]
        return {
            "mailbox_id": mailbox_id,
            "folder": folder_name,
            "messages": records,
            "next_cursor": f"{prefix}:{low}" if low > 1 else None,
            "uidvalidity": validity,
        }
    except ApiError:
        raise
    except (OSError, imaplib.IMAP4.error, ValueError, TypeError, LookupError):
        raise _error(kind) from None
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass
        _READ_SLOTS.release()


def read_inbox(settings, mailbox_id, **kwargs):
    return read_folder(settings, mailbox_id, "inbox", **kwargs)
