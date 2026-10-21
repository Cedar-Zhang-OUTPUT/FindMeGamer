"""Task monitoring follows its frozen mailbox, never the global legacy sender."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import SecretStr

from test_email_sending import headers
from test_mailbox_live_configuration import live_registry
from test_mailbox_outreach import payload

from fmg_agent.email.inbox import InboxCursor, mailbox_key
from fmg_agent.outreach import OutreachTask


def prepare(live_registry):
    app, client, owner, path, entries = live_registry
    app.state.settings.imap_host = "old.example.com"
    app.state.settings.imap_username = "old"
    app.state.settings.imap_password = SecretStr("offline-secret")
    entries["mailboxes"][0].update(
        imap_host="mail.example.com",
        imap_username="alpha",
        imap_password="offline-secret",
    )
    entries["mailboxes"].append(
        {
            **entries["mailboxes"][0],
            "id": "second",
            "imap_username": "second",
            "smtp_from": "second@example.com",
        }
    )
    path.write_text(json.dumps(entries))
    now = datetime.now(timezone.utc)
    stamps = {
        "alpha": now.isoformat(),
        "second": (now - timedelta(seconds=10)).isoformat(),
    }
    with app.state.sessions() as session:
        session.add(
            InboxCursor(
                id=mailbox_key(app.state.settings),
                last_success=(now - timedelta(hours=2)).isoformat(),
            )
        )
        for identity, stamp in stamps.items():
            session.add(
                InboxCursor(
                    id=mailbox_key(
                        app.state.mailboxes.current().settings_for(identity)
                    ),
                    last_success=stamp,
                )
            )
        session.commit()
    tasks = {}
    for identity in stamps:
        response = client.post(
            "/v1/outreach/tasks",
            headers=headers(owner, identity),
            json=payload(identity),
        )
        assert response.status_code == 201
        tasks[identity] = response.json()["data"]["id"]
    return tasks, stamps


@pytest.mark.parametrize("summary", [False, True])
def test_task_monitor_uses_its_own_live_mailbox(live_registry, summary):
    tasks, stamps = prepare(live_registry)
    _, client, owner, _, _ = live_registry
    for identity, task_id in tasks.items():
        response = client.get(
            f"/v1/outreach/tasks/{task_id}",
            headers=headers(owner),
            params={"summary": summary},
        )
        assert response.status_code == 200
        assert response.json()["data"]["monitoring"] == {
            "state": "active",
            "last_success": stamps[identity],
            "error": None,
        }


@pytest.mark.parametrize(
    "change,state,error",
    [
        ("disabled", "disabled", None),
        ("removed", "unavailable", "mailbox_not_found"),
        ("unbound", "unavailable", "mailbox_backfill_required"),
        ("unconfigured", "not_configured", None),
    ],
)
def test_historical_task_never_falls_back_to_legacy_monitor(
    live_registry,
    change,
    state,
    error,
):
    tasks, _ = prepare(live_registry)
    app, client, owner, path, entries = live_registry
    if change == "disabled":
        entries["mailboxes"][0]["enabled"] = False
    elif change == "removed":
        entries["mailboxes"].pop(0)
    elif change == "unconfigured":
        for key in ["imap_host", "imap_username", "imap_password"]:
            entries["mailboxes"][0].pop(key)
    else:
        with app.state.sessions() as session:
            session.get(OutreachTask, tasks["alpha"]).mailbox_id = None
            session.commit()
    path.write_text(json.dumps(entries))
    response = client.get(
        f"/v1/outreach/tasks/{tasks['alpha']}",
        headers=headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["data"]["monitoring"] == {
        "state": state,
        "last_success": None,
        "error": error,
    }
    # Changing one mailbox cannot contaminate the other mailbox's monitor.
    other = client.get(
        f"/v1/outreach/tasks/{tasks['second']}",
        headers=headers(owner),
    )
    assert other.json()["data"]["monitoring"]["state"] == "active"


def test_invalid_registry_is_not_hidden_as_inactive_monitor(live_registry):
    tasks, _ = prepare(live_registry)
    _, client, owner, path, _ = live_registry
    path.write_text("{invalid")
    response = client.get(
        f"/v1/outreach/tasks/{tasks['alpha']}",
        headers=headers(owner),
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "mailbox_configuration_invalid"
