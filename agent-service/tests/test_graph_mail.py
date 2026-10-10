"""Only provider I/O is replaced; MIME, private token stores and send guards are real."""

import base64
from email import policy
from email.parser import BytesParser
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest

from fmg_agent.email import microsoft as oauth
from test_microsoft_mail import APP_ID, MAILBOX, config, seed


def graph_settings(tmp_path):
    settings = config(tmp_path)
    settings.email_transport = "microsoft_graph"
    settings.microsoft_graph_token_store = tmp_path / "graph.json"
    return settings


def graph_seed(settings, expires=0, mailbox=MAILBOX):
    oauth.persist(
        settings.microsoft_graph_token_store,
        {
            "client_id": APP_ID,
            "mailbox": mailbox,
            "account_id": "account-one",
            "profile": "graph",
            "access_token": "graph-access",
            "refresh_token": "graph-refresh",
            "expires_at": expires,
        },
    )


def test_graph_ready_needs_separate_verified_grant_not_imap_token(tmp_path):
    from fmg_agent.email.sending import smtp_ready

    settings = graph_settings(tmp_path)
    seed(settings, time.time() + 3600)
    assert not smtp_ready(settings)
    graph_seed(settings, time.time() + 3600)
    assert smtp_ready(settings)
    settings.microsoft_graph_token_store = settings.microsoft_token_store
    assert not smtp_ready(settings)


def test_graph_refresh_verifies_identity_and_leaves_imap_store_untouched(tmp_path):
    settings = graph_settings(tmp_path)
    seed(settings, time.time() + 3600)
    original = settings.microsoft_token_store.read_bytes()
    graph_seed(settings)
    calls = []

    def respond(req):
        calls.append(req)
        if req.url.path.endswith("/token"):
            body = parse_qs(req.content.decode())
            assert body["refresh_token"] == ["graph-refresh"]
            assert "https://graph.microsoft.com/Mail.Send" in body["scope"][0]
            assert "IMAP" not in body["scope"][0]
            return httpx.Response(
                200,
                json={
                    "access_token": "rotated-access",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 3600,
                    "scope": "Mail.Send User.Read",
                },
            )
        assert (
            req.url
            == "https://graph.microsoft.com/v1.0/me?$select=id,mail,userPrincipalName"
        )
        assert req.headers["authorization"] == "Bearer rotated-access"
        return httpx.Response(
            200,
            json={"id": "account-one", "mail": MAILBOX, "userPrincipalName": MAILBOX},
        )

    assert (
        oauth.access_token(
            settings, MAILBOX, profile="graph", transport=httpx.MockTransport(respond)
        )
        == "rotated-access"
    )
    assert len(calls) == 2
    assert (
        json.loads(settings.microsoft_graph_token_store.read_text())["refresh_token"]
        == "rotated-refresh"
    )
    assert settings.microsoft_graph_token_store.stat().st_mode & 0o777 == 0o600
    assert settings.microsoft_token_store.read_bytes() == original


def test_graph_wrong_actual_account_is_rejected_without_overwriting_store(tmp_path):
    settings = graph_settings(tmp_path)
    graph_seed(settings)
    original = settings.microsoft_graph_token_store.read_bytes()

    def respond(req):
        if req.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "wrong-access",
                    "refresh_token": "wrong-refresh",
                    "expires_in": 3600,
                    "scope": "Mail.Send User.Read",
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "wrong-account",
                "mail": "other@outlook.com",
                "userPrincipalName": "other@outlook.com",
            },
        )

    with pytest.raises(oauth.MailOAuthError, match="mail_oauth_mailbox_mismatch"):
        oauth.access_token(
            settings, MAILBOX, profile="graph", transport=httpx.MockTransport(respond)
        )
    assert settings.microsoft_graph_token_store.read_bytes() == original


