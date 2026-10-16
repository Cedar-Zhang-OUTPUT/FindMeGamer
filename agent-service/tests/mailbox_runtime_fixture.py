"""Test-only process factory. No production test endpoints or transport switches.

Only virtual upstream mail/model calls are replaced. HTTP, CLI, database locks,
Celery prefork workers, dispatcher and monitor processes are real.
"""

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest
import redis
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def until(predicate, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"Condition did not complete within {timeout}s")


class Runtime:
    def __init__(self, directory):
        from fmg_agent.config import Settings
        from fmg_agent.db import database
        from fmg_agent.auth import issue_token
        from fmg_agent.mail_runtime import check_readiness, set_runtime
        from test_migrations import migrate

        self.directory = directory
        self.processes = []
        self.outputs = []
        dsn = os.environ["FMG_AGENT_TEST_DATABASE_URL"]
        self.broker = os.environ["FMG_AGENT_TEST_REDIS_URL"]
        self.redis = redis.Redis.from_url(self.broker, decode_responses=True)
        assert self.redis.connection_pool.connection_kwargs["host"] == "127.0.0.1"
        assert self.redis.connection_pool.connection_kwargs["db"] == 14
        assert self.redis.ping()
        self.admin = create_engine(dsn)
        assert self.admin.url.host == "127.0.0.1"
        assert self.admin.url.database == "find_me_gamer_agent_test"
        self.schema = "mailbox_acceptance_" + uuid4().hex
        self.prefix = self.schema + ":"
        self.binary = str(Path(os.environ["FMG_AGENT_TEST_CLI"]).resolve())
        with self.admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.dsn = self.admin.url.set(
            query={"options": f"-c search_path={self.schema}"}
        ).render_as_string(hide_password=False)
        migrated = migrate(dsn, self.schema)
        assert migrated.returncode == 0, migrated.stderr
        self.profiles = [
            {
                "id": name,
                "display_name": name.title(),
                "smtp_from": name + "@example.com",
                "smtp_host": "virtual.invalid",
                "smtp_username": "virtual",
                "smtp_password": "virtual",
                "imap_host": "virtual.invalid",
                "imap_username": name + "@example.com",
                "imap_password": "virtual",
                "allowed_templates": ["game-outreach"],
                "email_send_interval_seconds": 5,
            }
            for name in ("alpha", "beta")
        ]
        self.profile_path = directory / "mailboxes.json"
        self.save_profiles()
        self.settings = Settings(
            database_url=self.dsn,
            broker_url=self.broker,
            mailboxes_file=self.profile_path,
        )
        self.engine, self.sessions = database(self.settings)
        check_readiness(self.settings, self.sessions)
        set_runtime(self.sessions, dispatch_enabled=True, send_enabled=True)
        self.tokens = {}
        with self.sessions() as session:
            for agent in ("a", "b"):
                self.tokens[agent] = issue_token(
                    session, label=agent, scopes=["email:send", "email:enrich", "read"]
                ).token
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = dict(
            {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("FMG_AGENT_")
            },
            FMG_AGENT_DATABASE_URL=self.dsn,
            FMG_AGENT_BROKER_URL=self.broker,
            FMG_AGENT_MAILBOXES_FILE=str(self.profile_path),
            FMG_FIXTURE_PREFIX=self.prefix,
            FMG_FIXTURE_PORT=str(self.port),
            PYTHONPATH=str(ROOT / "src"),
        )
        self.spawn("api")

        def healthy():
            try:
                return (
                    httpx.get(self.url + "/v1/health", trust_env=False).status_code
                    == 200
                )
            except httpx.TransportError:
                return False

        until(healthy, 20)
        for agent in ("a", "b"):
            (self.directory / agent).mkdir()
            self.login(agent)
        self.spawn("enrichment")
        self.spawn("mail", "alpha")
        self.spawn("mail", "beta")
        self.spawn("monitor")
        self.spawn("dispatch")
        until(lambda: self.redis.scard(self.prefix + "ready") == 5, 30)

    def save_profiles(self):
        self.profile_path.write_text(json.dumps({"mailboxes": self.profiles}))
        self.profile_path.chmod(0o600)

    def spawn(self, role, mailbox=""):
        output = (self.directory / f"{role}-{mailbox}-{len(self.processes)}.log").open(
            "w"
        )
        env = self.env
        if role == "api" and os.environ.get("FMG_FIXTURE_BASELINE_SRC"):
            env = dict(
                env,
                PYTHONPATH=os.environ["FMG_FIXTURE_BASELINE_SRC"],
                FMG_AGENT_SMTP_FROM="alpha@example.com",
            )
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), role, mailbox],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes.append(proc)
        self.outputs.append(output)
        return proc

    def login(self, agent):
        result = self.run_cli(
            agent,
            ["auth", "login", "--server", self.url, "--token-stdin"],
            stdin=self.tokens[agent],
        )
        assert result.returncode == 0, result.stderr

    def share_token(self):
        self.tokens["b"] = self.tokens["a"]
        self.login("b")

    def run_cli(self, agent, args, stdin=""):
        result = subprocess.run(
            [self.binary, *args],
            input=stdin,
            text=True,
            capture_output=True,
            env=dict(self.env, FMG_CONFIG=str(self.directory / agent / "config.json")),
            timeout=90,
        )
        assert all(
            token not in result.stdout + result.stderr for token in self.tokens.values()
        )
        return result

    @staticmethod
    def data(result):
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)["data"]

    @staticmethod
    def error(result):
        return json.loads(result.stdout or result.stderr)["error"]["code"]

    def create(self, agent, mailbox, key=None, count=1, raw=False):
        from test_mailbox_outreach import payload

        body = payload(mailbox)
        body["recipients"] = [
            dict(
                body["recipients"][0],
                creator_id=f"creator-{i}",
                to=f"creator-{i}@example.com",
            )
            for i in range(count)
        ]
        path = self.directory / (uuid4().hex + ".json")
        path.write_text(json.dumps(body))
        result = self.run_cli(
            agent,
            [
                "outreach",
                "task",
                "create",
                "--input",
                str(path),
                "--idempotency-key",
                key or uuid4().hex,
            ],
        )
        return result if raw else self.data(result)

    def start(self, agent, task):
        return self.data(
            self.run_cli(
                agent,
                [
                    "outreach",
                    "task",
                    "start",
                    task["id"],
                    "--revision",
                    task["revision"],
                    "--confirm",
                ],
            )
        )

    def get(self, agent, task):
        return self.data(self.run_cli(agent, ["outreach", "task", "get", task["id"]]))

    def completed(self, agent, task, timeout=90):
        return until(
            lambda: (
                data
                if (data := self.get(agent, task))["state"] == "completed"
                else None
            ),
            timeout,
        )

    def send(self, agent, preview, key):
        return self.run_cli(
            agent,
            [
                "email",
                "send",
                "--preview-id",
                preview,
                "--idempotency-key",
                key,
                "--confirm",
            ],
        )

    def provider_calls(self, mailbox):
        return [
            json.loads(item)
            for item in self.redis.lrange(self.prefix + "calls:" + mailbox, 0, -1)
        ]

    def publish(self, task, identifier, mailbox=None, expires=60):
        from fmg_agent.worker import create_worker, queue_for_mailbox
        from kombu import Queue

        worker = create_worker(
            self.settings, role="mail" if mailbox else "enrichment", mailbox_id=mailbox
        )
        queue = queue_for_mailbox(mailbox) if mailbox else "fmg_enrichment"
        worker.conf.task_queues = (Queue(queue),)
        worker.conf.broker_transport_options["global_keyprefix"] = self.prefix
        worker.send_task(task, args=[identifier], queue=queue, expires=expires)
        worker.close()

    def block_enrichment(self):
        self.redis.set(self.prefix + "block_enrichment", "1")

    def release_enrichment(self):
        self.redis.delete(self.prefix + "block_enrichment")

    def drained(self):
        return not any(
            self.redis.llen(self.prefix + queue)
            for queue in ("fmg_enrichment", "fmg_mail.alpha", "fmg_mail.beta")
        ) and not self.redis.hlen(self.prefix + "unacked")

    def enrich(self, count):
        return [
            self.data(
                self.run_cli(
                    "a",
                    [
                        "email",
                        "enrich",
                        "--url",
                        f"https://example.com/{uuid4().hex}",
                        "--idempotency-key",
                        uuid4().hex,
                    ],
                )
            )["id"]
            for _ in range(count)
        ]

    def close(self):
        if hasattr(self, "prefix"):
            self.release_enrichment()
            self.redis.delete(self.prefix + "block_mail")
        for proc in reversed(self.processes):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in self.processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        for output in self.outputs:
            output.close()
        if hasattr(self, "engine"):
            self.engine.dispose()
        if hasattr(self, "schema"):
            with self.admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))
            self.admin.dispose()
            keys = list(self.redis.scan_iter(match=self.prefix + "*"))
            if keys:
                self.redis.delete(*keys)


