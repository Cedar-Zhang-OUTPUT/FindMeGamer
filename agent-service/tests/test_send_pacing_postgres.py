"""Real PostgreSQL locks, isolated schemas, no external email transport."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text

from test_email_sending import preview, send
from test_migrations import migrate


@pytest.fixture
def pg_sending():
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token
    from fmg_agent.config import Settings

    url = os.environ.get("FMG_AGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set isolated PostgreSQL test URL for mailbox pacing checks")
    engine = create_engine(url)
    assert engine.url.database == "find_me_gamer_agent_test"
    schema = "send_pacing_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    app = None
    try:
        migration = migrate(url, schema)
        assert migration.returncode == 0, migration.stderr
        scoped_url = engine.url.set(query={"options": f"-c search_path={schema}"})
        config = Settings(
            _env_file=None,
            database_url=scoped_url.render_as_string(hide_password=False),
            email_transport="smtp",
            smtp_host="smtp.example.com",
            smtp_username="test",
            smtp_password="offline-test-only",
            smtp_from="publisher@example.com",
            email_send_interval_seconds=5,
        )
        app = create_app(config)
        with app.state.sessions() as session:
            owner = issue_token(
                session, label="offline-pacing-test", scopes=["email:send"]
            )
        with TestClient(app) as client:
            yield app, client, owner
    finally:
        if app:
            app.state.engine.dispose()
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.postgres
def test_live_api_send_remains_exclusive_even_if_recovery_lease_expires(pg_sending):
    app, client, owner = pg_sending
    entered, release = Event(), Event()
    deliveries = []

    def transport(config, message, send_id):
        deliveries.append(send_id)
        entered.set()
        assert release.wait(15)
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    first = preview(client, owner).json()["data"]["id"]
    second = preview(client, owner).json()["data"]["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempt = pool.submit(send, client, owner, first)
        assert entered.wait(5)
        try:
            # An idempotent replay is readable while the live gate is occupied.
            replay = send(client, owner, first)
            assert replay.status_code == 200
            assert replay.json()["data"]["state"] == "sending"
            # Simulate elapsed durable lease while the API's live call still runs.
            with app.state.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE email_send_gates SET available_at=now()-interval '1 second'"
                    )
                )
            blocked = send(client, owner, second, key="second")
            assert blocked.status_code == 429
        finally:
            release.set()
        assert attempt.result().json()["data"]["state"] == "sent"
    assert len(deliveries) == 1


@pytest.mark.postgres
def test_postgres_waits_full_interval_before_next_transport(pg_sending):
    app, client, owner = pg_sending
    starts = []

    def transport(config, message, send_id):
        starts.append(monotonic())
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    first = preview(client, owner).json()["data"]["id"]
    second = preview(client, owner).json()["data"]["id"]
    assert send(client, owner, first).json()["data"]["state"] == "sent"
    blocked = send(client, owner, second, key="second")
    assert blocked.status_code == 429
    sleep(blocked.json()["error"]["retry_after_seconds"])
    assert send(client, owner, second, key="second").json()["data"]["state"] == "sent"
    assert starts[1] - starts[0] >= 5


@pytest.mark.postgres
def test_postgres_cooldown_uses_shared_database_clock(pg_sending, monkeypatch):
    app, client, owner = pg_sending
    deliveries = []

    def transport(config, message, send_id):
        deliveries.append(send_id)
        return {"state": "sent", "code": None}

    app.state.smtp_transport = transport
    first = preview(client, owner).json()["data"]["id"]
    second = preview(client, owner).json()["data"]["id"]
    assert send(client, owner, first).json()["data"]["state"] == "sent"
    monkeypatch.setattr(
        "fmg_agent.email.sending.utcnow",
        lambda: datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    blocked = send(client, owner, second, key="second")
    assert blocked.status_code == 429
    assert 1 <= blocked.json()["error"]["retry_after_seconds"] <= 5
    assert len(deliveries) == 1


@pytest.mark.postgres
def test_postgres_interrupted_owner_recovery_persists_cooldown(pg_sending):
    app, client, owner = pg_sending
    deliveries = []
    app.state.smtp_transport = lambda *args: deliveries.append(args) or {
        "state": "sent"
    }
    with app.state.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO email_send_gates (sender, available_at, lease_id) "
                "VALUES ('publisher@example.com', now()-interval '1 second', 'dead-owner')"
            )
        )
    target = preview(client, owner).json()["data"]["id"]
    assert send(client, owner, target).status_code == 429
    assert deliveries == []
    with app.state.engine.connect() as connection:
        lease, waiting = connection.execute(
            text(
                "SELECT lease_id, available_at > clock_timestamp() FROM email_send_gates"
            )
        ).one()
        assert lease is None
        assert waiting
        assert connection.scalar(text("SELECT count(*) FROM email_sends")) == 0
