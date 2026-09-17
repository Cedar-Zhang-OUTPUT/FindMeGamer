"""Compiled CLI -> real HTTP -> PostgreSQL -> Redis -> restarted Celery worker."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
import uvicorn

from test_migrations import migrate
from test_smtp_delivery import smtp_server
from test_email_templates import variables


@pytest.mark.postgres
def test_cli_email_worker_restart(tmp_path, smtp_server):
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token
    from fmg_agent.config import Settings

    dsn = os.environ.get("FMG_AGENT_TEST_DATABASE_URL")
    binary = os.environ.get("FMG_AGENT_TEST_CLI")
    if not dsn or not binary:
        pytest.skip("Set isolated database and compiled FMG_AGENT_TEST_CLI")
    binary = str(Path(binary).resolve())
    engine = create_engine(dsn)
    assert engine.url.database == "find_me_gamer_agent_test"
    schema = "email_e2e_" + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    process = None
    server = None
    thread = None
    worker_output = None
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    try:
        migrated = migrate(dsn, schema)
        assert migrated.returncode == 0, migrated.stderr
        settings = Settings(
            database_url=engine.url.set(
                query={"options": f"-c search_path={schema}"}
            ).render_as_string(hide_password=False),
            smtp_host="127.0.0.1",
            smtp_port=smtp_server.server_address[1],
            smtp_encryption="none",
            smtp_allow_insecure_loopback=True,
            smtp_from="publisher@example.com",
            outreach_public_url="https://callback.example.com",
        )
        app = create_app(settings)
        with app.state.sessions() as session:
            token = issue_token(
                session, label="e2e", scopes=["email:enrich", "email:send"]
            )
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        cli_env = dict(os.environ, FMG_CONFIG=str(tmp_path / "cli.json"))

        def cli(*args, stdin=""):
            result = subprocess.run(
                [binary, *args],
                input=stdin,
                text=True,
                capture_output=True,
                env=cli_env,
                timeout=15,
            )
            assert token.token not in result.stdout + result.stderr
            return result

        assert (
            cli(
                "auth",
                "login",
                "--server",
                f"http://127.0.0.1:{port}",
                "--token-stdin",
                stdin=token.token,
            ).returncode
            == 0
        )
        listed = cli("email", "templates")
        assert listed.returncode == 0, listed.stderr
        assert json.loads(listed.stdout)["data"][0]["id"] == "game-outreach"
        described = cli("email", "template", "game-outreach")
        assert described.returncode == 0, described.stderr
        assert "game_summary" in json.loads(described.stdout)["data"]["variables"]
        created = cli(
            "email",
            "enrich",
            "--url",
            "https://example.com/creator",
            "--idempotency-key",
            "e2e-one",
        )
        assert created.returncode == 0, created.stderr
        job_id = json.loads(created.stdout)["data"]["id"]

        def start_worker(phase):
            env = dict(
                os.environ,
                FMG_AGENT_DATABASE_URL=settings.database_url,
                FMG_AGENT_BROKER_URL="redis://127.0.0.1:55440/13",
                FMG_FIXTURE_PHASE=phase,
                FMG_AGENT_SMTP_HOST="127.0.0.1",
                FMG_AGENT_SMTP_PORT=str(smtp_server.server_address[1]),
                FMG_AGENT_SMTP_ENCRYPTION="none",
                FMG_AGENT_SMTP_ALLOW_INSECURE_LOOPBACK="true",
                FMG_AGENT_SMTP_FROM="publisher@example.com",
            )
            output = (tmp_path / f"worker-{phase}.log").open("w")
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("email_worker_fixture.py")),
                ],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            return proc, output

        def wait_state(expected):
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                assert (
                    process.poll() is None
                ), "Worker exited; inspect isolated test log"
                response = cli("email", "job", job_id)
                data = json.loads(response.stdout)["data"]
                if data["state"] == expected:
                    return data
                time.sleep(0.25)
            pytest.fail(f"Job did not reach {expected}")

        process, worker_output = start_worker("fail")
        failed = wait_state("failed")
        assert failed["error"]["code"] == "upstream_rate_limited"
        assert "public_pages" in failed["checkpoints"]
        process.terminate()
        process.wait(timeout=15)
        worker_output.close()
        # Retry while no worker is available, then prove startup discovers it.
        assert cli("email", "retry", job_id).returncode == 0
        process, worker_output = start_worker("resume")
        completed = wait_state("completed")
        assert completed["emails"][0]["email"] == "press@example.com"
        assert completed["checkpoints"]["enrichment"]["usage"]["totalTokenCount"] == 123
        message_file = tmp_path / "preview.json"
        message_file.write_text(
            json.dumps(
                {
                    "template_id": "game-outreach",
                    "template_version": "1",
                    "to": "creator@example.com",
                    "variables": variables(),
                }
            )
        )
        preview_result = cli("email", "preview", "--input", str(message_file))
        assert preview_result.returncode == 0, preview_result.stderr
        preview_id = json.loads(preview_result.stdout)["data"]["id"]
        assert smtp_server.messages == []
        no_confirm = cli(
            "email", "send", "--preview-id", preview_id, "--idempotency-key", "send-one"
        )
        assert no_confirm.returncode == 2
        assert smtp_server.messages == []
        for _ in range(2):
            sent = cli(
                "email",
                "send",
                "--preview-id",
                preview_id,
                "--idempotency-key",
                "send-one",
                "--confirm",
            )
            assert sent.returncode == 0, sent.stderr
            assert json.loads(sent.stdout)["data"]["state"] == "sent"
        assert len(smtp_server.messages) == 1
        smtp_server.mode = "unknown"
        preview_id = json.loads(
            cli("email", "preview", "--input", str(message_file)).stdout
        )["data"]["id"]
        uncertain = cli(
            "email",
            "send",
            "--preview-id",
            preview_id,
            "--idempotency-key",
            "send-two",
            "--confirm",
        )
        assert uncertain.returncode == 7, uncertain.stderr
        send_id = json.loads(uncertain.stdout)["data"]["id"]
        assert cli("email", "receipt", send_id).returncode == 7
        assert len(smtp_server.messages) == 2
        # Batch remains unapproved until explicit CLI start, then worker handles it
        # without any client-side send loop, including repeated starts.
        smtp_server.mode = "sent"
        batch_file = tmp_path / "batch.json"
        batch_file.write_text(json.dumps({"name": "Worker batch", "template_id": "game-outreach",
            "template_version": "1", "recipients": [{"creator_id": name,
                "to": name + "@example.com", "variables": variables()} for name in ("alice", "bob")]}))
        response = cli("outreach", "task", "create", "--input", str(batch_file), "--idempotency-key", "batch")
        assert response.returncode == 0, response.stderr
        batch = json.loads(response.stdout)["data"]
        assert len(smtp_server.messages) == 2
        for _ in range(2):
            started = cli("outreach", "task", "start", batch["id"], "--revision", batch["revision"], "--confirm")
            assert started.returncode == 0, started.stderr
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            current = json.loads(cli("outreach", "task", "get", batch["id"]).stdout)["data"]
            if current["state"] == "completed":
                break
            time.sleep(.25)
        assert current["state"] == "completed", current
        assert current["stats"]["sent"] == 2
        assert len(smtp_server.messages) == 4
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if worker_output is not None:
            worker_output.close()
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)
        listener.close()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
