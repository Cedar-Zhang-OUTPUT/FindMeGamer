"""Private file changes must affect a running API without changing frozen drafts."""

import json

import pytest
from fastapi.testclient import TestClient

from test_email_sending import headers, send
from test_mailbox_delivery import draft
from test_mailbox_outreach import payload
from test_send_pacing_postgres import pg_sending


@pytest.fixture
def live_registry(tmp_path):
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token
    from fmg_agent.config import Settings
    from fmg_agent.db import Base
    from fmg_agent.mail_runtime import set_runtime

    path = tmp_path / "mailboxes.json"
    entries = {
        "mailboxes": [
            {
                "id": "alpha",
                "smtp_from": "alpha@example.com",
                "display_name": "Alpha",
                "smtp_host": "smtp.example.com",
                "smtp_username": "alpha",
                "smtp_password": "offline-secret",
                "allowed_templates": ["game-outreach"],
                "email_send_interval_seconds": 0,
            }
        ]
    }
    path.write_text(json.dumps(entries))
    path.chmod(0o600)
    app = create_app(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{tmp_path / 'live.sqlite'}",
            mailboxes_file=path,
        )
    )
    Base.metadata.create_all(app.state.engine)
    set_runtime(app.state.sessions, dispatch_enabled=True, send_enabled=True)
    with app.state.sessions() as session:
        owner = issue_token(session, label="owner", scopes=["email:send"])
    with TestClient(app) as client:
        yield app, client, owner, path, entries


@pytest.mark.parametrize(
    "change,code",
    [
        ({"enabled": False}, "mailbox_disabled"),
        ({"allowed_templates": []}, "mailbox_template_not_allowed"),
        ({"smtp_from": "changed@example.com"}, "mailbox_identity_conflict"),
        ({"display_name": "Changed"}, "mailbox_identity_conflict"),
    ],
)
def test_private_file_change_blocks_confirmed_send_and_preserves_receipt(
    live_registry, change, code
):
    from fmg_agent.email.models import EmailPreview

    app, client, owner, path, entries = live_registry
    completed = draft(client, owner, "alpha")
    pending = draft(client, owner, "alpha")
    calls = []
    app.state.smtp_transport = lambda c, m, i: calls.append(i) or {"state": "sent"}
    receipt = send(client, owner, completed, key="completed").json()["data"]
    replay_before = send(client, owner, completed, key="completed").json()["data"]
    assert replay_before["id"] == receipt["id"]
    assert replay_before["state"] == "sent"
    with app.state.sessions() as session:
        frozen = dict(session.get(EmailPreview, pending).message)
    entries["mailboxes"][0].update(change)
    path.write_text(json.dumps(entries))
    response = send(client, owner, pending, key="pending")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert (
        send(client, owner, completed, key="completed").json()["data"] == replay_before
    )
    assert len(calls) == 1
    with app.state.sessions() as session:
        assert session.get(EmailPreview, pending).message == frozen
    current = client.get(
        f"/v1/email/previews/{pending}", headers=headers(owner)
    ).json()["data"]
    assert current["send_ready"] is False
    assert current["message"] == frozen


def test_private_file_credential_rotation_uses_current_secret_and_frozen_message(
    live_registry,
):
    _, client, owner, path, entries = live_registry
    app = client.app
    pending = draft(client, owner, "alpha")
    frozen = client.get(f"/v1/email/previews/{pending}", headers=headers(owner)).json()[
        "data"
    ]["message"]
    entries["mailboxes"][0]["smtp_password"] = "rotated-offline-secret"
    path.write_text(json.dumps(entries))
    delivered = []
    app.state.smtp_transport = lambda c, m, i: delivered.append(
        (c.smtp_password.get_secret_value(), m)
    ) or {"state": "sent"}
    assert send(client, owner, pending).status_code == 200
    assert delivered == [("rotated-offline-secret", frozen)]


