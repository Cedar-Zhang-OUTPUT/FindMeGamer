import pytest

from test_email_sending import sending, headers, send
from test_email_templates import variables
from fmg_agent.mailboxes import MailboxProfile, MailboxRegistry
from fmg_agent.email.sending import SendStore
from fmg_agent.errors import ApiError


def setup_mailboxes(app):
    profiles = [
        MailboxProfile(
            id=name,
            smtp_from=f"{name}@example.com",
            display_name=name.title(),
            smtp_host=f"smtp.{name}.example.com",
            smtp_username=name,
            smtp_password=f"{name}-secret",
            email_send_interval_seconds=0,
            allowed_templates=["game-outreach"],
        )
        for name in ("alpha", "beta")
    ]
    app.state.mailboxes = MailboxRegistry(app.state.settings, profiles, legacy=False)
    return profiles


def draft(client, owner, mailbox):
    response = client.post(
        "/v1/email/previews",
        headers=headers(owner),
        json={
            "mailbox_id": mailbox,
            "template_id": "game-outreach",
            "template_version": "5",
            "variables": variables(),
            "to": "creator@example.com",
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def test_transport_uses_bound_profile(sending, tmp_path):
    from test_graph_mail import graph_settings, graph_seed

    app, client, owner, _, _ = sending
    profiles = setup_mailboxes(app)
    graph = graph_settings(tmp_path)
    graph.smtp_from = "alpha@example.com"
    graph_seed(graph, mailbox="alpha@example.com")
    profiles[0] = profiles[0].model_copy(
        update={
            "email_transport": "microsoft_graph",
            "microsoft_client_id": graph.microsoft_client_id,
            "microsoft_graph_token_store": graph.microsoft_graph_token_store,
        }
    )
    app.state.mailboxes = MailboxRegistry(app.state.settings, profiles, legacy=False)
    calls = []
    app.state.smtp_transport = lambda c, m, i: calls.append(
        (
            c.smtp_host,
            c.smtp_password.get_secret_value(),
            m["from"],
            m["from_name"],
            c.email_transport,
        )
    ) or {"state": "sent"}
    for name in ("alpha", "beta"):
        assert (
            send(client, owner, draft(client, owner, name), key=name).status_code == 200
        )
    assert calls == [
        (
            "smtp.alpha.example.com",
            "alpha-secret",
            "alpha@example.com",
            "Alpha",
            "microsoft_graph",
        ),
        ("smtp.beta.example.com", "beta-secret", "beta@example.com", "Beta", "smtp"),
    ]


@pytest.mark.parametrize("change", ["sender", "name", "disabled", "template"])
def test_identity_or_template_changed_blocks(sending, change):
    app, client, owner, _, _ = sending
    profiles = setup_mailboxes(app)
    preview_id = draft(client, owner, "alpha")
    updates = {
        "sender": {"smtp_from": "other@example.com"},
        "name": {"display_name": "Other"},
        "disabled": {"enabled": False},
        "template": {"allowed_templates": []},
    }
    app.state.mailboxes = MailboxRegistry(
        app.state.settings,
        [profiles[0].model_copy(update=updates[change]), profiles[1]],
        legacy=False,
    )
    calls = []
    app.state.smtp_transport = lambda *args: calls.append(args) or {"state": "sent"}
    response = send(client, owner, preview_id)
    assert response.status_code == 409
    assert (
        response.json()["error"]["code"]
        == {
            "sender": "mailbox_identity_conflict",
            "name": "mailbox_identity_conflict",
            "disabled": "mailbox_disabled",
            "template": "mailbox_template_not_allowed",
        }[change]
    )
    assert calls == []


def test_wrong_worker_never_calls_transport(sending):
    app, client, owner, _, _ = sending
    setup_mailboxes(app)
    preview_id = draft(client, owner, "alpha")
    calls = []
    with pytest.raises(ApiError) as error:
        SendStore(app.state.sessions).send(
            owner.id,
            preview_id,
            "worker",
            app.state.settings,
            lambda *a: calls.append(a),
            registry=app.state.mailboxes,
            expected_mailbox_id="beta",
        )
    assert error.value.code == "mailbox_queue_mismatch"
    assert calls == []


def test_pause_affects_only_bound_mailbox(sending):
    from fmg_agent.email.safety import trip

    app, client, owner, _, _ = sending
    setup_mailboxes(app)
    previews = {name: draft(client, owner, name) for name in ("alpha", "beta")}
    with app.state.sessions() as session:
        trip(session, "alpha@example.com", "delivery_failures")
        session.commit()
    calls = []
    app.state.smtp_transport = lambda c, m, i: calls.append(m["from"]) or {
        "state": "sent"
    }
    assert send(client, owner, previews["alpha"], key="alpha").status_code == 409
    assert send(client, owner, previews["beta"], key="beta").status_code == 200
    assert calls == ["beta@example.com"]


@pytest.mark.parametrize("state", ["sent", "unknown"])
def test_unknown_and_sent_replay_never_deliver_again(sending, state):
    app, client, owner, _, _ = sending
    profiles = setup_mailboxes(app)
    preview_id = draft(client, owner, "alpha")
    calls = []
    app.state.smtp_transport = lambda *a: calls.append(a) or {"state": state}
    original = send(client, owner, preview_id)
    assert original.status_code == 200
    app.state.mailboxes = MailboxRegistry(
        app.state.settings,
        [profiles[0].model_copy(update={"enabled": False}), profiles[1]],
        legacy=False,
    )
    assert (
        send(client, owner, preview_id).json()["data"]["id"]
        == original.json()["data"]["id"]
    )
    assert len(calls) == 1


def test_mime_formats_frozen_name_and_rejects_injection():
    from fmg_agent.email.mime import build_message

    message = {
        "from": "alpha@example.com",
        "from_name": "Alpha, Studio",
        "to": "c@example.com",
        "subject": "Hello",
        "text": "Body",
    }
    mail = build_message(message, "one")
    assert mail["From"].addresses[0].display_name == "Alpha, Studio"
    assert mail["From"].addresses[0].addr_spec == "alpha@example.com"
    with pytest.raises(ValueError):
        build_message({**message, "from_name": "Alpha\r\nBcc: bad@example.com"}, "one")


@pytest.mark.parametrize("actual_mail", ["other@example.com", "sender@hotmail.com"])
def test_graph_cached_token_actual_account_mismatch_never_posts(tmp_path, actual_mail):
    import time
    import httpx
    from test_graph_mail import graph_settings, graph_seed, MAILBOX
    from fmg_agent.email.graph import deliver

    settings = graph_settings(tmp_path)
    graph_seed(settings, time.time() + 3600)
    calls = []

    def respond(request):
        calls.append(request.method)
        return httpx.Response(200, json={"id": "other-account", "mail": actual_mail})

    result = deliver(
        settings,
        {"from": MAILBOX, "to": "c@example.com", "subject": "Hello", "text": "Body"},
        "one",
        transport=httpx.MockTransport(respond),
    )
    assert result == {"state": "failed", "code": "mail_oauth_mailbox_mismatch"}
    assert calls == ["GET"]


def test_graph_readiness_rejects_other_stored_account(tmp_path):
    from test_graph_mail import graph_settings, graph_seed
    from fmg_agent.email.sending import smtp_ready

    settings = graph_settings(tmp_path)
    graph_seed(settings, mailbox="other@example.com")
    assert smtp_ready(settings) is False


def test_preview_readiness_uses_bound_profile(sending):
    app, client, owner, _, _ = sending
    setup_mailboxes(app)
    preview_id = draft(client, owner, "beta")
    response = client.get("/v1/email/previews/" + preview_id, headers=headers(owner))
    assert response.json()["data"]["send_ready"] is True


def test_oauth_label_mismatch_before_transport(sending, tmp_path):
    from test_graph_mail import graph_settings, graph_seed

    app, client, owner, _, _ = sending
    profiles = setup_mailboxes(app)
    graph = graph_settings(tmp_path)
    graph_seed(graph, mailbox="other@example.com")
    profiles[0] = profiles[0].model_copy(
        update={
            "email_transport": "microsoft_graph",
            "microsoft_client_id": graph.microsoft_client_id,
            "microsoft_graph_token_store": graph.microsoft_graph_token_store,
        }
    )
    app.state.mailboxes = MailboxRegistry(app.state.settings, profiles, legacy=False)
    preview_id = draft(client, owner, "alpha")
    calls = []
    app.state.smtp_transport = lambda *a: calls.append(a) or {"state": "sent"}
    response = send(client, owner, preview_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "mail_oauth_authorization_required"
    assert calls == []


def test_wrong_recipient_worker_preserves_task(sending):
    from test_mailbox_outreach import payload
    from fmg_agent.outreach import process_recipient, OutreachTask

    app, client, owner, _, _ = sending
    setup_mailboxes(app)
    task = client.post(
        "/v1/outreach/tasks", headers=headers(owner), json=payload("alpha")
    ).json()["data"]
    assert (
        client.post(
            "/v1/outreach/tasks/" + task["id"] + "/start",
            headers=headers(owner),
            json={"confirm": True, "revision": task["revision"]},
        ).status_code
        == 200
    )
    calls = []
    result = process_recipient(
        app.state.sessions,
        task["recipients"][0]["id"],
        app.state.settings,
        lambda *a: calls.append(a),
        registry=app.state.mailboxes,
        expected_mailbox_id="beta",
    )
    assert result == {"code": "mailbox_queue_mismatch", "transport_attempted": False}
    with app.state.sessions() as session:
        assert session.get(OutreachTask, task["id"]).state == "sending"
    assert calls == []


def test_wrong_retry_worker_preserves_queue_and_frozen_identity(sending, monkeypatch):
    from test_bounce_safety import accepted, dsn
    from test_bounce_retry import retry_row, advance
    from fmg_agent.email.inbox import ingest
    from fmg_agent.email.retries import process_retry
    from fmg_agent.email.models import EmailPreview

    app, client, owner, _, _ = sending
    setup_mailboxes(app)
    original = accepted(app, client, owner, "bounce", mailbox_id="alpha")
    ingest(app.state.sessions, "junk", "1", 1, dsn(original, "bounce"))
    retry = retry_row(app, original)
    advance(monkeypatch, retry.due_at)
    calls = []
    result = process_retry(
        app.state.sessions,
        original,
        app.state.settings,
        lambda *a: calls.append(a),
        registry=app.state.mailboxes,
        expected_mailbox_id="beta",
    )
    assert result == {"code": "mailbox_queue_mismatch", "transport_attempted": False}
    assert retry_row(app, original).state == "queued"
    with app.state.sessions() as session:
        frozen = session.get(EmailPreview, retry.preview_id)
        assert frozen.mailbox_id == "alpha"
        assert frozen.message["from_name"] == "Alpha"
    assert calls == []


def test_credential_rotation_preserves_frozen_message(sending):
    from pydantic import SecretStr

    app, client, owner, _, _ = sending
    profiles = setup_mailboxes(app)
    preview_id = draft(client, owner, "alpha")
    frozen = client.get(
        "/v1/email/previews/" + preview_id, headers=headers(owner)
    ).json()["data"]["message"]
    profiles[0] = profiles[0].model_copy(
        update={"smtp_password": SecretStr("rotated-secret")}
    )
    app.state.mailboxes = MailboxRegistry(app.state.settings, profiles, legacy=False)
    calls = []
    app.state.smtp_transport = lambda c, m, i: calls.append(
        (c.smtp_password.get_secret_value(), m)
    ) or {"state": "sent"}
    assert send(client, owner, preview_id).status_code == 200
    assert calls == [("rotated-secret", frozen)]


@pytest.mark.parametrize(
    "identity,sender",
    [
        ("beta", "beta@example.com"),
        ("beta", "OntologyPlay@hotmail.com"),
        ("ontologyplay", "other@example.com"),
    ],
)
def test_liminal_fixed_signature_cannot_be_assigned_to_other_sender(
    sending, identity, sender
):
    from test_liminal_fixed_copy import personalization

    app, client, owner, _, _ = sending
    profile = MailboxProfile(
        id=identity, smtp_from=sender, allowed_templates=["liminal-outreach"]
    )
    app.state.mailboxes = MailboxRegistry(app.state.settings, [profile], legacy=False)
    response = client.post(
        "/v1/email/previews",
        headers=headers(owner),
        json={
            "mailbox_id": identity,
            "template_id": "liminal-outreach",
            "template_version": "7",
            "variables": personalization(),
            "to": "creator@example.com",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "mailbox_template_not_allowed"


def test_smtp_oauth_cannot_send_as_another_account(sending, tmp_path):
    from test_microsoft_mail import config, seed

    app, client, owner, _, _ = sending
    profiles = setup_mailboxes(app)
    oauth = config(tmp_path)
    seed(oauth)
    profiles[0] = profiles[0].model_copy(
        update={
            "smtp_auth": "microsoft_oauth",
            "smtp_username": oauth.smtp_username,
            "microsoft_client_id": oauth.microsoft_client_id,
            "microsoft_token_store": oauth.microsoft_token_store,
        }
    )
    app.state.mailboxes = MailboxRegistry(app.state.settings, profiles, legacy=False)
    preview_id = draft(client, owner, "alpha")
    calls = []
    app.state.smtp_transport = lambda *a: calls.append(a) or {"state": "sent"}
    response = send(client, owner, preview_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "mail_oauth_mailbox_mismatch"
    assert calls == []
