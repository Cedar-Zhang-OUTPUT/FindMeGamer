import re
from dataclasses import dataclass
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


_safe_correlation_id = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@dataclass
class APIError(Exception):
    status_code: int
    code: str
    message: str
    retryable: bool = False


def correlation_id_for(request: Request) -> str:
    supplied = request.headers.get("X-Correlation-ID", "")
    if safe_correlation_id(supplied) is not None:
        return supplied
    return str(uuid4())


def safe_correlation_id(value: object) -> str | None:
    if isinstance(value, str) and _safe_correlation_id.fullmatch(value):
        return value
    return None


def error_response(error: APIError, correlation_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "correlation_id": correlation_id,
            }
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, error: APIError) -> JSONResponse:
        return error_response(error, request.state.correlation_id)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            APIError(
                status_code=422,
                code="request_invalid",
                message="The request is invalid.",
            ),
            request.state.correlation_id,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        if error.status_code == 404:
            public_error = APIError(
                status_code=404,
                code="not_found",
                message="The requested resource was not found.",
            )
        elif error.status_code == 405:
            public_error = APIError(
                status_code=405,
                code="method_not_allowed",
                message="The request method is not allowed.",
            )
        else:
            public_error = APIError(
                status_code=error.status_code,
                code="request_error",
                message="The request could not be completed.",
            )
        return error_response(public_error, request.state.correlation_id)
