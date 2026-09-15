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


@pytest.mark.postgres
def test_cli_email_worker_restart(tmp_path):
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
            ).render_as_string(hide_password=False)
        )
        app = create_app(settings)
        with app.state.sessions() as session:
            token = issue_token(session, label="e2e", scopes=["email:enrich"])
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
