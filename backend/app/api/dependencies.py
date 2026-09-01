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
    *,
    workspace_key_hash: str,
    rate_limiter: RateLimiter,
    resolve_client_address: Callable[[str | None, str | None], str],
) -> Callable[..., AuthenticatedWorkspace]:
    workspace_identity = workspace_key_digest(workspace_key_hash)

    def authenticate_workspace(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> AuthenticatedWorkspace:
        raw_key = credentials.credentials if credentials is not None else ""
        peer_address = request.client.host if request.client is not None else None
        client_address = resolve_client_address(
            peer_address, request.headers.get("X-Forwarded-For")
        )

        try:
            allowed = rate_limiter.allow(workspace_identity, client_address)
        except Exception:
            raise APIError(
                status_code=503,
                code="authentication_unavailable",
                message="Authentication is temporarily unavailable.",
                retryable=True,
            ) from None
        if not allowed:
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
        return AuthenticatedWorkspace(key_digest=workspace_identity)

    return authenticate_workspace
