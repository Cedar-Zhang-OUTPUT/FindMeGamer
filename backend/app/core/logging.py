import json
import logging


request_logger = logging.getLogger("app.requests")


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