@pytest.mark.parametrize(
    "status,state,code",
    [
        (202, "sent", None),
        (400, "failed", "graph_request_rejected"),
        (401, "failed", "mail_oauth_authorization_required"),
        (403, "failed", "graph_send_access_denied"),
        (429, "failed", "graph_rate_limited"),
        (503, "unknown", "graph_confirmation_lost"),
        (302, "failed", "graph_request_rejected"),
    ],
)
def test_graph_mime_keeps_template_signature_and_message_id_without_retry(
    tmp_path, status, state, code
):
    from fmg_agent.email.graph import deliver
    from fmg_agent.email.templates import get_template, render_template
    from test_liminal_template import values

    settings = graph_settings(tmp_path)
    graph_seed(settings, time.time() + 3600)
    message = render_template(get_template("game-outreach"), values())
    message.update({"from": MAILBOX, "to": "test@example.com"})
    requests = []

    def respond(req):
        requests.append(req)
        return httpx.Response(
            status,
            headers={"Location": "https://attacker.example", "Retry-After": "10"},
            json={"error": {"message": "secret-provider-detail"}},
        )

    result = deliver(
        settings, message, "test-send", transport=httpx.MockTransport(respond)
    )
    assert {k: result[k] for k in ("state", "code")} == {"state": state, "code": code}
    if status != 202:
        assert result["diagnostics"]["http_status"] == status
    assert len(requests) == 1
    req = requests[0]
    assert (
        req.method == "POST"
        and req.url == "https://graph.microsoft.com/v1.0/me/sendMail"
    )
    assert req.headers["content-type"] == "text/plain"
    assert req.headers["authorization"] == "Bearer graph-access"
    parsed = BytesParser(policy=policy.default).parsebytes(
        base64.b64decode(req.content, validate=True)
    )
    assert str(parsed["Message-ID"]) == "<fmg-test-send@hotmail.com>"
    assert str(parsed["Subject"]) == message["subject"]
    assert str(parsed["To"]) == "test@example.com"
    assert (
        parsed.get_body(preferencelist=("plain",))
        .get_content()
        .replace("\r\n", "\n")
        .strip()
        == message["text"].strip()
    )
    assert (
        'src="cid:ontology-play-signature"'
        in parsed.get_body(preferencelist=("html",)).get_content()
    )
    assert len([p for p in parsed.walk() if p.get_content_type() == "image/png"]) == 1


def test_graph_timeout_is_unknown_and_not_retried(tmp_path):
    from fmg_agent.email.graph import deliver

    settings = graph_settings(tmp_path)
    graph_seed(settings, time.time() + 3600)
    calls = []

    def respond(req):
        calls.append(req)
        raise httpx.ReadTimeout("secret", request=req)

    assert deliver(
        settings,
        {"from": MAILBOX, "to": "test@example.com", "subject": "Test", "text": "test"},
        "test",
        transport=httpx.MockTransport(respond),
    ) == {"state": "unknown", "code": "graph_confirmation_lost"}
    assert len(calls) == 1


def test_graph_dispatch_preserves_allowlist_and_never_falls_back_to_smtp(
    tmp_path, monkeypatch
):
    from fmg_agent.email import smtp, graph

    settings = graph_settings(tmp_path)
    graph_seed(settings, time.time() + 3600)
    monkeypatch.setattr(
        smtp.smtplib, "SMTP", lambda *a, **k: pytest.fail("unexpected SMTP fallback")
    )
    calls = []
    monkeypatch.setattr(
        graph, "deliver", lambda *a: calls.append(a) or {"state": "sent", "code": None}
    )
    settings.smtp_allowed_recipients = ["test@example.com"]
    assert (
        smtp.deliver(settings, {"to": "outside@example.com"}, "one")["state"]
        == "failed"
    )
    assert calls == []
    assert smtp.deliver(settings, {"to": "test@example.com"}, "two")["state"] == "sent"
    assert len(calls) == 1


