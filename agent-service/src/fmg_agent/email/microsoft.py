"""Delegated Microsoft consumer-mail OAuth; private, shared refresh-token storage.

SMTP and IMAP processes lock the same mounted file before refreshing. Rotated
refresh tokens are saved atomically before use. No tokens reach API responses.
"""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import smtplib
import tempfile
import time
from uuid import UUID

import httpx

from ..providers.logging import protect_http_logs

AUTHORITY = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
SCOPES = (
    "https://outlook.office.com/IMAP.AccessAsUser.All "
    "https://outlook.office.com/SMTP.Send offline_access"
)
GRAPH_SCOPES = "https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read offline_access"
GRAPH_ME = "https://graph.microsoft.com/v1.0/me?$select=id,mail,userPrincipalName"


class MailOAuthError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def client_id(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise MailOAuthError("mail_oauth_configuration_missing") from None


def token_path(settings, profile):
    if profile == "graph":
        path = settings.microsoft_graph_token_store
        if (
            path is not None
            and settings.microsoft_token_store is not None
            and path.resolve() == settings.microsoft_token_store.resolve()
        ):
            raise MailOAuthError("mail_oauth_store_invalid")
        return path
    if profile != "outlook":
        raise MailOAuthError("mail_oauth_configuration_missing")
    return settings.microsoft_token_store


def ready(settings, profile="outlook"):
    try:
        client_id(settings.microsoft_client_id)
        path = token_path(settings, profile)
        if path is None or not path.is_absolute() or not path.is_file():
            return False
        if profile == "graph":
            read_store(
                path, settings.microsoft_client_id, settings.smtp_from, profile=profile
            )
        return True
    except (MailOAuthError, OSError):
        return False


def xoauth2(username, token):
    if any(char in username + token for char in "\r\n\x01"):
        raise MailOAuthError("mail_oauth_store_invalid")
    return f"user={username}\x01auth=Bearer {token}\x01\x01"


def authenticate_smtp(connection, mailbox, token):
    """STARTTLS resets EHLO; smtplib.auth accepts 503, which is unsafe here."""
    if connection.ehlo()[0] != 250:
        raise MailOAuthError("smtp_greeting_rejected")
    sasl = xoauth2(mailbox, token)
    try:
        code, _ = connection.auth(
            "XOAUTH2", lambda challenge=None: sasl if challenge is None else ""
        )
    except smtplib.SMTPAuthenticationError as exc:
        if b"smtpclientauthentication is disabled" in exc.smtp_error.lower():
            raise MailOAuthError("smtp_mailbox_auth_disabled") from None
        raise MailOAuthError("smtp_authentication_rejected") from None
    if code != 235:
        raise MailOAuthError("smtp_authentication_rejected")


@contextmanager
def store_lock(path):
    """Parent is provisioned by the administrator, not created in containers."""
    try:
        if not path.is_absolute() or not path.parent.is_dir():
            raise OSError()
        fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    except OSError:
        raise MailOAuthError("mail_oauth_store_invalid") from None


def read_store(path, app_id, mailbox, profile="outlook"):
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError()
        data = json.loads(path.read_text())
        if data.get("profile", "outlook") != profile:
            raise ValueError()
        if profile == "graph" and not data.get("account_id"):
            raise ValueError()
        if (
            data["client_id"] != app_id
            or data["mailbox"].casefold() != mailbox.casefold()
            or not isinstance(data["refresh_token"], str)
            or not data["refresh_token"]
        ):
            raise ValueError()
        return data
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise MailOAuthError("mail_oauth_authorization_required") from None


def persist(path, data):
    name = None
    try:
        fd, name = tempfile.mkstemp(prefix=".microsoft-", dir=path.parent)
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        raise MailOAuthError("mail_oauth_store_invalid") from None
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def token_data(response, app_id, mailbox, old_refresh=None, profile="outlook"):
    try:
        data = response.json()
        access = data["access_token"]
        refresh = data.get("refresh_token", old_refresh)
        expires = int(data["expires_in"])
        if (
            not isinstance(access, str)
            or not access
            or not isinstance(refresh, str)
            or not refresh
            or expires <= 60
        ):
            raise ValueError()
        xoauth2(mailbox, access)
        if profile == "graph":
            granted = {
                scope.rsplit("/", 1)[-1].casefold()
                for scope in data.get("scope", "").split()
            }
            if not {"mail.send", "user.read"}.issubset(granted):
                raise ValueError()
        return {
            "client_id": app_id,
            "mailbox": mailbox,
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": time.time() + expires,
            "profile": profile,
        }
    except (ValueError, KeyError, TypeError):
        raise MailOAuthError("mail_oauth_invalid_response") from None


def verify_graph_identity(client, token, mailbox):
    """Do not trust the mailbox label supplied to device enrollment."""
    response = client.get(GRAPH_ME, headers={"Authorization": f"Bearer {token}"})
    if response.status_code != 200:
        raise MailOAuthError("mail_oauth_identity_verification_failed")
    try:
        data = response.json()
        actual = data.get("mail") or data.get("userPrincipalName")
        if not isinstance(actual, str) or actual.casefold() != mailbox.casefold():
            raise MailOAuthError("mail_oauth_mailbox_mismatch")
        if not isinstance(data["id"], str) or not data["id"]:
            raise ValueError()
        return data["id"]
    except (ValueError, KeyError, TypeError):
        raise MailOAuthError("mail_oauth_invalid_response") from None


def access_token(settings, mailbox, *, transport=None, profile="outlook"):
    app_id = client_id(settings.microsoft_client_id)
    path = token_path(settings, profile)
    if path is None:
        raise MailOAuthError("mail_oauth_configuration_missing")
    protect_http_logs()
    with store_lock(path):
        saved = read_store(path, app_id, mailbox, profile=profile)
        try:
            if (
                isinstance(saved.get("access_token"), str)
                and saved["access_token"]
                and float(saved.get("expires_at", 0)) > time.time() + 120
            ):
                return saved["access_token"]
        except (ValueError, TypeError):
            raise MailOAuthError("mail_oauth_store_invalid") from None
        try:
            with httpx.Client(
                timeout=20, transport=transport, follow_redirects=False, trust_env=False
            ) as client:
                response = client.post(
                    AUTHORITY + "/token",
                    data={
                        "client_id": app_id,
                        "grant_type": "refresh_token",
                        "refresh_token": saved["refresh_token"],
                        "scope": GRAPH_SCOPES if profile == "graph" else SCOPES,
                    },
                )
                if response.status_code in {400, 401, 403}:
                    raise MailOAuthError("mail_oauth_authorization_required")
                if response.status_code != 200:
                    raise MailOAuthError("mail_oauth_unavailable")
                updated = token_data(
                    response, app_id, mailbox, saved["refresh_token"], profile=profile
                )
                if profile == "graph":
                    updated["account_id"] = verify_graph_identity(
                        client, updated["access_token"], mailbox
                    )
                    if updated["account_id"] != saved["account_id"]:
                        raise MailOAuthError("mail_oauth_mailbox_mismatch")
            persist(path, updated)
            return updated["access_token"]
        except httpx.HTTPError:
            raise MailOAuthError("mail_oauth_unavailable") from None
