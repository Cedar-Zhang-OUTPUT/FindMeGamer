"""Import-safe broker-only Celery application."""

from celery import Celery

from app.core.config import get_settings


def create_celery_app(*, broker_url: str | None = None) -> Celery:
    settings = get_settings()
    app = Celery(
        "find_me_gamer",
        broker=broker_url or settings.redis_url,
        backend=None,
        include=[
            "app.matching.retention",
            "app.workers.analysis_tasks",
            "app.workers.match_tasks",
            "app.workers.outreach_tasks",
            "app.workers.outreach_draft_tasks",
            "app.workers.activity_send_tasks",
            "app.workers.discovery_tasks",
            "app.workers.planning_tasks",
            "app.workers.evaluation_tasks",
            "app.workers.schedules",
        ],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_ignore_result=True,
        task_store_errors_even_if_ignored=False,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        broker_connection_retry_on_startup=True,
        broker_connection_max_retries=settings.celery_broker_connection_max_retries,
        broker_transport_options={
            "socket_connect_timeout": settings.celery_broker_connect_timeout_seconds,
            "socket_timeout": settings.celery_broker_socket_timeout_seconds,
            "max_retries": 0,
        },
        worker_prefetch_multiplier=1,
        worker_concurrency=5,
        beat_schedule={
            "mandatory-profile-reanalysis": {
                "task": "find_me_gamer.reanalysis.enqueue_due",
                "schedule": 900.0,
            },
            "match-input-retention": {
                "task": "find_me_gamer.match.purge_expired_inputs",
                "schedule": 3600.0,
            },
        },
    )
    return app


celery_app = create_celery_app()