def test_graph_enrollment_confirms_actual_mailbox_and_does_not_send(tmp_path, capsys):
    from argparse import Namespace
    from fmg_agent.email import microsoft_admin as admin

    args = Namespace(
        client_id=APP_ID,
        mailbox=MAILBOX,
        store=tmp_path / "enroll.json",
        profile="graph",
    )
    calls = []

    def respond(req):
        calls.append(req)
        if req.url.path.endswith("/devicecode"):
            assert "Mail.Send" in parse_qs(req.content.decode())["scope"][0]
            return httpx.Response(
                200,
                json={
                    "device_code": "secret-device",
                    "user_code": "TEST-CODE",
                    "verification_uri": "https://www.microsoft.com/link",
                    "expires_in": 900,
                },
            )
        if req.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "secret-access",
                    "refresh_token": "secret-refresh",
                    "expires_in": 3600,
                    "scope": "Mail.Send User.Read",
                },
            )
        assert req.method == "GET" and req.url.path == "/v1.0/me"
        return httpx.Response(
            200,
            json={"id": "account-one", "mail": MAILBOX, "userPrincipalName": MAILBOX},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert admin.authorize(args, client) == 0
        assert admin.complete(args, client) == 0
    saved = json.loads(args.store.read_text())
    assert saved["profile"] == "graph" and saved["account_id"] == "account-one"
    output = capsys.readouterr().out
    assert '"sent": 0' in output
    assert '"send_verified": false' in output
    assert not any(
        secret in output
        for secret in ("secret-access", "secret-refresh", "secret-device")
    )
    assert len(calls) == 3


def test_graph_enrollment_wrong_account_never_saves_authorization(tmp_path):
    from argparse import Namespace
    from fmg_agent.email import microsoft_admin as admin

    args = Namespace(
        client_id=APP_ID,
        mailbox=MAILBOX,
        store=tmp_path / "enroll.json",
        profile="graph",
    )
    oauth.persist(
        type(args.store)(str(args.store) + ".pending"),
        {
            "profile": "graph",
            "client_id": APP_ID,
            "mailbox": MAILBOX,
            "device_code": "device",
            "expires_at": time.time() + 3600,
            "next_poll_at": 0,
            "interval": 5,
        },
    )

    def respond(req):
        if req.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                    "scope": "Mail.Send User.Read",
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "other",
                "mail": "wrong@outlook.com",
                "userPrincipalName": "wrong@outlook.com",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(oauth.MailOAuthError, match="mail_oauth_mailbox_mismatch"):
            admin.complete(args, client)
    assert not args.store.exists()


def test_graph_missing_send_permission_cannot_become_ready(tmp_path):
    with pytest.raises(oauth.MailOAuthError, match="mail_oauth_invalid_response"):
        oauth.token_data(
            httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                    "scope": "User.Read",
                },
            ),
            APP_ID,
            MAILBOX,
            profile="graph",
        )


def test_graph_failed_send_receipt_is_durable_and_not_replayed(sending, tmp_path):
    from fmg_agent.email.graph import deliver
    from test_email_sending import preview, send

    app, client, owner, *_ = sending
    settings = app.state.settings
    settings.email_transport = "microsoft_graph"
    settings.smtp_from = MAILBOX
    settings.microsoft_client_id = APP_ID
    settings.microsoft_graph_token_store = tmp_path / "graph.json"
    graph_seed(settings, time.time() + 3600)
    calls = []

    def respond(req):
        calls.append(req)
        return httpx.Response(403, json={"error": {"message": "private"}})

    app.state.smtp_transport = lambda cfg, msg, mid: deliver(
        cfg, msg, mid, transport=httpx.MockTransport(respond)
    )
    draft = preview(client, owner).json()["data"]
    assert draft["send_ready"] is True
    result = send(client, owner, draft["id"]).json()["data"]
    assert result["state"] == "failed" and result["code"] == "graph_send_access_denied"
    assert send(client, owner, draft["id"]).json()["data"]["id"] == result["id"]
    assert send(client, owner, draft["id"], key="different-key").status_code == 409
    assert len(calls) == 1


from test_email_sending import sending
