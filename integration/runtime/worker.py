import sys

sys.path.insert(0, "/app")

from app.workers.celery_app import celery_app  # noqa: E402
from app.workers import outreach_tasks  # noqa: E402
from app.analysis import runtime as analysis_runtime  # noqa: E402
from capture_smtp import capture_gateway  # noqa: E402
from fake_images import image_gateway  # noqa: E402


outreach_tasks.SMTPGateway = capture_gateway
analysis_runtime.DeepSeekGateway = image_gateway
celery_app.conf.broker_transport_options = {
    **celery_app.conf.broker_transport_options,
    "visibility_timeout": 5,
}
celery_app.start(["worker", "--loglevel=INFO", "--concurrency=1"])
