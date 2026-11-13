"""Compatibility entrypoint for bounded, read-only IMAP Sent access."""

from .folders import BODY_LIMIT, HEADER_LIMIT, _identity, read_folder


def read_sent(
    settings, mailbox_id, *, limit=20, cursor=None, message_id=None, connect=None
):
    return read_folder(
        settings,
        mailbox_id,
        "sent",
        limit=limit,
        cursor=cursor,
        message_id=message_id,
        connect=connect,
    )