@pytest.mark.parametrize("operation", ["discovery", "preview", "create", "approval"])
def test_private_file_disable_updates_discovery_creation_and_approval(
    live_registry, operation
):
    app, client, owner, path, entries = live_registry
    task = client.post(
        "/v1/outreach/tasks", headers=headers(owner), json=payload("alpha")
    ).json()["data"]
    entries["mailboxes"][0]["enabled"] = False
    path.write_text(json.dumps(entries))
    if operation == "discovery":
        assert (
            client.get("/v1/email/mailboxes", headers=headers(owner)).json()["data"][0][
                "enabled"
            ]
            is False
        )
    elif operation == "preview":
        from test_email_templates import variables

        response = client.post(
            "/v1/email/previews",
            headers=headers(owner),
            json={
                "mailbox_id": "alpha",
                "template_id": "game-outreach",
                "template_version": "5",
                "variables": variables(),
                "to": "creator@example.com",
            },
        )
        assert response.json()["error"]["code"] == "mailbox_disabled"
    elif operation == "create":
        response = client.post(
            "/v1/outreach/tasks", headers=headers(owner, "new"), json=payload("alpha")
        )
        assert response.json()["error"]["code"] == "mailbox_disabled"
    else:
        response = client.post(
            f"/v1/outreach/tasks/{task['id']}/start",
            headers=headers(owner),
            json={"confirm": True, "revision": task["revision"]},
        )
        assert response.json()["error"]["code"] == "mailbox_disabled"
    current = client.get(
        f"/v1/outreach/tasks/{task['id']}", headers=headers(owner)
    ).json()["data"]
    assert current["revision"] == task["revision"]
    assert current["state"] == task["state"]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"allowed_templates": []}, "mailbox_template_not_allowed"),
        ({"smtp_from": "changed@example.com"}, "mailbox_identity_conflict"),
        ({"display_name": "Changed"}, "mailbox_identity_conflict"),
    ],
)
def test_private_file_change_blocks_approval_without_changing_revision(
    live_registry, change, code
):
    _, client, owner, path, entries = live_registry
    task = client.post(
        "/v1/outreach/tasks", headers=headers(owner), json=payload("alpha")
    ).json()["data"]
    entries["mailboxes"][0].update(change)
    path.write_text(json.dumps(entries))
    response = client.post(
        f"/v1/outreach/tasks/{task['id']}/start",
        headers=headers(owner),
        json={"confirm": True, "revision": task["revision"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    current = client.get(
        f"/v1/outreach/tasks/{task['id']}", headers=headers(owner)
    ).json()["data"]
    assert current["revision"] == task["revision"]
    assert current["state"] == task["state"]
    assert current["recipients"] == task["recipients"]


@pytest.mark.parametrize("damage", ["permissions", "malformed", "missing"])
def test_invalid_private_file_fails_closed_but_receipt_replays(live_registry, damage):
    app, client, owner, path, _ = live_registry
    completed, pending = (draft(client, owner, "alpha") for _ in range(2))
    calls = []
    app.state.smtp_transport = lambda *a: calls.append(a) or {"state": "unknown"}
    receipt = send(client, owner, completed, key="completed").json()["data"]
    replay_before = send(client, owner, completed, key="completed").json()["data"]
    assert replay_before["id"] == receipt["id"]
    assert replay_before["state"] == "unknown"
    if damage == "permissions":
        path.chmod(0o644)
    elif damage == "malformed":
        path.write_text("not json")
    else:
        path.unlink()
    response = send(client, owner, pending, key="pending")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "mailbox_configuration_invalid"
    assert (
        send(client, owner, completed, key="completed").json()["data"] == replay_before
    )
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["held-local", "local-ready"])
@pytest.mark.parametrize(
    "damage",
    [
        "host",
        "username",
        "password",
        "folder",
        "oauth_missing",
        "oauth_identity",
        "oauth_sender",
        "oauth_permissions",
    ],
)
def test_monitor_probe_rejects_incomplete_imap_even_with_complete_smtp(
    tmp_path, monkeypatch, mode, damage
):
    from fmg_agent import role_health
    from fmg_agent.config import Settings
    from test_microsoft_mail import config, seed

    monkeypatch.setenv("FMG_AGENT_ROLE_HEALTH_DIR", str(tmp_path / "health"))
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///probe-only",
        smtp_host="smtp.example.com",
        smtp_username="sender",
        smtp_password="secret",
        smtp_from="sender@hotmail.com",
        imap_host="imap.example.com",
        imap_username="sender@hotmail.com",
        imap_password="secret",
    )
    if damage.startswith("oauth"):
        oauth = config(tmp_path)
        seed(oauth)
        settings.imap_auth = "microsoft_oauth"
        settings.microsoft_client_id = oauth.microsoft_client_id
        settings.microsoft_token_store = oauth.microsoft_token_store
        if damage == "oauth_missing":
            settings.microsoft_token_store.unlink()
        elif damage == "oauth_permissions":
            settings.microsoft_token_store.chmod(0o644)
        elif damage == "oauth_sender":
            settings.smtp_from = "other@hotmail.com"
        else:
            settings.imap_username = "other@hotmail.com"
    else:
        setattr(settings, "imap_" + damage, "")
    role_health.record(settings, "monitor", "ontologyplay", mode=mode)
    with pytest.raises(ValueError, match="configuration"):
        role_health.probe(settings, "monitor", "ontologyplay")


def test_monitor_probe_validates_oauth_locally_without_refresh(tmp_path, monkeypatch):
    from fmg_agent import role_health
    from fmg_agent.email import microsoft
    from test_microsoft_mail import config, seed

    settings = config(tmp_path)
    seed(settings, expires=0)
    monkeypatch.setenv("FMG_AGENT_ROLE_HEALTH_DIR", str(tmp_path / "health"))
    monkeypatch.setattr(
        microsoft,
        "access_token",
        lambda *a, **k: pytest.fail("offline readiness refreshed token"),
    )
    role_health.record(settings, "monitor", "ontologyplay", mode="held-local")
    assert (
        role_health.probe(settings, "monitor", "ontologyplay")["mode"] == "held-local"
    )


@pytest.mark.postgres
@pytest.mark.parametrize("held", [True, False])
@pytest.mark.parametrize(
    "configuration", ["missing", "invalid_oauth", "valid", "not_configured"]
)
def test_monitor_loop_only_records_ready_for_usable_imap(
    pg_sending, tmp_path, monkeypatch, held, configuration
):
    from threading import Event
    from fmg_agent.email import monitor
    from fmg_agent import role_health
    from fmg_agent.mail_runtime import set_runtime
    from test_microsoft_mail import config, seed

    app, *_ = pg_sending
    settings = app.state.settings
    if configuration != "missing":
        settings.imap_host = "imap.example.com"
        settings.imap_username = "publisher@example.com"
        settings.imap_password = "offline-secret"
    if configuration == "invalid_oauth":
        oauth = config(tmp_path)
        seed(oauth)
        settings.imap_auth = "microsoft_oauth"
        settings.microsoft_client_id = oauth.microsoft_client_id
        settings.microsoft_token_store = oauth.microsoft_token_store
    monkeypatch.setenv("FMG_AGENT_ROLE_HEALTH_DIR", str(tmp_path / "health"))
    set_runtime(app.state.sessions, dispatch_enabled=not held, send_enabled=not held)
    observed = []

    class OneCycle(Event):
        def wait(self, timeout=None):
            if not self.is_set():
                observed.append(
                    role_health.path_for(settings, "monitor", "ontologyplay").exists()
                )
            self.set()
            return True

    if held:
        monkeypatch.setattr(
            monitor,
            "sync_once",
            lambda *a, **k: pytest.fail("held monitor contacted IMAP"),
        )
    elif configuration in {"valid", "not_configured"}:
        monkeypatch.setattr(
            monitor,
            "sync_once",
            lambda *a, **k: {
                "state": "active" if configuration == "valid" else "not_configured"
            },
        )
    else:
        # Missing configuration returns before connecting; invalid OAuth must
        # fail the same local preflight without opening a provider connection.
        monkeypatch.setattr(
            "imaplib.IMAP4_SSL",
            lambda *a, **k: pytest.fail("invalid IMAP reached provider"),
        )
    monitor.monitor_mailbox(settings, "ontologyplay", OneCycle())
    assert observed == [
        configuration == "valid" or (held and configuration == "not_configured")
    ]
