"""Offline maintenance administration. No approval, safety or receipt writes."""

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import select, text

from fmg_agent.config import Settings
from fmg_agent.db import database
from fmg_agent.mailboxes import MailboxRegistry
from fmg_agent.mail_runtime import MailRuntime, set_runtime
from fmg_agent.email.identity import backfill_mailboxes

ROLES = ("api", "worker", "mail-worker", "mail-worker-second", "dispatch", "monitor")


def admin_settings():
    path = os.environ.get("FMG_AGENT_ADMIN_ENV_FILE")
    if path and Path(path).stat().st_mode & 0o077:
        raise ValueError("Private admin environment required")
    return Settings(_env_file=path)


def compose(file, *args):
    return subprocess.check_output(
        ["docker", "compose", "-f", str(file), *args],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )


def stopped(file):
    if compose(file, "ps", "--status", "running", "--services").strip():
        raise ValueError("All legacy producers and consumers must be stopped")


def status(session):
    row = session.get(MailRuntime, 1)
    if row is None:
        raise ValueError("Runtime singleton missing")
    result = {
        "dispatch_enabled": row.dispatch_enabled,
        "send_enabled": row.send_enabled,
    }
    for table in (
        "email_jobs",
        "email_sends",
        "email_bounce_retries",
        "outreach_tasks",
    ):
        result[table] = dict(
            session.execute(
                text(f"SELECT state, count(*) FROM {table} GROUP BY state")
            ).all()
        )
    result["send_leases"] = session.scalar(
        text("SELECT count(*) FROM email_send_gates WHERE lease_id IS NOT NULL")
    )
    result["schema"] = session.scalar(text("SELECT version_num FROM alembic_version"))
    return result


@contextmanager
def cutover_lock(sessions, registry):
    """Fail, never kill/recover, if a current or legacy sender is still active."""
    with sessions() as session:
        if session.get_bind().dialect.name != "postgresql":
            raise ValueError("PostgreSQL required")
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        row = session.scalar(
            select(MailRuntime).where(MailRuntime.id == 1).with_for_update(nowait=True)
        )
        if row is None or row.dispatch_enabled or row.send_enabled:
            raise ValueError("Both maintenance gates must be closed")
        state = status(session)
        if (
            state["email_sends"].get("sending", 0)
            or state["email_jobs"].get("running", 0)
            or state["send_leases"]
        ):
            raise ValueError("In-flight work or unresolved send lease prevents cutover")
        senders = set(session.scalars(text("SELECT sender FROM mailbox_identities")))
        senders.update(
            p.smtp_from.casefold() for p in registry.profiles() if p.smtp_from
        )
        for sender in senders:
            key = int.from_bytes(
                sha256(("fmg-email:" + sender).encode()).digest()[:8],
                "big",
                signed=True,
            )
            if not session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}
            ):
                raise ValueError("Live sender prevents cutover")
        yield session
        session.commit()


def ready(session, registry):
    if (
        session.scalar(text("SELECT version_num FROM alembic_version"))
        != "0013_mail_runtime"
    ):
        raise ValueError("Schema mismatch")
    result = backfill_mailboxes(session, registry)
    if result["previews"] or result["tasks"] or not result["unchanged"]:
        raise ValueError("Identity backfill required")
    profiles = [p for p in registry.profiles() if p.enabled]
    if not profiles or any(p.email_send_interval_seconds != 5 for p in profiles):
        raise ValueError("Enabled mailboxes require the approved five-second interval")


def legacy_drained(broker, *, prefix="fmg_agent:"):
    keys = [
        prefix + "fmg_agent" + suffix
        for suffix in ("", "\x06\x163", "\x06\x166", "\x06\x169")
    ]
    if (
        any(broker.llen(key) for key in keys)
        or broker.hlen(prefix + "unacked")
        or broker.zcard(prefix + "unacked_index")
    ):
        raise ValueError("Legacy migration or broker drain is incomplete")


def verify_roles(file, registry):
    profiles = [p for p in registry.profiles() if p.enabled]
    if len(profiles) > 2:
        raise ValueError("Compose supports at most two mailboxes")
    expected = {"api", "worker", "mail-worker", "dispatch", "monitor"}
    if len(profiles) == 2:
        expected.add("mail-worker-second")
    running = set(compose(file, "ps", "--status", "running", "--services").split())
    if running != expected:
        raise ValueError("Missing or unexpected running roles")
    compose(
        file,
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=5)",
    )
    probes = [("worker", "enrichment", None), ("dispatch", "dispatch", None)]
    for service, profile in zip(("mail-worker", "mail-worker-second"), profiles):
        probes.extend(
            [(service, "mail", profile.id), ("monitor", "monitor", profile.id)]
        )
    reports = []
    for service, role, mailbox in probes:
        command = ["exec", "-T", service, "python", "-m", "fmg_agent.role_health", role]
        if mailbox:
            command += ["--mailbox", mailbox]
        reports.append(json.loads(compose(file, *command)))
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "status",
            "hold",
            "release",
            "check-cutover",
            "check-legacy-rollback",
            "readiness",
        ],
    )
    parser.add_argument(
        "--compose-file", default=str(Path(__file__).with_name("compose.yaml"))
    )
    args = parser.parse_args(argv)
    engine = None
    try:
        settings = admin_settings()
        engine, sessions = database(settings)
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgreSQL required")
        if args.action == "hold":
            # Waiting for shared sender locks is intentional. Never a forced kill.
            result = set_runtime(sessions, dispatch_enabled=False, send_enabled=False)
        elif args.action == "status":
            with sessions() as session:
                result = status(session)
        else:
            registry = MailboxRegistry.load(settings)
            with cutover_lock(sessions, registry) as session:
                if args.action == "check-legacy-rollback":
                    identities = set(
                        session.scalars(text("SELECT id FROM mailbox_identities"))
                    )
                    if identities - {"ontologyplay"} or any(
                        p.id != "ontologyplay" and p.enabled
                        for p in registry.profiles()
                    ):
                        raise ValueError(
                            "Legacy worker cannot own second mailbox history"
                        )
                elif args.action in ("release", "readiness"):
                    ready(session, registry)
                    verify_roles(args.compose_file, registry)
                    import redis

                    with redis.Redis.from_url(
                        settings.broker_url.get_secret_value(), socket_timeout=5
                    ) as broker:
                        legacy_drained(broker)
                    if args.action == "release":
                        row = session.get(MailRuntime, 1)
                        row.dispatch_enabled = row.send_enabled = True
                result = {"action": args.action, "ok": True}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(
            "Runtime operation refused; verify held gates, drained work, identity/schema and fresh role readiness. No safety/approval reset was performed.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
