"""Explicit enrichment and per-mailbox Celery consumers; no embedded loops."""

import argparse
import re

from celery import Celery
from kombu import Queue

from .config import Settings
from .db import database
from .email.enrichment import Enricher, run_job
from .email.gemini import GeminiGateway
from .email.jobs import JobStore
from .email.public_pages import PublicPageGateway
from .mailboxes import MailboxRegistry
from .mail_runtime import check_readiness


def queue_for_mailbox(mailbox_id: str) -> str:
    if not isinstance(mailbox_id, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,39}", mailbox_id
    ):
        raise ValueError("A valid mailbox ID is required")
    return f"fmg_mail.{mailbox_id}"


def worker_args(role: str, mailbox_id: str | None) -> list[str]:
    if role == "enrichment" and mailbox_id is None:
        queue, concurrency = "fmg_enrichment", 4
    elif role == "mail":
        queue, concurrency = queue_for_mailbox(mailbox_id), 2
    else:
        raise ValueError("Choose enrichment or mail with a mailbox ID")
    return [
        "worker",
        f"--queues={queue}",
        f"--concurrency={concurrency}",
        "--loglevel=WARNING",
    ]


def create_worker(
    settings=None, *, role="enrichment", mailbox_id=None, enricher_factory=None
):
    settings = settings or Settings()
    args = worker_args(role, mailbox_id)
    queue = args[1].split("=", 1)[1]
    worker = Celery("fmg_agent", broker=settings.broker_url.get_secret_value())
    worker.conf.update(
        task_default_queue=queue,
        task_queues=(Queue(queue),),
        task_create_missing_queues=False,
        accept_content=["json"],
        task_serializer="json",
        task_ignore_result=True,
        worker_prefetch_multiplier=1,
        worker_enable_remote_control=False,
        task_publish_retry=False,
        task_acks_late=True,
        task_time_limit=600,
        task_soft_time_limit=570,
        broker_transport_options={
            "global_keyprefix": "fmg_agent:",
            "visibility_timeout": 900,
        },
        broker_connection_timeout=5,
        broker_connection_retry_on_startup=True,
    )
    factory = enricher_factory or (
        lambda: Enricher(
            PublicPageGateway(),
            GeminiGateway(
                settings.gemini_api_key.get_secret_value(), settings.gemini_model
            ),
        )
    )

    @worker.task(name="fmg_agent.email.enrich", max_retries=0, shared=False)
    def enrich(job_id):
        if role != "enrichment":
            return {"code": "worker_role_mismatch"}
        engine, sessions = database(settings)
        try:
            run_job(JobStore(sessions), job_id, factory())
        finally:
            engine.dispose()

    @worker.task(name="fmg_agent.email.bounce_retry", max_retries=0, shared=False)
    def bounce_retry(original_send_id):
        from .email.retries import process_retry
        from .email.smtp import deliver

        if role != "mail":
            return {"code": "worker_role_mismatch"}
        engine, sessions = database(settings)
        try:
            return process_retry(
                sessions,
                original_send_id,
                settings,
                deliver,
                registry=MailboxRegistry.load(settings),
                expected_mailbox_id=mailbox_id,
            )
        finally:
            engine.dispose()

    @worker.task(name="fmg_agent.outreach.send", max_retries=0, shared=False)
    def outreach_send(recipient_id):
        from .outreach import process_recipient
        from .email.smtp import deliver

        if role != "mail":
            return {"code": "worker_role_mismatch"}
        engine, sessions = database(settings)
        try:
            return process_recipient(
                sessions,
                recipient_id,
                settings,
                deliver,
                registry=MailboxRegistry.load(settings),
                expected_mailbox_id=mailbox_id,
            )
        finally:
            engine.dispose()

    return worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("enrichment", "mail"), required=True)
    parser.add_argument("--mailbox")
    options = parser.parse_args()
    args = worker_args(options.role, options.mailbox)
    settings = Settings()
    engine, sessions = database(settings)
    try:
        registry = check_readiness(settings, sessions)
        if options.role == "mail":
            registry.select(options.mailbox, allow_legacy=False)
    finally:
        engine.dispose()
    create_worker(settings, role=options.role, mailbox_id=options.mailbox).worker_main(
        args
    )


if __name__ == "__main__":
    main()
