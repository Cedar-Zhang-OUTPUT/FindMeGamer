"""One connection-owned dispatcher; all publication leaves durable work pending."""

from contextlib import contextmanager
from itertools import zip_longest
import logging
from threading import Event

from sqlalchemy import text
from kombu import Queue

from .config import Settings
from .db import database
from .email.jobs import JobStore
from .email.monitor import mailbox_leader, leader_sessions
from .email.retries import pending_retries
from .errors import ApiError
from .mailboxes import MailboxRegistry
from .mail_runtime import check_readiness, runtime_gate
from .outreach import pending
from .worker import create_worker, queue_for_mailbox
from . import role_health


@contextmanager
def dispatch_leader(engine):
    with mailbox_leader(engine, "__dispatch__") as owner:
        yield owner


def dispatch_once(settings, sessions, publish) -> dict:
    registry = MailboxRegistry.load(settings)
    counts = {
        "fmg_enrichment": 0,
        **{queue_for_mailbox(p.id): 0 for p in registry.profiles() if p.enabled},
    }
    try:
        with runtime_gate(sessions) as check:
            store = JobStore(sessions)
            store.recover_expired()
            store.cleanup(settings.email_retention_days)

            def emit(task, identifier, queue):
                check()
                publish(task, identifier, queue)
                counts[queue] += 1

            for job_id in store.pending(limit=20):
                emit("fmg_agent.email.enrich", job_id, "fmg_enrichment")
            for profile in registry.profiles():
                if not profile.enabled:
                    continue
                queue = queue_for_mailbox(profile.id)
                retries = pending_retries(sessions, mailbox_id=profile.id)
                recipients = pending(sessions, mailbox_id=profile.id)
                for retry, recipient in zip_longest(retries, recipients):
                    for task, identifier in (
                        ("fmg_agent.email.bounce_retry", retry),
                        ("fmg_agent.outreach.send", recipient),
                    ):
                        if identifier is not None and counts[queue] < 20:
                            emit(task, identifier, queue)
    except ApiError as exc:
        if exc.code != "mail_service_maintenance":
            raise
    return counts


def run_dispatch(settings, stop):
    engine, sessions = database(settings)
    publisher = create_worker(settings)

    def publish(task, identifier, queue):
        publisher.send_task(task, args=[identifier], queue=queue, expires=60)

    try:
        registry = check_readiness(settings, sessions)
        publisher.conf.task_queues = (
            Queue("fmg_enrichment"),
            *(
                Queue(queue_for_mailbox(profile.id))
                for profile in registry.profiles()
                if profile.enabled
            ),
        )
        while not stop.is_set():
            try:
                with dispatch_leader(engine) as owner:
                    if owner is not None:
                        fenced = leader_sessions(owner)
                        while not stop.is_set():
                            owner.execute(text("SELECT 1"))
                            owner.commit()
                            dispatch_once(settings, fenced, publish)
                            role_health.record(settings, "dispatch")
                            if stop.wait(10):
                                break
            except Exception:
                role_health.clear(settings, "dispatch")
                logging.getLogger(__name__).warning(
                    "Dispatch unavailable; durable pending work retained."
                )
            stop.wait(10)
    finally:
        role_health.clear(settings, "dispatch")
        publisher.close()
        engine.dispose()


def main():
    import signal

    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    run_dispatch(Settings(), stop)


if __name__ == "__main__":
    main()
