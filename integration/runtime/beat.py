import sys

sys.path.insert(0, "/app")

from app.workers.celery_app import celery_app  # noqa: E402


celery_app.conf.beat_schedule = {
    "integration-profile-reanalysis": {
        "task": "find_me_gamer.reanalysis.enqueue_due",
        "schedule": 15.0,
        "args": (1,),
    }
}
celery_app.start(
    [
        "beat",
        "--loglevel=INFO",
        "--schedule=/tmp/integration-celerybeat-schedule",
        "--max-interval=1",
    ]
)
