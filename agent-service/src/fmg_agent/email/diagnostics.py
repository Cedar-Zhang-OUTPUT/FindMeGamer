"""Bounded, allowlisted Graph diagnostics; never retain a raw provider response."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import logging
import math
import re
from uuid import UUID

logger = logging.getLogger(__name__)

# Fail closed: even fields named "code" can contain echoed request data.
# Extend reviewed identifiers as needed; unknowns remain correlatable by hash/ID.
SAFE_CODES = frozenset(
    {
        "TooManyRequests",
        "ErrorThrottled",
        "MailSubmissionThrottled",
        "ErrorQuotaExceeded",
        "ErrorLimitExceeded",
        "ErrorExceededMessageLimit",
        "ErrorMessageSubmissionBlocked",
        "ErrorAccessDenied",
        "ErrorSendAsDenied",
        "ErrorInvalidRecipients",
        "ErrorInvalidRequest",
        "ErrorInternalServerError",
        "ErrorServerBusy",
        "ErrorMailboxStoreUnavailable",
        "MailboxNotEnabledForRESTAPI",
        "InvalidAuthenticationToken",
        "InvalidRequest",
        "BadRequest",
        "AccessDenied",
        "Authorization_RequestDenied",
        "AuthenticationError",
        "ServiceUnavailable",
        "GeneralException",
        "ResourceNotFound",
        "ErrorItemNotFound",
    }
)
SAFE_MESSAGES = frozenset(
    {
        "Mailbox send limit exceeded.",
        "Please retry again later.",
        "Please retry after",
        "Too many requests.",
        "Too Many Requests",
        "Too many requests. Please retry later.",
        "Mailbox is busy.",
        "Access is denied. Check credentials and try again.",
    }
)


def identifier(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def error_code(value):
    if isinstance(value, str) and (
        value in SAFE_CODES or re.fullmatch(r"[1-5][0-9]{2}", value)
    ):
        return value
    return None


def code_fingerprint(value):
    if isinstance(value, str) and len(value) <= 100 and error_code(value) is None:
        try:
            return sha256(value.encode()).hexdigest()
        except UnicodeEncodeError:
            # Malformed provider Unicode must not change the delivery outcome.
            return None
    return None


def http_date(value):
    if not isinstance(value, str) or len(value) > 100:
        return None
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is not None:
            return date.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def safe_message(value):
    if not isinstance(value, str):
        return None, False
    if value in SAFE_MESSAGES:
        return value, False
    return "[withheld provider message]", True


def graph_response(response, client_request_id):
    error = {}
    # Do not JSON-decode unbounded/HTML bodies. Only selected Graph fields escape.
    if len(response.content) <= 65536:
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                error = body["error"]
        except (ValueError, RecursionError):
            pass
    inner = error.get("innerError", error.get("innererror", {}))
    if not isinstance(inner, dict):
        inner = {}
    observed = datetime.now(timezone.utc)
    date = http_date(response.headers.get("date"))
    retry = response.headers.get("retry-after")
    retry_seconds = None
    if isinstance(retry, str) and re.fullmatch(r"[0-9]{1,10}", retry.strip()):
        retry_seconds = int(retry.strip())
    elif retry_date := http_date(retry):
        retry_seconds = max(
            0, math.ceil((retry_date - (date or observed)).total_seconds())
        )
    prose, redacted = safe_message(error.get("message"))
    details = {
        "provider": "microsoft_graph",
        "http_status": response.status_code,
        "provider_error_code": error_code(error.get("code")),
        "inner_error_code": error_code(inner.get("code")),
        "provider_error_code_sha256": code_fingerprint(error.get("code")),
        "inner_error_code_sha256": code_fingerprint(inner.get("code")),
        "provider_message": prose,
        "message_redacted": redacted,
        "retry_after_seconds": retry_seconds,
        "request_id": identifier(response.headers.get("request-id"))
        or identifier(inner.get("request-id")),
        "client_request_id": client_request_id,
        "response_date": date.isoformat() if date else None,
        "observed_at": observed.isoformat(),
    }
    # Logs deliberately omit even sanitized prose. Receipt data is owner-scoped.
    metadata = {k: v for k, v in details.items() if k != "provider_message"}
    logger.warning("graph_mail_response %s", json.dumps(metadata, sort_keys=True))
    return details
