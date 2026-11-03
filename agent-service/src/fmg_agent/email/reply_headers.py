"""Bounded, read-only recovery of headers for pre-feature inbox records."""

import imaplib
import ssl
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from hashlib import sha256
from time import monotonic

from ..errors import ApiError
from .inbox import monitored_folders, fetch_part, configured
from .microsoft import access_token, xoauth2
from .sent_copy import _quote
from .threading import read_thread_headers


def recover_headers(config, reply, original_message_id, *, connect=None):
    """Match the original stored message hash, not merely a sender/subject guess.

    Fetch headers only; no Seen flag, body fetch, SMTP or provider generation.
    Missing mail or an exhausted search budget stays unresolved.
    """
    client = None
    try:
        if not configured(config):
            raise ValueError()
        client = (connect or imaplib.IMAP4_SSL)(
            config.imap_host,
            config.imap_port,
            ssl_context=ssl.create_default_context(),
            timeout=5,
        )
        if config.imap_auth == "microsoft_oauth":
            sasl = xoauth2(
                config.imap_username, access_token(config, config.imap_username)
            ).encode()
            client.authenticate(
                "XOAUTH2", lambda challenge: sasl if not challenge else b""
            )
        else:
            client.login(config.imap_username, config.imap_password.get_secret_value())
        deadline, budget = monotonic() + 10, 100
        for folder in monitored_folders(client, config)[:8]:
            if monotonic() > deadline or budget <= 0:
                break
            if client.select(_quote(folder), readonly=True)[0] != "OK":
                continue
            status, rows = client.uid(
                "search",
                None,
                f"(OR HEADER In-Reply-To {_quote(original_message_id)} HEADER References {_quote(original_message_id)})",
            )
            if status != "OK":
                continue
            for uid in (rows[0] or b"").split()[-budget:][::-1]:
                if monotonic() > deadline or budget <= 0:
                    break
                budget -= 1
                raw = fetch_part(client, int(uid), "HEADER", 65536)
                if not raw:
                    continue
                message = BytesParser(policy=policy.default).parsebytes(raw)
                identity = str(message.get("Message-ID", ""))
                if (
                    not identity
                    or sha256(identity.encode()).hexdigest() != reply.message_key
                ):
                    continue
                sender = parseaddr(str(message.get("From", "")))[1].casefold()
                if sender != reply.sender.casefold():
                    continue
                return read_thread_headers(message)
    except Exception:
        # Never expose provider responses, passwords, or OAuth details.
        pass
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass
    raise ApiError(
        409,
        "reply_headers_unavailable",
        "Original reply headers could not be verified within the read-only lookup limit. No preview or send was created; ask an administrator to recover the original headers.",
    )
