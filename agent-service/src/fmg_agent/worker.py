"""Dedicated Celery worker with an in-process pending-job dispatcher; no Beat."""

import logging
from threading import Event, Thread

from celery import Celery
from celery.signals import worker_ready, worker_shutdown
from kombu import Queue

from .config import Settings
from .db import database
from .email.enrichment import Enricher, run_job
from .email.gemini import GeminiGateway
from .email.jobs import JobStore
from .email.public_pages import PublicPageGateway


def dispatch_once(store, publish, *, retention_days):
    store.recover_expired()
    store.cleanup(retention_days)
    for job_id in store.pending(limit=20):
        publish(job_id)


def create_worker(settings=None, *, enricher_factory=None):
    settings = settings or Settings()
    worker = Celery("fmg_agent", broker=settings.broker_url.get_secret_value())
    worker.conf.update(
        task_default_queue="fmg_agent",
        task_queues=(Queue("fmg_agent"),),
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

    @worker.task(name="fmg_agent.email.enrich", max_retries=0)
    def enrich(job_id):
        engine, sessions = database(settings)
        try:
            run_job(JobStore(sessions), job_id, factory())
        finally:
            engine.dispose()

    stop = Event()

    @worker.task(name="fmg_agent.outreach.send", max_retries=0)
    def outreach_send(recipient_id):
        from .outreach import process_recipient
        from .email.smtp import deliver
        engine, sessions = database(settings)
        try:
            process_recipient(sessions, recipient_id, settings, deliver)
        finally:
            engine.dispose()

    def dispatch_loop():
        engine, sessions = database(settings)
        try:
            while not stop.is_set():
                try:
                    dispatch_once(
                        JobStore(sessions),
                        lambda job_id: enrich.apply_async(
                            args=[job_id], queue="fmg_agent", expires=60
                        ),
                        retention_days=settings.email_retention_days,
                    )
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Email dispatch unavailable; pending jobs are retained."
                    )
                try:
                    from .outreach import pending
                    for recipient_id in pending(sessions):
                        outreach_send.apply_async(args=[recipient_id], queue="fmg_agent", expires=60)
                except Exception:
                    logging.getLogger(__name__).warning("Outreach dispatch unavailable; pending recipients are retained.")
                stop.wait(10)
        finally:
            engine.dispose()

    def start(sender=None, **kwargs):
        if sender is not None and sender.app is worker:
            stop.clear()
            Thread(target=dispatch_loop, daemon=True, name="fmg-agent-dispatch").start()

    def shutdown(sender=None, **kwargs):
        if sender is not None and sender.app is worker:
            stop.set()

    worker_ready.connect(start, weak=False)
    worker_shutdown.connect(shutdown, weak=False)
    return worker


def main():
    worker = create_worker()
    worker.worker_main(
        ["worker", "--queues=fmg_agent", "--concurrency=2", "--loglevel=WARNING"]
    )


if __name__ == "__main__":
    main()
