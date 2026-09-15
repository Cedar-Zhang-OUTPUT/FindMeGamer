from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ):
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


async def error_response(request: Request, exc: ApiError):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else {}
    return JSONResponse(
        status_code=exc.status,
        headers=headers,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "retry_after_seconds": exc.retry_after_seconds,
            },
            "request_id": request.state.request_id,
            "meta": {"cost": getattr(exc, "cost", None)},
        },
    )
