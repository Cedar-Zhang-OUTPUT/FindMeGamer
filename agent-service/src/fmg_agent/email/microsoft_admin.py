"""Administrator-only device enrollment and connection checks; never sends mail.

Run inside the service image or its Python environment, not through a public API.
Device codes/refresh tokens are stored only in a private administrator directory.
"""

import argparse
import imaplib
import json
from pathlib import Path
import smtplib
import ssl
import time

import httpx

from .microsoft import (
    AUTHORITY,
    SCOPES,
    MailOAuthError,
    access_token,
    client_id,
    persist,
    store_lock,
    token_data,
    xoauth2,
)
from .sending import email_address
from ..config import Settings
from ..providers.logging import protect_http_logs


def probe(mailbox, token):
    """Authenticate both protocols without SMTP MAIL/DATA or IMAP message reads."""
    sasl = xoauth2(mailbox, token)
    try:
        with smtplib.SMTP("smtp-mail.outlook.com", 587, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.auth(
                "XOAUTH2", lambda challenge=None: sasl if challenge is None else ""
            )
    except (OSError, smtplib.SMTPException):
        raise MailOAuthError("microsoft_smtp_probe_failed") from None
    imap = None
    try:
        imap = imaplib.IMAP4_SSL(
            "outlook.office365.com",
            993,
            ssl_context=ssl.create_default_context(),
            timeout=20,
        )
        imap.authenticate(
            "XOAUTH2", lambda challenge: sasl.encode() if not challenge else b""
        )
        if imap.select("INBOX", readonly=True)[0] != "OK":
            raise imaplib.IMAP4.error()
    except (OSError, imaplib.IMAP4.error):
        raise MailOAuthError("microsoft_imap_probe_failed") from None
    finally:
        if imap:
            try:
                imap.logout()
            except Exception:
                pass


def authorize(args, client):
    app_id = client_id(args.client_id)
    mailbox = email_address(args.mailbox).casefold()
    response = client.post(
        AUTHORITY + "/devicecode",
        data={
            "client_id": app_id,
            "scope": SCOPES,
        },
    )
    if response.status_code != 200:
        raise MailOAuthError("mail_oauth_app_registration_required")
    try:
        data = response.json()
        # Do not print Microsoft's response message (it can contain dynamic text).
        result = {
            "verification_uri": data["verification_uri"],
            "user_code": data["user_code"],
            "mailbox": mailbox,
            "expires_in": int(data["expires_in"]),
        }
        if result["verification_uri"] not in {
            "https://microsoft.com/devicelogin",
            "https://www.microsoft.com/link",
        }:
            raise ValueError()
        pending = {
            "client_id": app_id,
            "mailbox": mailbox,
            "device_code": data["device_code"],
            "expires_at": time.time() + result["expires_in"],
            "interval": int(data.get("interval", 5)),
            "next_poll_at": 0,
        }
    except (ValueError, KeyError, TypeError):
        raise MailOAuthError("mail_oauth_invalid_response") from None
    with store_lock(args.store):
        persist(Path(str(args.store) + ".pending"), pending)
    print(json.dumps(result))
    return 0


def complete(args, client):
    pending_path = Path(str(args.store) + ".pending")
    with store_lock(args.store):
        try:
            if pending_path.stat().st_mode & 0o077:
                raise ValueError()
            pending = json.loads(pending_path.read_text())
            if pending["expires_at"] <= time.time():
                raise ValueError()
            if pending["next_poll_at"] > time.time():
                print(
                    json.dumps(
                        {"state": "waiting", "retry_after_seconds": pending["interval"]}
                    )
                )
                return 3
        except (OSError, ValueError, TypeError, KeyError):
            raise MailOAuthError("mail_oauth_restart_authorization") from None
        response = client.post(
            AUTHORITY + "/token",
            data={
                "client_id": pending["client_id"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": pending["device_code"],
            },
        )
        if response.status_code == 400:
            error = response.json().get("error")
            if error in {"authorization_pending", "slow_down"}:
                if error == "slow_down":
                    pending["interval"] += 5
                pending["next_poll_at"] = time.time() + pending["interval"]
                persist(pending_path, pending)
                print(
                    json.dumps(
                        {"state": "waiting", "retry_after_seconds": pending["interval"]}
                    )
                )
                return 3
        if response.status_code != 200:
            raise MailOAuthError("mail_oauth_authorization_required")
        data = token_data(response, pending["client_id"], pending["mailbox"])
        # Save refreshed authorization even if a protocol probe needs repair.
        # A successful probe is required separately before production activation.
        persist(args.store, data)
        pending_path.unlink()
    probe(data["mailbox"], data["access_token"])
    print(
        json.dumps(
            {
                "state": "authorized",
                "mailbox": data["mailbox"],
                "smtp": "ok",
                "imap": "ok",
                "sent": 0,
            }
        )
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("authorize", "complete", "probe"):
        sub = commands.add_parser(command)
        sub.add_argument("--store", required=True, type=Path)
        if command == "authorize":
            sub.add_argument("--client-id", required=True)
            sub.add_argument("--mailbox", required=True)
    args = parser.parse_args()
    protect_http_logs()
    try:
        with httpx.Client(
            timeout=25, follow_redirects=False, trust_env=False
        ) as client:
            if args.command == "authorize":
                return authorize(args, client)
            if args.command == "complete":
                return complete(args, client)
        # Load service settings only for an existing server-side enrollment.
        settings = Settings()
        if args.store != settings.microsoft_token_store:
            raise MailOAuthError("mail_oauth_configuration_missing")
        probe(settings.smtp_username, access_token(settings, settings.smtp_username))
        print(json.dumps({"smtp": "ok", "imap": "ok", "sent": 0}))
        return 0
    except MailOAuthError as exc:
        print(json.dumps({"state": "error", "code": exc.code}))
        return 2
    except (httpx.HTTPError, ValueError, OSError):
        print(json.dumps({"state": "error", "code": "mail_oauth_unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
