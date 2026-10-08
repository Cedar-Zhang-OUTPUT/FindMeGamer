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


class MailOAuthError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def client_id(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise MailOAuthError("mail_oauth_configuration_missing") from None


def ready(settings):
    try:
        client_id(settings.microsoft_client_id)
        path = settings.microsoft_token_store
        return path is not None and path.is_absolute() and path.is_file()
    except (MailOAuthError, OSError):
        return False


def xoauth2(username, token):
    if any(char in username + token for char in "\r\n\x01"):
        raise MailOAuthError("mail_oauth_store_invalid")
    return f"user={username}\x01auth=Bearer {token}\x01\x01"


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


def read_store(path, app_id, mailbox):
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError()
        data = json.loads(path.read_text())
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


def token_data(response, app_id, mailbox, old_refresh=None):
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
        return {
            "client_id": app_id,
            "mailbox": mailbox,
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": time.time() + expires,
        }
    except (ValueError, KeyError, TypeError):
        raise MailOAuthError("mail_oauth_invalid_response") from None


def access_token(settings, mailbox, *, transport=None):
    app_id = client_id(settings.microsoft_client_id)
    path = settings.microsoft_token_store
    if path is None:
        raise MailOAuthError("mail_oauth_configuration_missing")
    protect_http_logs()
    with store_lock(path):
        saved = read_store(path, app_id, mailbox)
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
                        "scope": SCOPES,
                    },
                )
            if response.status_code in {400, 401, 403}:
                raise MailOAuthError("mail_oauth_authorization_required")
            if response.status_code != 200:
                raise MailOAuthError("mail_oauth_unavailable")
            updated = token_data(response, app_id, mailbox, saved["refresh_token"])
            persist(path, updated)
            return updated["access_token"]
        except httpx.HTTPError:
            raise MailOAuthError("mail_oauth_unavailable") from None
