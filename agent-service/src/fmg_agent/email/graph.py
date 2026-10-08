"""Delegated personal-account sendMail; never retry a possibly accepted POST."""

from base64 import b64encode
from email import policy

import httpx

from .microsoft import MailOAuthError, access_token
from .mime import build_message
from ..providers.logging import protect_http_logs


def deliver(config, message, message_id, *, transport=None):
    attempting_send = False
    try:
        if message["from"].casefold() != config.smtp_from.casefold():
            return {"state": "failed", "code": "sender_changed"}
        mime = build_message(message, message_id)
        token = access_token(config, config.smtp_from, profile="graph")
        body = b64encode(mime.as_bytes(policy=policy.SMTP))
        protect_http_logs()
        with httpx.Client(
            timeout=30, transport=transport, trust_env=False, follow_redirects=False
        ) as client:
            attempting_send = True
            response = client.post(
                "https://graph.microsoft.com/v1.0/me/sendMail",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "text/plain",
                },
                content=body,
            )
        if response.status_code == 202:
            # Accepted for processing, not proof of delivery to the inbox.
            return {"state": "sent", "code": None}
        if response.status_code >= 500 or response.status_code == 408:
            return {"state": "unknown", "code": "graph_confirmation_lost"}
        code = {
            401: "mail_oauth_authorization_required",
            403: "graph_send_access_denied",
            429: "graph_rate_limited",
        }.get(response.status_code, "graph_request_rejected")
        return {"state": "failed", "code": code}
    except MailOAuthError as exc:
        return {"state": "failed", "code": exc.code}
    except Exception:
        return {
            "state": "unknown" if attempting_send else "failed",
            "code": (
                "graph_confirmation_lost"
                if attempting_send
                else "graph_preparation_failed"
            ),
        }
