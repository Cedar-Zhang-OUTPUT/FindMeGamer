"""Offline mailbox association; run with the agent-service Python environment."""

import argparse
import json
import sys
import importlib.util
from pathlib import Path

from sqlalchemy import text

from fmg_agent.config import Settings
from fmg_agent.db import database
from fmg_agent.email.identity import backfill_mailboxes
from fmg_agent.mailboxes import MailboxRegistry

spec = importlib.util.spec_from_file_location(
    "deployment_runtime", Path(__file__).with_name("mail_runtime.py")
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify frozen sender mappings, defaulting to a read-only dry run."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist verified mailbox associations atomically.",
    )
    parser.add_argument(
        "--quiescent",
        action="store_true",
        help="Acknowledge API, workers and monitors are stopped and in-flight delivery has drained. This flag does not verify service state; deployment must independently check it.",
    )
    args = parser.parse_args(argv)
    if args.apply and not args.quiescent:
        parser.error(
            "--apply requires --quiescent after stopping all writers and draining in-flight delivery"
        )
    engine = None
    try:
        settings = runtime.admin_settings()
        registry = MailboxRegistry.load(settings)
        engine, sessions = database(settings)
        if engine.dialect.name != "postgresql":
            raise ValueError("Mailbox deployment preflight requires PostgreSQL")
        context = (
            runtime.cutover_lock(sessions, registry) if args.apply else sessions.begin()
        )
        with context as session:
            if args.apply:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(
                    text(
                        "LOCK TABLE mailbox_identities, email_previews, outreach_tasks, outreach_recipients, email_sends IN ACCESS EXCLUSIVE MODE"
                    )
                )
            outcome = backfill_mailboxes(session, registry, apply=args.apply)
        print(json.dumps(outcome, sort_keys=True))
        return 0
    except Exception:
        # Configuration/driver exceptions may contain credentials. Fail closed.
        print(
            "Mailbox preflight failed; verify configuration, schema and sender mappings offline.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
