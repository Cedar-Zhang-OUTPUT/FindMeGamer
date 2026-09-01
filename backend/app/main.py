from time import monotonic

from fastapi import FastAPI, Request
from fastapi.responses import Response
from redis import Redis

from app.api.dependencies import create_workspace_authenticator
from app.api.routes import health
from app.api.routes.health import ReadinessProbe
from app.api.routes import session
from app.core.config import get_settings
from app.core.errors import (
    APIError,
    correlation_id_for,
    error_response,
    install_error_handlers,
)
from app.core.logging import log_request
from app.core.rate_limit import (
    FixedWindowRateLimiter,
    RateLimiter,
    RedisRateLimitCounter,
)


def create_app(
    *,
    readiness_probe: ReadinessProbe | None = None,
    workspace_key_hash: str | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    settings = get_settings()
    if rate_limiter is None:
        redis_client = Redis.from_url(settings.redis_url)
        rate_limiter = FixedWindowRateLimiter(
            counter=RedisRateLimitCounter(redis_client),
            limit=settings.workspace_rate_limit,
            window_seconds=settings.workspace_rate_limit_window_seconds,
        )
    authenticate_workspace = create_workspace_authenticator(
        workspace_key_hash=(
            workspace_key_hash
            if workspace_key_hash is not None
            else settings.workspace_access_key_hash
        ),
        rate_limiter=rate_limiter,
    )
    app = FastAPI(title="Find Me Gamer API", version="1.0.0")
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:
        correlation_id = correlation_id_for(request)
        request.state.correlation_id = correlation_id
        started = monotonic()
        try:
            response = await call_next(request)
        except APIError as error:
            response = error_response(error, correlation_id)
        except Exception:
            response = error_response(
                APIError(
                    status_code=500,
                    code="internal_error",
                    message="The request could not be completed.",
                    retryable=True,
                ),
                correlation_id,
            )
        response.headers["X-Correlation-ID"] = correlation_id
        route = request.scope.get("route")
        route_template = getattr(route, "path", "<unmatched>")
        log_request(
            method=request.method,
            route=route_template,
            status=response.status_code,
            duration_ms=(monotonic() - started) * 1000,
            correlation_id=correlation_id,
        )
        return response

    app.include_router(health.create_router(readiness_probe))
    app.include_router(session.create_router(authenticate_workspace))
    return app


app = create_app()
