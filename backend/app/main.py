from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.responses import Response
from redis import Redis

from app.api.dependencies import create_workspace_authenticator
from app.api.routes import health
from app.api.routes import discover as discover_routes
from app.api.routes.health import ReadinessProbe
from app.api.routes import profiles as profile_routes
from app.api.routes import jobs as job_routes
from app.api.routes import match as match_routes
from app.api.routes import outreach as outreach_routes
from app.api.routes import responses as response_routes
from app.api.routes import session, settings as settings_routes
from app.analysis.targets import ChannelResolver
from app.analysis.runtime import build_production_channel_resolver
from app.core.client_address import ClientAddressResolver
from app.core.config import get_settings
from app.core.crypto import SecretCipher
from app.core.database import session_scope
from app.core.idempotency import utc_now
from app.core.errors import (
    APIError,
    correlation_id_for,
    error_response,
    install_error_handlers,
)
from app.core.logging import configure_request_logging, log_request
from app.core.rate_limit import (
    FixedWindowRateLimiter,
    RateLimiter,
    RedisRateLimitCounter,
)
from app.core.security import validate_workspace_key_hash
from app.outreach.rate_limit import SMTPRateLimiter
from app.outreach.smtp import SMTPGateway
from app.integrations.connection_probe import ProductionConnectionProbe


def create_app(
    *,
    readiness_probe: ReadinessProbe | None = None,
    workspace_key_hash: str | None = None,
    rate_limiter: RateLimiter | None = None,
    trusted_proxy_cidrs: tuple[str, ...] | None = None,
    secret_cipher: SecretCipher | None = None,
    connection_probe: settings_routes.ConnectionProbe | None = None,
    channel_resolver: ChannelResolver | None = None,
    job_session_factory: job_routes.SessionFactory = session_scope,
    idempotency_clock: job_routes.IdempotencyClock = utc_now,
    job_dispatcher: job_routes.JobDispatcher | None = None,
    analysis_failure_clock: job_routes.FailureClock = utc_now,
    match_dispatcher: match_routes.MatchAPIDispatcher | None = None,
    match_clock: match_routes.Clock = utc_now,
    match_seed_factory: match_routes.SeedFactory = match_routes.random_signed_64_bit,
    smtp_gateway: SMTPGateway | None = None,
    smtp_rate_limiter: SMTPRateLimiter | None = None,
    outreach_batch_dispatcher: outreach_routes.OutreachBatchDispatcher | None = None,
) -> FastAPI:
    configure_request_logging()
    settings = get_settings()
    effective_workspace_key_hash = validate_workspace_key_hash(
        (
            workspace_key_hash
            if workspace_key_hash is not None
            else settings.workspace_access_key_hash
        )
    )
    effective_trusted_proxy_cidrs = (
        trusted_proxy_cidrs
        if trusted_proxy_cidrs is not None
        else settings.trusted_proxy_cidrs
    )
    client_address_resolver = ClientAddressResolver(effective_trusted_proxy_cidrs)
    effective_secret_cipher = (
        secret_cipher
        if secret_cipher is not None
        else SecretCipher.from_file(settings.master_key_file)
    )
    effective_connection_probe = connection_probe or ProductionConnectionProbe(
        deepseek_base_url=settings.deepseek_api_base_url,
        youtube_base_url=settings.youtube_api_base_url,
        x_base_url=settings.x_api_base_url,
        google_ai_base_url=settings.google_ai_api_base_url,
    )
    effective_channel_resolver = channel_resolver or build_production_channel_resolver(
        settings=settings,
        session_factory=session_scope,
    )
    owned_redis_client: Redis | None = None
    if rate_limiter is None:
        owned_redis_client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_read_timeout_seconds,
        )
        rate_limiter = FixedWindowRateLimiter(
            counter=RedisRateLimitCounter(owned_redis_client),
            limit=settings.workspace_rate_limit,
            window_seconds=settings.workspace_rate_limit_window_seconds,
        )
    owned_smtp_redis_client: Redis | None = None
    effective_smtp_gateway = smtp_gateway or SMTPGateway()
    if smtp_rate_limiter is None:
        smtp_redis_client = owned_redis_client
        if smtp_redis_client is None:
            owned_smtp_redis_client = Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=settings.redis_connect_timeout_seconds,
                socket_timeout=settings.redis_read_timeout_seconds,
            )
            smtp_redis_client = owned_smtp_redis_client
        smtp_rate_limiter = SMTPRateLimiter(smtp_redis_client)
    authenticate_workspace = create_workspace_authenticator(
        workspace_key_hash=effective_workspace_key_hash,
        rate_limiter=rate_limiter,
        resolve_client_address=client_address_resolver.resolve,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure_request_logging()
        try:
            yield
        finally:
            if owned_redis_client is not None:
                owned_redis_client.close()
            if owned_smtp_redis_client is not None:
                owned_smtp_redis_client.close()

    app = FastAPI(title="Find Me Gamer API", version="1.0.0", lifespan=lifespan)
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
    app.include_router(
        discover_routes.create_router(
            authenticate_workspace, session_factory=job_session_factory
        )
    )
    app.include_router(
        response_routes.create_router(
            rate_limiter=rate_limiter,
            resolve_client_address=client_address_resolver.resolve,
        )
    )
    app.include_router(session.create_router(authenticate_workspace))
    app.include_router(
        settings_routes.create_router(
            authenticate_workspace,
            secret_cipher=effective_secret_cipher,
            connection_probe=effective_connection_probe,
        )
    )
    app.include_router(
        profile_routes.create_router(
            authenticate_workspace,
            cursor_signing_secret=effective_workspace_key_hash,
        )
    )
    app.include_router(
        job_routes.create_router(
            authenticate_workspace,
            session_factory=job_session_factory,
            channel_resolver=effective_channel_resolver,
            idempotency_clock=idempotency_clock,
            dispatcher=job_dispatcher,
            failure_clock=analysis_failure_clock,
            cursor_signing_secret=effective_workspace_key_hash,
        )
    )
    app.include_router(
        match_routes.create_router(
            authenticate_workspace,
            session_factory=job_session_factory,
            dispatcher=match_dispatcher,
            clock=match_clock,
            seed_factory=match_seed_factory,
            cursor_signing_secret=effective_workspace_key_hash,
        )
    )
    app.include_router(
        outreach_routes.create_router(
            authenticate_workspace,
            secret_cipher=effective_secret_cipher,
            smtp_gateway=effective_smtp_gateway,
            smtp_rate_limiter=smtp_rate_limiter,
            batch_dispatcher=outreach_batch_dispatcher,
            cursor_signing_secret=effective_workspace_key_hash,
        )
    )
    return app


app = create_app()
