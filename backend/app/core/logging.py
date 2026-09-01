import json
import logging
import sys
from typing import TextIO


request_logger = logging.getLogger("app.requests")


def configure_request_logging(stream: TextIO | None = None) -> None:
    for handler in tuple(request_logger.handlers):
        if handler.get_name() == "find_me_gamer_request":
            request_logger.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name("find_me_gamer_request")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    request_logger.addHandler(handler)
    request_logger.setLevel(logging.INFO)
    request_logger.disabled = False
    request_logger.propagate = False

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.disabled = True
    access_logger.propagate = False


def log_request(
    *,
    method: str,
    route: str,
    status: int,
    duration_ms: float,
    correlation_id: str,
) -> None:
    request_logger.info(
        json.dumps(
            {
                "method": method,
                "route": route,
                "status": status,
                "duration_ms": round(duration_ms, 3),
                "correlation_id": correlation_id,
            },
            separators=(",", ":"),
        )
    )
