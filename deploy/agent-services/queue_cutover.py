"""Read-only legacy queue audit and explicit, recoverable exact-message migration."""

import argparse
import base64
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import importlib.util

import redis
from sqlalchemy import text

from fmg_agent.config import Settings
from fmg_agent.db import database
from fmg_agent.mailboxes import MailboxRegistry

TASKS = {
    "fmg_agent.email.enrich",
    "fmg_agent.outreach.send",
    "fmg_agent.email.bounce_retry",
}

spec = importlib.util.spec_from_file_location(
    "deployment_runtime", Path(__file__).with_name("mail_runtime.py")
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def decode_message(raw):
    result = {"recognized": False, "task": "malformed", "id": None, "identifier": None}
    try:
        message = json.loads(raw)
        result.update(task=message["headers"]["task"], id=message["headers"]["id"])
        body = json.loads(base64.b64decode(message["body"], validate=True))
        args, kwargs, embed = body
        if (
            result["task"] in TASKS
            and isinstance(args, list)
            and len(args) == 1
            and isinstance(args[0], str)
            and not kwargs
            and isinstance(embed, dict)
            and not any(
                embed.get(k) for k in ("callbacks", "errbacks", "chain", "chord")
            )
        ):
            result.update(recognized=True, identifier=args[0])
    except (ValueError, KeyError, TypeError):
        pass
    return result


def queue_keys(prefix):
    return [
        prefix + "fmg_agent" + suffix
        for suffix in ("", "\x06\x163", "\x06\x166", "\x06\x169")
    ]


def checksum(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def binding(broker, session):
    connection = broker.connection_pool.connection_kwargs
    return checksum(
        {
            "database": session.get_bind().url.render_as_string(hide_password=False),
            "schema": session.scalar(text("SELECT current_schema()")),
            "broker": {
                key: str(connection.get(key)) for key in ("host", "port", "db", "path")
            },
        }
    )


def audit(broker, session, *, prefix="fmg_agent:"):
    messages = []
    # MULTI/EXEC gives one consistent broker snapshot without consuming anything.
    pipe = broker.pipeline(transaction=True)
    keys = queue_keys(prefix)
    for key in keys:
        pipe.lrange(key, 0, -1)
    pipe.hgetall(prefix + "unacked")
    pipe.zrange(prefix + "unacked_index", 0, -1, withscores=True)
    values = pipe.execute()
    for key, entries in zip(keys, values[:4]):
        for raw in entries:
            messages.append(
                dict(decode_message(raw), key=key, raw=base64.b64encode(raw).decode())
            )
    result = {
        "version": 1,
        "prefix": prefix,
        "binding": binding(broker, session),
        "messages": messages,
        "recognized": sum(m["recognized"] for m in messages),
        "unknown": sum(not m["recognized"] for m in messages),
        "types": dict(Counter(m["task"] for m in messages)),
        "unacked": {
            base64.b64encode(k).decode(): base64.b64encode(v).decode()
            for k, v in values[4].items()
        },
        "unacked_index": [
            (base64.b64encode(k).decode(), score) for k, score in values[5]
        ],
        "database": runtime.status(session),
    }
    result["sha256"] = checksum(result)
    return result


def route(session, registry, message):
    from sqlalchemy import select
    from fmg_agent.db import AccessToken
    from fmg_agent.email.models import (
        EmailJob,
        EmailPreview,
        EmailSend,
        EmailBounceRetry,
    )
    from fmg_agent.email import safety, retries
    from fmg_agent.email.jobs import utcnow
    from fmg_agent.outreach import OutreachTask, OutreachRecipient
    from fmg_agent.worker import queue_for_mailbox

    identifier = message["identifier"]
    if message["task"] == "fmg_agent.email.enrich":
        job = session.get(EmailJob, identifier)
        token = session.get(AccessToken, job.token_id) if job else None
        return (
            "fmg_enrichment"
            if job and job.state == "queued" and token and not token.revoked_at
            else None
        )
    if message["task"] == "fmg_agent.outreach.send":
        recipient = session.get(OutreachRecipient, identifier)
        if not recipient:
            return None
        task = session.get(OutreachTask, recipient.task_id)
        if task.state != "sending":
            return None
        preview = session.get(EmailPreview, recipient.preview_id)
        if task.mailbox_id != preview.mailbox_id:
            raise ValueError("Task identity mismatch")
    else:
        retry = session.get(EmailBounceRetry, identifier)
        if (
            not retry
            or retry.state != "queued"
            or retries.aware(retry.due_at) > utcnow()
        ):
            return None
        original = session.get(EmailSend, identifier)
        if original.state != "sent":
            return None
        task = session.scalar(
            select(OutreachTask)
            .join(OutreachRecipient)
            .where(OutreachRecipient.preview_id == original.preview_id)
        )
        if task and task.state != "sending":
            return None
        preview = session.get(EmailPreview, retry.preview_id)
        from fmg_agent.errors import ApiError

        try:
            retries.preflight(session, preview.id, "bounce-retry:" + identifier)
        except ApiError:
            return None
    if session.scalar(select(EmailSend.id).where(EmailSend.preview_id == preview.id)):
        return None  # Includes unknown and every prior attempt; never replay it.
    token = session.get(AccessToken, preview.token_id)
    if not token or token.revoked_at or "email:send" not in token.scopes:
        return None
    profile = next((p for p in registry.profiles() if p.id == preview.mailbox_id), None)
    if not profile or not profile.enabled:
        return None
    sender = preview.message["from"].casefold()
    if safety.status(session, sender)["reason"] or safety.recipient_invalid(
        session, sender, preview.message["to"]
    ):
        return None
    return queue_for_mailbox(profile.id)


def private_write(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def journal(path, data):
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "a") as stream:
        stream.write(json.dumps(data, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def migrate(broker, sessions, registry, manifest, publish, progress):
    content = {k: v for k, v in manifest.items() if k != "sha256"}
    if manifest.get("version") != 1 or checksum(content) != manifest.get("sha256"):
        raise ValueError("Invalid snapshot checksum/version")
    if manifest["unknown"] or manifest["unacked"] or manifest["unacked_index"]:
        raise ValueError("Unknown or unacknowledged messages prevent migration")
    prefix = manifest["prefix"]
    allowed = queue_keys(prefix)
    decoded = []
    for item in manifest["messages"]:
        raw = base64.b64decode(item["raw"], validate=True)
        message = decode_message(raw)
        if item["key"] not in allowed or not message["recognized"]:
            raise ValueError("Snapshot contains unsupported message")
        decoded.append((item["key"], raw, message))
    result = {"published": 0, "retained_db": 0, "already_absent": 0}
    with runtime.cutover_lock(sessions, registry) as session:
        runtime.ready(session, registry)
        if manifest["binding"] != binding(broker, session):
            raise ValueError("Snapshot belongs to a different database/broker")
        current = audit(broker, session, prefix=prefix)
        if current["unknown"] or current["unacked"] or current["unacked_index"]:
            raise ValueError("Broker is not drained")
        original_counts = Counter((key, raw) for key, raw, _ in decoded)
        live_counts = Counter(
            (m["key"], base64.b64decode(m["raw"])) for m in current["messages"]
        )
        if live_counts - original_counts:
            raise ValueError("Queue changed since audit; stop all producers first")
        for key, raw, message in decoded:
            if not live_counts[(key, raw)]:
                result["already_absent"] += 1
                continue
            destination = route(session, registry, message)
            entry = {
                "message_sha256": sha256(raw).hexdigest(),
                "task": message["task"],
                "identifier": message["identifier"],
                "queue": destination,
            }
            journal(progress, dict(entry, stage="pending-reconciliation"))
            if destination:
                publish(message["task"], message["identifier"], destination)
            # The exact audited bytes, one occurrence. No purge or broad delete.
            if broker.lrem(key, 1, raw) != 1:
                raise ValueError("Exact acknowledgement failed; reconcile journal")
            journal(progress, dict(entry, stage="acknowledged"))
            live_counts[(key, raw)] -= 1
            result["published" if destination else "retained_db"] += 1
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit", "migrate"])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--prefix", default="fmg_agent:")
    parser.add_argument(
        "--compose-file", default=str(Path(__file__).with_name("compose.yaml"))
    )
    args = parser.parse_args(argv)
    engine = publisher = broker = None
    try:
        settings = runtime.admin_settings()
        engine, sessions = database(settings)
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgreSQL required")
        broker = redis.Redis.from_url(
            settings.broker_url.get_secret_value(), socket_timeout=10
        )
        if args.action == "audit":
            with sessions() as session:
                report = audit(broker, session, prefix=args.prefix)
            if args.manifest:
                private_write(args.manifest, report)
            # Raw payloads are private artifacts, never dumped to a terminal.
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in report.items()
                        if k not in {"messages", "unacked", "unacked_index"}
                    },
                    sort_keys=True,
                )
            )
            print(
                json.dumps(
                    {
                        "task_ids": {
                            task: [
                                m["identifier"]
                                for m in report["messages"]
                                if m["task"] == task
                            ]
                            for task in TASKS
                        },
                        "unacked_count": len(report["unacked"]),
                    }
                )
            )
            return (
                1
                if report["unknown"] or report["unacked"] or report["unacked_index"]
                else 0
            )
        if (
            not args.confirm
            or not args.manifest
            or args.manifest.stat().st_mode & 0o077
        ):
            raise ValueError(
                "Explicit confirmation and private audited snapshot required"
            )
        manifest = json.loads(args.manifest.read_text())
        if args.prefix != manifest["prefix"]:
            raise ValueError("Prefix mismatch")
        runtime.stopped(args.compose_file)
        from fmg_agent.worker import create_worker, queue_for_mailbox
        from kombu import Queue

        registry = MailboxRegistry.load(settings)
        publisher = create_worker(settings)
        publisher.conf.task_queues = (
            Queue("fmg_enrichment"),
            *(Queue(queue_for_mailbox(p.id)) for p in registry.profiles() if p.enabled),
        )
        publisher.conf.broker_transport_options["global_keyprefix"] = args.prefix

        def publish(task, identifier, queue):
            publisher.send_task(task, args=[identifier], queue=queue)

        result = migrate(
            broker,
            sessions,
            registry,
            manifest,
            publish,
            args.manifest.with_suffix(".progress.jsonl"),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(
            "Queue operation refused or interrupted; retain snapshot and reconcile its progress journal before retrying. No bulk queue deletion was performed.",
            file=sys.stderr,
        )
        return 1
    finally:
        if publisher is not None:
            publisher.close()
        if broker is not None:
            broker.close()
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