@pytest.fixture
def mailbox_runtime(tmp_path):
    runtime = Runtime.__new__(Runtime)
    try:
        runtime.__init__(tmp_path)
        yield runtime
    finally:
        runtime.close()


def process_main():
    if sys.argv[1] == "api" and os.environ.get("FMG_FIXTURE_BASELINE_SRC"):
        import uvicorn
        from fmg_agent.app import create_app

        uvicorn.run(
            create_app(),
            host="127.0.0.1",
            port=int(os.environ["FMG_FIXTURE_PORT"]),
            log_level="warning",
        )
        return
    from fmg_agent.config import Settings
    from fmg_agent.db import database
    from fmg_agent.mail_runtime import check_readiness
    from fmg_agent import worker as workers
    from fmg_agent.email import smtp
    from fmg_agent.email.enrichment import Enricher
    from fmg_agent.email.public_pages import PublicPage
    from celery.signals import worker_ready

    settings = Settings()
    prefix = os.environ["FMG_FIXTURE_PREFIX"]
    broker = redis.Redis.from_url(
        settings.broker_url.get_secret_value(), decode_responses=True
    )
    role, mailbox = sys.argv[1:3]

    def virtual_mail(config, message, send_id):
        identity = message["from"].split("@")[0]
        started = time.time()
        call = {
            "id": send_id,
            "mailbox": identity,
            "pid": os.getpid(),
            "start": started,
            "to": message["to"],
        }
        broker.rpush(prefix + "entered:" + identity, json.dumps(call))
        while broker.exists(prefix + "block_mail"):
            time.sleep(0.05)
        mode = broker.get(prefix + "mode:" + identity) or "sent"
        call["end"] = time.time()
        broker.rpush(prefix + "calls:" + identity, json.dumps(call))
        if mode == "crash":
            os._exit(91)
        if mode == "429":
            return {"state": "failed", "code": "graph_rate_limited"}
        return {"state": "sent", "code": None}

    class Pages:
        def fetch_page(self, url):
            return PublicPage(url, "<p>Gaming creator</p>", "text/html")

    class Gemini:
        def find(self, target):
            broker.rpush(prefix + "enrich_entered", str(os.getpid()))
            while broker.exists(prefix + "block_enrichment"):
                time.sleep(0.05)
            delay = float(broker.get(prefix + "enrich_delay") or 0)
            time.sleep(delay)
            return {"emails": [], "usage": {"totalTokenCount": 0}}

    original = workers.create_worker

    def create_worker(*args, **kwargs):
        kwargs["enricher_factory"] = lambda: Enricher(Pages(), Gemini())
        app = original(*args, **kwargs)
        app.conf.broker_transport_options["global_keyprefix"] = prefix
        return app

    workers.create_worker = create_worker
    smtp.deliver = virtual_mail
    engine, sessions = database(settings)
    check_readiness(settings, sessions)
    engine.dispose()
    if role == "api":
        import uvicorn
        from fmg_agent.app import create_app

        app = create_app(settings)
        app.state.smtp_transport = virtual_mail
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=int(os.environ["FMG_FIXTURE_PORT"]),
            log_level="warning",
        )
    elif role in {"enrichment", "mail"}:

        @worker_ready.connect(weak=False)
        def ready(**kwargs):
            broker.sadd(prefix + "ready", role + mailbox)

        worker = create_worker(settings, role=role, mailbox_id=mailbox or None)
        worker.worker_main(
            [
                *workers.worker_args(role, mailbox or None),
                "--without-gossip",
                "--without-mingle",
                "--hostname=" + role + mailbox + "@%h",
            ]
        )
    else:
        broker.sadd(prefix + "ready", role)
        if role == "dispatch":
            from fmg_agent.dispatch import main
        elif role == "monitor":
            # Exercise real sync/cursor/readiness code against an empty local
            # IMAP protocol substitute; never open a provider connection.
            from fmg_agent.email import inbox

            class VirtualIMAP:
                def __init__(self, host, port, **kwargs):
                    assert host == "virtual.invalid" and port == 993

                def login(self, username, password):
                    assert username in {"alpha@example.com", "beta@example.com"}
                    assert password == "virtual"

                def list(self):
                    return "OK", []

                def select(self, folder, *, readonly):
                    assert folder == '"INBOX"' and readonly
                    return "OK", [b"0"]

                def response(self, name):
                    assert name == "UIDVALIDITY"
                    return name, [b"1"]

                def uid(self, action, *args):
                    assert action == "search"
                    return "OK", [b""]

                def logout(self):
                    return "BYE", []

            inbox.imaplib.IMAP4_SSL = VirtualIMAP
            from fmg_agent.email.monitor import main
        else:
            raise ValueError(role)
        main()


if __name__ == "__main__":
    process_main()
