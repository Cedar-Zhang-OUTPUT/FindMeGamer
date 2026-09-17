import asyncio
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .auth import Principal, authenticate
from .config import Settings
from .db import database
from .errors import ApiError, error_response
from .email.routes import router as email_router
from .outreach import router as outreach_router
from .providers.catalog import Catalog
from .providers.twitch import TwitchAuth
from .providers.routes import router as provider_router
from .usage import router as usage_router, run_id


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine, sessions = database(settings)

    @asynccontextmanager
    async def lifespan(app):
        maintenance = None
        if settings.twitch_client_id:
            maintenance = asyncio.create_task(
                app.state.twitch_auth.maintain(app.state.provider_transport)
            )
        try:
            yield
        finally:
            if maintenance:
                maintenance.cancel()
                with suppress(asyncio.CancelledError):
                    await maintenance
            engine.dispose()

    app = FastAPI(
        title="FMG Agent Services",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.settings = settings
    app.state.catalog = Catalog(settings.catalog_dir)
    app.state.provider_transport = None
    app.state.twitch_auth = TwitchAuth(settings)
    app.include_router(provider_router)
    app.include_router(email_router)
    app.include_router(outreach_router)
    app.include_router(usage_router)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        try:
            request.state.run_id = run_id(
                request.headers.get("X-FMG-Run-ID", "unassigned")
            )
        except ApiError as error:
            return await error_response(request, error)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    app.add_exception_handler(ApiError, error_response)

    @app.exception_handler(SQLAlchemyError)
    async def storage_error(request, exc):
        return await error_response(
            request,
            ApiError(
                503,
                "storage_unavailable",
                "Service storage is unavailable.",
                retryable=True,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic's default response includes raw input; never echo credentials.
        return await error_response(
            request, ApiError(422, "invalid_request", "Check the request parameters.")
        )

    @app.get("/v1/health")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/v1/auth/check")
    def auth_check(request: Request, principal: Principal = Depends(authenticate)):
        return {
            "data": {
                "token_id": principal.id,
                "label": principal.label,
                "scopes": list(principal.scopes),
            },
            "meta": {"request_id": request.state.request_id},
        }

    return app
