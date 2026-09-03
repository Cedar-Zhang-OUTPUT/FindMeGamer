import sys

sys.path.insert(0, "/app")

from app.workers.celery_app import celery_app  # noqa: E402


celery_app.conf.broker_transport_options = {
    **celery_app.conf.broker_transport_options,
    "visibility_timeout": 5,
}
celery_app.start(["worker", "--loglevel=INFO", "--concurrency=1"])
