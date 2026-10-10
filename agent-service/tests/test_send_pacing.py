"""Exercise the shared durable gate, not a per-worker sleep or provider retry."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

from sqlalchemy import func, select

from test_email_sending import headers, preview, send, sending
from test_outreach import create


def paced(app, monkeypatch):
    clock = [datetime.now(timezone.utc)]
    app.state.settings = app.state.settings.model_copy(
        update={"email_send_interval_seconds": 5}
    )
    monkeypatch.setattr("fmg_agent.email.sending.utcnow", lambda: clock[0])
    return clock


def test_single_send_waits_five_seconds_without_consuming_preview(sending, monkeypatch):
    from fmg_agent.email.models import EmailSend

    app, client, owner, _, _ = sending
    clock = paced(app, monkeypatch)
    deliveries = []

    def transport(config, message, send_id):
        deliveries.append(send_id)
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    first = preview(client, owner).json()["data"]["id"]
    second = preview(client, owner).json()["data"]["id"]
    receipt = send(client, owner, first).json()["data"]
    blocked = send(client, owner, second, key="second")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "email_send_throttled"
    assert blocked.json()["error"]["retry_after_seconds"] == 5
    assert blocked.json()["error"]["retryable"] is True
    assert len(deliveries) == 1
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EmailSend)) == 1
    clock[0] += timedelta(seconds=4)
    assert send(client, owner, first).json()["data"]["id"] == receipt["id"]
    blocked = send(client, owner, second, key="second")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["retry_after_seconds"] == 1
    clock[0] += timedelta(seconds=1)
    assert send(client, owner, second, key="second").json()["data"]["state"] == "sent"
    assert len(deliveries) == 2


def test_concurrent_tokens_and_stores_cannot_bypass_mailbox_gate(sending, monkeypatch):
    app, client, owner, other, _ = sending
    paced(app, monkeypatch)
    entered, release = Event(), Event()
    deliveries = []

    def transport(config, message, send_id):
        deliveries.append(send_id)
        entered.set()
        assert release.wait(5)
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    first = preview(client, owner).json()["data"]["id"]
    second = preview(client, other).json()["data"]["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending_first = pool.submit(send, client, owner, first)
        assert entered.wait(5)
        try:
            blocked = send(client, other, second)
            assert blocked.status_code == 429
            assert blocked.json()["error"]["code"] == "email_send_throttled"
        finally:
            release.set()
        assert sending_first.result().json()["data"]["state"] == "sent"
    assert len(deliveries) == 1


def test_batches_share_single_send_gate_and_remain_pending(sending, monkeypatch):
    from fmg_agent.outreach import pending, process_recipient

    app, client, owner, _, _ = sending
    clock = paced(app, monkeypatch)
    deliveries = []

    def transport(config, message, send_id):
        deliveries.append(send_id)
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    tasks = [create(app, client, owner, key=key).json()["data"] for key in ("a", "b")]
    for task in tasks:
        client.post(
            "/v1/outreach/tasks/" + task["id"] + "/start",
            headers=headers(owner),
            json={"confirm": True, "revision": task["revision"]},
        )
    single = preview(client, owner).json()["data"]["id"]
    assert send(client, owner, single).json()["data"]["state"] == "sent"
    ids = pending(app.state.sessions)
    assert len(ids) == 4
    for rid in ids:
        process_recipient(app.state.sessions, rid, app.state.settings, transport)
    assert len(deliveries) == 1
    assert set(pending(app.state.sessions)) == set(ids)
    for task in tasks:
        data = client.get(
            "/v1/outreach/tasks/" + task["id"], headers=headers(owner)
        ).json()["data"]
        assert data["state"] == "sending"
        assert data["stats"]["pending"] == 2
        assert data["stats"]["failed"] == 0
    clock[0] += timedelta(seconds=5)
    process_recipient(app.state.sessions, ids[0], app.state.settings, transport)
    assert len(deliveries) == 2
    assert len(pending(app.state.sessions)) == 3


def test_cooldown_runs_after_transport_and_unknown_is_not_retried(sending, monkeypatch):
    app, client, owner, _, _ = sending
    clock = paced(app, monkeypatch)
    deliveries = []

    def transport(config, message, send_id):
        deliveries.append(send_id)
        clock[0] += timedelta(seconds=20)
        raise RuntimeError("uncertain external acceptance")

    app.state.smtp_transport = transport
    first = preview(client, owner).json()["data"]["id"]
    second = preview(client, owner).json()["data"]["id"]
    assert send(client, owner, first).json()["data"]["state"] == "unknown"
    assert send(client, owner, second, key="second").status_code == 429
    clock[0] += timedelta(seconds=5)
    assert send(client, owner, first).json()["data"]["state"] == "unknown"
    assert len(deliveries) == 1
    assert (
        send(client, owner, second, key="second").json()["data"]["state"] == "unknown"
    )
    assert len(deliveries) == 2


def test_expired_interrupted_owner_gets_fresh_cooldown(sending, monkeypatch):
    from fmg_agent.email.models import EmailSendGate

    app, client, owner, _, _ = sending
    clock = paced(app, monkeypatch)
    deliveries = []

    def transport(config, message, send_id):
        deliveries.append(send_id)
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    with app.state.sessions() as session:
        session.add(
            EmailSendGate(
                sender=app.state.settings.smtp_from.casefold(),
                available_at=clock[0] - timedelta(seconds=1),
                lease_id="interrupted-owner",
            )
        )
        session.commit()
    target = preview(client, owner).json()["data"]["id"]
    blocked = send(client, owner, target)
    assert blocked.status_code == 429
    assert deliveries == []
    with app.state.sessions() as session:
        gate = session.get(EmailSendGate, app.state.settings.smtp_from.casefold())
        assert gate.lease_id is None
        assert gate.available_at.replace(tzinfo=timezone.utc) == clock[0] + timedelta(
            seconds=5
        )
    clock[0] += timedelta(seconds=5)
    assert send(client, owner, target).json()["data"]["state"] == "sent"
    assert len(deliveries) == 1
