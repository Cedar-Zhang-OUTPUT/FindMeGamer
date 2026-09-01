from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import APIError
from app.core.rate_limit import RateLimiter
from app.core.security import verify_workspace_key, workspace_key_digest


_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedWorkspace:
    key_digest: str


def create_workspace_authenticator(
    *, workspace_key_hash: str, rate_limiter: RateLimiter
) -> Callable[..., AuthenticatedWorkspace]:
    def authenticate_workspace(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> AuthenticatedWorkspace:
        raw_key = credentials.credentials if credentials is not None else ""
        key_digest = workspace_key_digest(raw_key)
        client_address = request.client.host if request.client is not None else "unknown"

        if not rate_limiter.allow(key_digest, client_address):
            raise APIError(
                status_code=429,
                code="rate_limit_exceeded",
                message="Too many requests. Please try again later.",
                retryable=True,
            )
        if credentials is None or not verify_workspace_key(raw_key, workspace_key_hash):
            raise APIError(
                status_code=401,
                code="workspace_key_invalid",
                message="A valid Workspace Access Key is required.",
            )
        return AuthenticatedWorkspace(key_digest=key_digest)

    return authenticate_workspace
