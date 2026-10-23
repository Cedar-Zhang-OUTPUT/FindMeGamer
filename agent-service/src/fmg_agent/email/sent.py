"""Bounded, read-only access to the configured IMAP Sent folder.

UID windows deliberately allow sparse/empty pages: never download an entire
mailbox's UID list just to paginate. Cursor identities include UIDVALIDITY.
"""

import hashlib
import imaplib
import re
import ssl
from email import policy
from email.parser import BytesParser

from ..errors import ApiError
from .sent_copy import _quote

HEADER_LIMIT = 4096
BODY_LIMIT = 131072


def _error(code="sent_read_failed", status=502):
    return ApiError(
        status,
        code,
        "Could not read the Sent folder; no email was sent or changed.",
        retryable=code == "sent_read_failed",
    )


def _number(client, name):
    _, values = client.response(name)
    if not values or not values[0] or not values[0].isdigit():
        raise _error()
    return int(values[0])


def _identity(mailbox_id, folder, account=""):
    return hashlib.sha256(f"{mailbox_id}\0{folder}\0{account}".encode()).hexdigest()[
        :16
    ]


def _decode(value, identity, validity):
    parts = value.split(":")
    if (
        len(parts) != 3
        or parts[0] != identity
        or not all(re.fullmatch(r"[1-9][0-9]{0,9}", p) for p in parts[1:])
    ):
        raise _error("sent_reference_invalid", 422)
    if int(parts[1]) != validity:
        raise _error("sent_folder_changed", 409)
    return int(parts[2])


def _records(data, prefix, *, full=False):
    records = []
    for item in data or []:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        metadata, raw = item
        uid = re.search(rb"\bUID (\d+)\b", metadata)
        size = re.search(rb"\bRFC822.SIZE (\d+)\b", metadata)
        if not uid or not size or not isinstance(raw, bytes):
            raise _error()
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
                for kind in ("plain", "html"):
                    part = message.get_body(preferencelist=(kind,))
                    if part is not None:
                        content = part.get_content()
                        record["text" if kind == "plain" else "html"] = (
                            content[:BODY_LIMIT] if isinstance(content, str) else None
                        )
        records.append(record)
    return sorted(records, key=lambda r: r["uid"], reverse=True)


def read_sent(
    settings, mailbox_id, *, limit=20, cursor=None, message_id=None, connect=None
):
    if not 1 <= limit <= 50:
        raise _error("sent_reference_invalid", 422)
    if (
        not settings.imap_host
        or not settings.imap_username
        or settings.imap_username.casefold() != settings.smtp_from.casefold()
    ):
        raise _error("sent_not_configured", 503)
    if (
        settings.imap_auth != "password"
        or not settings.imap_password.get_secret_value()
    ):
        raise _error("sent_auth_not_configured", 503)
    client = None
    try:
        folder = _quote(settings.imap_sent_folder)
        identity = _identity(
            mailbox_id,
            settings.imap_sent_folder,
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
            raise _error("sent_auth_failed", 503) from None
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            raise _error("sent_folder_unavailable", 503)
        validity = _number(client, "UIDVALIDITY")
        uidnext = _number(client, "UIDNEXT")
        prefix = f"{identity}:{validity}"
        if message_id:
            uid = _decode(message_id, identity, validity)
            if uid >= uidnext:
                raise _error("sent_message_not_found", 404)
            status, data = client.uid(
                "FETCH", str(uid), f"(UID RFC822.SIZE BODY.PEEK[]<0.{BODY_LIMIT}>)"
            )
            if status != "OK":
                raise _error()
            records = [r for r in _records(data, prefix, full=True) if r["uid"] == uid]
            if not records:
                raise _error("sent_message_not_found", 404)
            return {
                "mailbox_id": mailbox_id,
                "folder": settings.imap_sent_folder,
                "message": records[0],
            }
        before = _decode(cursor, identity, validity) if cursor else uidnext
        if before > uidnext:
            raise _error("sent_reference_invalid", 422)
        low, high = max(1, before - limit), before - 1
        records = []
        if high >= low:
            status, data = client.uid(
                "FETCH",
                f"{low}:{high}",
                f"(UID RFC822.SIZE BODY.PEEK[HEADER]<0.{HEADER_LIMIT}>)",
            )
            if status != "OK":
                raise _error()
            records = [r for r in _records(data, prefix) if low <= r["uid"] <= high]
        return {
            "mailbox_id": mailbox_id,
            "folder": settings.imap_sent_folder,
            "messages": records,
            "next_cursor": f"{prefix}:{low}" if low > 1 else None,
            "uidvalidity": validity,
        }
    except ApiError:
        raise
    except (OSError, imaplib.IMAP4.error, ValueError, TypeError, LookupError):
        raise _error() from None
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass
