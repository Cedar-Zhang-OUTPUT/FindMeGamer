import json
import time
from pathlib import Path
from threading import Thread

import httpx
import pytest

from fmg_agent.config import Settings
from fmg_agent.email import microsoft as oauth

APP_ID = "0d4ce688-3a3f-4efc-83b3-08fb88ce58c4"
MAILBOX = "sender@hotmail.com"


def config(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'mail.sqlite'}",
        microsoft_client_id=APP_ID,
        microsoft_token_store=tmp_path / "tokens.json",
        smtp_auth="microsoft_oauth",
        imap_auth="microsoft_oauth",
        smtp_host="smtp-mail.outlook.com",
        smtp_port=587,
        smtp_encryption="starttls",
        smtp_username=MAILBOX,
        smtp_from=MAILBOX,
        imap_host="outlook.office365.com",
        imap_username=MAILBOX,
    )


def seed(settings, expires=0):
    oauth.persist(
        settings.microsoft_token_store,
        {
            "client_id": APP_ID,
            "mailbox": MAILBOX,
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_at": expires,
        },
    )


def test_concurrent_refresh_rotates_once_and_persists_privately(tmp_path):
    settings = config(tmp_path)
    seed(settings)
    calls = []

    def refresh(request):
        calls.append(request)
        assert request.url == oauth.AUTHORITY + "/token"
        assert b"old-refresh" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        )

    results = []
    transport = httpx.MockTransport(refresh)
    threads = [
        Thread(
            target=lambda: results.append(
                oauth.access_token(settings, MAILBOX, transport=transport)
            )
        )
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert results == ["new-access"] * 4
    assert len(calls) == 1
    assert (
        json.loads(settings.microsoft_token_store.read_text())["refresh_token"]
        == "new-refresh"
    )
    assert settings.microsoft_token_store.stat().st_mode & 0o777 == 0o600


def test_wrong_mailbox_and_public_store_rejected_before_network(tmp_path):
    settings = config(tmp_path)
    seed(settings, time.time() + 3600)
    with pytest.raises(oauth.MailOAuthError, match="authorization_required"):
        oauth.access_token(settings, "wrong@hotmail.com")
    settings.microsoft_token_store.chmod(0o644)
    with pytest.raises(oauth.MailOAuthError, match="authorization_required"):
        oauth.access_token(settings, MAILBOX)


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "mail_oauth_authorization_required"),
        (429, "mail_oauth_unavailable"),
        (503, "mail_oauth_unavailable"),
    ],
)
def test_provider_failures_sanitized_and_store_kept(tmp_path, status, code):
    settings = config(tmp_path)
    seed(settings)
    original = settings.microsoft_token_store.read_bytes()
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            status, json={"error_description": "secret-provider-details"}
        )
    )
    with pytest.raises(oauth.MailOAuthError) as exc:
        oauth.access_token(settings, MAILBOX, transport=transport)
    assert str(exc.value) == code
    assert settings.microsoft_token_store.read_bytes() == original


def test_rotation_storage_failure_cannot_use_unsaved_token(tmp_path, monkeypatch):
    settings = config(tmp_path)
    seed(settings)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={
                "access_token": "new",
                "refresh_token": "rotated",
                "expires_in": 3600,
            },
        )
    )
    monkeypatch.setattr(
        oauth.os, "replace", lambda *a: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(oauth.MailOAuthError, match="store_invalid"):
        oauth.access_token(settings, MAILBOX, transport=transport)


def test_smtp_oauth_authenticates_before_sending_and_failure_sends_nothing(
    tmp_path, monkeypatch
):
    from fmg_agent.email import smtp

    settings = config(tmp_path)
    seed(settings, time.time() + 3600)
    calls = []

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def starttls(self, **kwargs):
            calls.append("tls")

        def ehlo(self):
            calls.append("ehlo")
            return 250, b"ready"

        def auth(self, mechanism, callback):
            assert mechanism == "XOAUTH2"
            assert callback() == oauth.xoauth2(MAILBOX, "old-access")
            assert callback(b"error") == ""
            calls.append("oauth")
            # Model Microsoft's post-TLS greeting requirement.
            return (
                (235, b"authenticated")
                if calls[-2:] == ["ehlo", "oauth"]
                else (503, b"Send hello first")
            )

        def send_message(self, *args, **kwargs):
            calls.append("send")
            return {}

        def quit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(smtp.smtplib, "SMTP", Connection)
    message = {
        "from": MAILBOX,
        "to": "test@example.com",
        "subject": "Test",
        "text": "test",
    }
    assert smtp.deliver(settings, message, "test")["state"] == "sent"
    assert calls == ["tls", "ehlo", "oauth", "send"]
    calls.clear()
    monkeypatch.setattr(
        smtp,
        "access_token",
        lambda *a: (_ for _ in ()).throw(
            oauth.MailOAuthError("mail_oauth_authorization_required")
        ),
    )
    assert smtp.deliver(settings, message, "test2") == {
        "state": "failed",
        "code": "mail_oauth_authorization_required",
    }
    assert calls == ["tls"]


@pytest.mark.parametrize(
    "reply,expected",
    [
        ((503, b"5.5.2 Send hello first"), "smtp_authentication_rejected"),
        (
            (535, b"5.7.139 SmtpClientAuthentication is disabled for the Mailbox"),
            "smtp_mailbox_auth_disabled",
        ),
    ],
)
def test_smtp_and_admin_probe_reject_false_auth_success(
    tmp_path, monkeypatch, reply, expected
):
    from fmg_agent.email import smtp, microsoft_admin as admin

    settings = config(tmp_path)
    seed(settings, time.time() + 3600)
    sent = []

    class Connection:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def starttls(self, **kw):
            pass

        def ehlo(self):
            return 250, b"ready"

        def auth(self, *a):
            if reply[0] == 535:
                import smtplib

                raise smtplib.SMTPAuthenticationError(*reply)
            return reply

        def send_message(self, *a, **kw):
            sent.append(True)

        def quit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(smtp.smtplib, "SMTP", Connection)
    result = smtp.deliver(
        settings,
        {"from": MAILBOX, "to": "test@example.com", "subject": "Test", "text": "Test"},
        "test",
    )
    assert result == {"state": "failed", "code": expected}
    assert sent == []
    with pytest.raises(oauth.MailOAuthError, match=expected):
        admin.probe(MAILBOX, "old-access")


def test_imap_oauth_uses_read_only_and_preserves_polling(sending, tmp_path):
    from fmg_agent.email.inbox import sync_once, configured

    app, *_ = sending
    settings = config(tmp_path)
    seed(settings, time.time() + 3600)
    assert configured(settings)
    calls = []

    class Mailbox:
        def __init__(self, *a, **kw):
            pass

        def authenticate(self, mechanism, callback):
            assert mechanism == "XOAUTH2"
            assert callback(b"") == oauth.xoauth2(MAILBOX, "old-access").encode()
            assert callback(b"error") == b""
            calls.append("oauth")

        def select(self, folder, readonly):
            assert readonly is True and folder == '"INBOX"'
            return "OK", [b"0"]

        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

        def response(self, key):
            return key, [b"1"]

        def uid(self, command, *args):
            assert command == "search"
            return "OK", [b""]

        def logout(self):
            pass

    assert sync_once(app.state.sessions, settings, connect=Mailbox) == {
        "state": "active",
        "processed": 0,
        "folders": ["INBOX"],
    }
    assert calls == ["oauth"]


def test_oauth_is_not_ready_until_authorized_and_requires_tls(tmp_path):
    from fmg_agent.email.sending import smtp_ready

    settings = config(tmp_path)
    assert not smtp_ready(settings)
    seed(settings)
    assert smtp_ready(settings)
    settings.smtp_encryption = "none"
    settings.smtp_host = "127.0.0.1"
    settings.smtp_allow_insecure_loopback = True
    assert not smtp_ready(settings)


@pytest.mark.parametrize(
    "verification_uri",
    [
        "https://microsoft.com/devicelogin",
        "https://www.microsoft.com/link",
    ],
)
def test_admin_enrollment_never_prints_tokens(
    tmp_path, capsys, monkeypatch, verification_uri
):
    from argparse import Namespace
    from fmg_agent.email import microsoft_admin as admin

    args = Namespace(client_id=APP_ID, mailbox=MAILBOX, store=tmp_path / "enroll.json")

    def respond(request):
        if request.url.path.endswith("/devicecode"):
            return httpx.Response(
                200,
                json={
                    "device_code": "secret-device-code",
                    "user_code": "TEST-CODE",
                    "verification_uri": verification_uri,
                    "expires_in": 900,
                },
            )
        return httpx.Response(
            200,
            json={
                "access_token": "secret-access",
                "refresh_token": "secret-refresh",
                "expires_in": 3600,
            },
        )

    probes = []
    monkeypatch.setattr(admin, "probe", lambda mailbox, token: probes.append(mailbox))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert admin.authorize(args, client) == 0
        assert admin.complete(args, client) == 0
    output = capsys.readouterr().out
    assert "TEST-CODE" in output and '"sent": 0' in output
    assert all(
        secret not in output
        for secret in ("secret-device-code", "secret-access", "secret-refresh")
    )
    assert probes == [MAILBOX]


@pytest.mark.parametrize(
    "verification_uri",
    [
        "http://www.microsoft.com/link",
        "https://www.microsoft.com.attacker.example/link",
        "https://www.microsoft.com/link?redirect=attacker",
        "https://www.microsoft.com/other",
    ],
)
def test_admin_rejects_untrusted_authorization_urls(tmp_path, capsys, verification_uri):
    from argparse import Namespace
    from fmg_agent.email import microsoft_admin as admin

    args = Namespace(client_id=APP_ID, mailbox=MAILBOX, store=tmp_path / "enroll.json")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "device_code": "secret-device-code",
                    "user_code": "TEST-CODE",
                    "verification_uri": verification_uri,
                    "expires_in": 900,
                    "interval": 5,
                    "message": "Untrusted message",
                },
            )
        )
    ) as client:
        with pytest.raises(oauth.MailOAuthError, match="mail_oauth_invalid_response"):
            admin.authorize(args, client)
    assert not Path(str(args.store) + ".pending").exists()
    assert capsys.readouterr().out == ""


# Reuse the isolated service/API fixture; no local Docker services are started.
from test_email_sending import sending
