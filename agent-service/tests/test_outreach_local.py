"""Local-only HTTP, SMTP, compiled CLI and dashboard integration; no real mail."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread
import time

import httpx
import pytest
import uvicorn
from sqlalchemy import create_engine, inspect

from test_migrations import migrate
from test_smtp_delivery import smtp_server, configuration
from test_email_templates import variables


def test_outreach_additive_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.sqlite'}"
    assert migrate(url, revision="0005_cost").returncode == 0
    result = migrate(url)
    assert result.returncode == 0, result.stderr
    assert migrate(url).returncode == 0
    engine = create_engine(url)
    assert {"outreach_tasks", "outreach_recipients", "email_sends"} <= set(
        inspect(engine).get_table_names()
    )
    engine.dispose()


def test_inbox_migration_preserves_sent_history(tmp_path):
    from datetime import datetime, timezone
    from sqlalchemy import MetaData, select

    url = f"sqlite:///{tmp_path / 'legacy.sqlite'}"
    assert migrate(url, revision="0006_outreach").returncode == 0
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(engine)
    tables = metadata.tables
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            tables["access_tokens"].insert(),
            dict(
                id="owner",
                digest="a" * 64,
                label="test",
                scopes=["email:send"],
                created_at=now,
            ),
        )
        conn.execute(
            tables["email_previews"].insert(),
            dict(
                id="preview",
                token_id="owner",
                template_id="game-outreach",
                template_version="2",
                message={"text": "historical message", "html": "<p>historical</p>"},
                created_at=now,
            ),
        )
        conn.execute(
            tables["email_sends"].insert(),
            dict(
                id="send",
                token_id="owner",
                preview_id="preview",
                idempotency_key="original",
                state="sent",
                created_at=now,
                updated_at=now,
            ),
        )
        conn.execute(
            tables["outreach_tasks"].insert(),
            dict(
                id="task",
                token_id="owner",
                idempotency_key="batch",
                fingerprint="b" * 64,
                revision="r",
                state="sending",
                name="historical",
                run_id="run",
                template={},
            ),
        )
        conn.execute(
            tables["outreach_recipients"].insert(),
            dict(
                id="recipient",
                task_id="task",
                creator_id="creator",
                preview_id="preview",
                response_digest="c" * 64,
                response="yes",
                responded_at=now.isoformat(),
            ),
        )
    upgraded = migrate(url)
    assert upgraded.returncode == 0, upgraded.stderr
    fresh = MetaData()
    fresh.reflect(engine)
    with engine.connect() as conn:
        assert conn.scalar(select(fresh.tables["email_sends"].c.state)) == "sent"
        assert (
            conn.scalar(select(fresh.tables["email_previews"].c.message))["text"]
            == "historical message"
        )
        assert (
            conn.scalar(select(fresh.tables["outreach_recipients"].c.creator_id))
            == "creator"
        )
        assert "response_digest" not in fresh.tables["outreach_recipients"].c
        assert "response" not in fresh.tables["outreach_recipients"].c
    engine.dispose()


def test_local_cli_dashboard_and_smtp(tmp_path, smtp_server):
    binary = os.environ.get("FMG_AGENT_TEST_CLI")
    if not binary:
        pytest.skip("Set FMG_AGENT_TEST_CLI to the compiled local CLI")
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token
    from fmg_agent.db import Base
    from fmg_agent.email.smtp import deliver
    from fmg_agent.outreach import pending, process_recipient

    config = configuration(tmp_path, smtp_server)
    app = create_app(config)
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as session:
        token = issue_token(session, label="local-only", scopes=["email:send"])
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    dashboard = None
    env = dict(os.environ, FMG_CONFIG=str(tmp_path / "config.json"))

    def cli(*args, stdin=""):
        result = subprocess.run(
            [binary, *args],
            env=env,
            input=stdin,
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert token.token not in result.stdout + result.stderr
        return json.loads(result.stdout)

    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        cli(
            "auth",
            "login",
            "--server",
            f"http://127.0.0.1:{port}",
            "--token-stdin",
            stdin=token.token,
        )
        source = tmp_path / "batch.json"
        source.write_text(
            json.dumps(
                {
                    "name": "Local review",
                    "template_id": "game-outreach",
                    "template_version": "4",
                    "recipients": [
                        {
                            "creator_id": "creator-A",
                            "to": "creator@example.com",
                            "variables": variables(),
                        }
                    ],
                }
            )
        )
        task = cli(
            "--run-id",
            "local-outreach",
            "outreach",
            "task",
            "create",
            "--input",
            str(source),
            "--idempotency-key",
            "one",
        )["data"]
        script = (
            Path(__file__).resolve().parents[2]
            / "skills/fmg-api/scripts/outreach_dashboard.py"
        )
        dashboard = subprocess.Popen(
            [sys.executable, str(script), "--task-id", task["id"], "--fmg", binary],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        url = json.loads(dashboard.stdout.readline())["url"]
        with httpx.Client(trust_env=False) as client:
            page = client.get(url)
            assert page.status_code == 200 and "Preview" in page.text
            before = client.get(url + "data")
            assert before.json()["data"]["state"] == "awaiting_approval"
            assert token.token not in before.text + page.text
            assert client.post(url + "data").status_code == 501
            assert client.get(url, headers={"Host": "evil.example"}).status_code == 403
            assert smtp_server.messages == []
            cli(
                "outreach",
                "task",
                "start",
                task["id"],
                "--revision",
                task["revision"],
                "--confirm",
            )
            ids = pending(app.state.sessions)
            for rid in ids + ids:
                process_recipient(app.state.sessions, rid, config, deliver)
            assert len(smtp_server.messages) == 1
            actual = cli("outreach", "task", "get", task["id"])["data"]
            assert actual["stats"]["sent"] == 1
            assert actual["stats"]["replied"] == 0
            assert actual["monitoring"]["state"] == "not_configured"
            assert actual["recipients"][0]["message"]["format"] == "signature_image"
            assert "cid:ontology-play-signature" in actual["recipients"][0]["message"]["html"]
            ledger = cli("--run-id", "local-outreach", "usage")["data"]
            assert "smtp" in json.dumps(ledger)
    finally:
        if dashboard:
            dashboard.terminate()
            dashboard.wait(timeout=10)
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
