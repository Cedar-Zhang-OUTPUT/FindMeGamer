from contextlib import asynccontextmanager
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
from .providers.catalog import Catalog
from .providers.routes import router as provider_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine, sessions = database(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
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
    app.include_router(provider_router)
    app.include_router(email_router)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
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
