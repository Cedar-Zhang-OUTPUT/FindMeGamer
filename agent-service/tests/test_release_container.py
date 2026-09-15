"""Opt-in local image, CLI, migration and backup/restore rehearsal. No upstream calls."""

import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import urllib.request

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.postgres
def test_local_release_image_and_restore(tmp_path):
    if os.environ.get("FMG_AGENT_TEST_IMAGE") != "fmg-agent:predeploy":
        pytest.skip(
            "Opt in with locally built FMG_AGENT_TEST_IMAGE=fmg-agent:predeploy"
        )
    url = os.environ["FMG_AGENT_TEST_DATABASE_URL"]
    engine = create_engine(url)
    assert engine.url.host == "127.0.0.1"
    assert engine.url.database == "find_me_gamer_agent_test"
    suffix = uuid.uuid4().hex
    schema = "release_test_" + suffix
    api, worker = "fmg-release-api-" + suffix, "fmg-release-worker-" + suffix
    db_container = "fmg-agent-tests-postgres-1"
    image = "fmg-agent:predeploy"

    def run(*args, **kwargs):
        return subprocess.run(args, check=True, capture_output=True, **kwargs)

    env = [
        "-e",
        "FMG_AGENT_DATABASE_URL=postgresql+psycopg://fmg_agent_test:local-test-only@postgres:5432/find_me_gamer_agent_test",
        "-e",
        f"PGOPTIONS=-c search_path={schema}",
        "-e",
        "FMG_AGENT_BROKER_URL=redis://redis:6379/14",
    ]
    common = ["docker", "run", "--network", "fmg-agent-tests_default", *env]
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        for _ in range(2):
            run(*common, "--rm", image, "python", "-m", "alembic", "upgrade", "head")
        token = json.loads(
            run(
                *common,
                "--rm",
                image,
                "python",
                "-m",
                "fmg_agent.admin",
                "token",
                "create",
                "--label",
                "release-test",
                "--scope",
                "read",
            ).stdout
        )
        run(*common, "-d", "--name", api, "-p", "127.0.0.1::8000", image)
        run(*common, "-d", "--name", worker, image, "python", "-m", "fmg_agent.worker")
        port = (
            run("docker", "port", api, "8000/tcp")
            .stdout.decode()
            .strip()
            .split(":")[-1]
        )
        server = f"http://127.0.0.1:{port}"
        for attempt in range(40):
            try:
                with urllib.request.urlopen(
                    server + "/v1/health", timeout=1
                ) as response:
                    assert response.status == 200
                break
            except OSError:
                if attempt == 39:
                    raise
                time.sleep(0.25)
        config = tmp_path / "cli.json"
        config.write_text(json.dumps({"server": server, "token": token["token"]}))
        config.chmod(0o600)
        smoke = run(
            "sh",
            str(ROOT / "deploy/agent-services/smoke.sh"),
            server,
            env=dict(os.environ, FMG_CONFIG=str(config), FMG_BIN=str(ROOT / "cli/fmg")),
        )
        assert b"configuration smoke passed" in smoke.stdout
        # A private URL is rejected locally: proves actual queue processing without
        # a paid provider call or any public-site request.
        create_job = (
            "from fmg_agent.config import Settings; from fmg_agent.db import database; "
            "from fmg_agent.email.jobs import JobStore; "
            "engine,sessions=database(Settings()); "
            f'JobStore(sessions).create({token["id"]!r},"release-worker-test",{{"url":"http://127.0.0.1/private"}})'
        )
        run(*common, "--rm", image, "python", "-c", create_job)
        for attempt in range(80):
            with engine.connect() as conn:
                state = conn.scalar(text(f'SELECT state FROM "{schema}".email_jobs'))
            if state == "failed":
                break
            time.sleep(0.25)
        assert state == "failed"
        assert (
            run("docker", "inspect", "--format", "{{.Config.User}}", api).stdout.strip()
            == b"agent"
        )
        run("docker", "stop", "-t", "5", api, worker)
        dump = run(
            "docker",
            "exec",
            db_container,
            "pg_dump",
            "-U",
            "fmg_agent_test",
            "-d",
            "find_me_gamer_agent_test",
            "-Fc",
            "--no-owner",
            "--no-acl",
            "--schema",
            schema,
        ).stdout
        assert dump.startswith(b"PGDMP")
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        run(
            "docker",
            "exec",
            "-i",
            db_container,
            "pg_restore",
            "-U",
            "fmg_agent_test",
            "-d",
            "find_me_gamer_agent_test",
            "--no-owner",
            "--no-acl",
            input=dump,
        )
        with engine.connect() as conn:
            assert (
                conn.scalar(text(f'SELECT count(*) FROM "{schema}".access_tokens')) == 1
            )
            assert conn.scalar(text(f'SELECT count(*) FROM "{schema}".email_jobs')) == 1
            assert (
                conn.scalar(text(f'SELECT version_num FROM "{schema}".alembic_version'))
                == "0004_usage"
            )
    finally:
        for name in (api, worker):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
