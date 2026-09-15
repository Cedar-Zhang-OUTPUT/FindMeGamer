import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AccessToken
from .errors import ApiError

VALID_SCOPES = frozenset({"read", "email:enrich", "email:send"})
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class IssuedToken:
    id: str
    token: str = field(repr=False)


@dataclass(frozen=True)
class Principal:
    id: str
    label: str
    scopes: tuple[str, ...]


def issue_token(session: Session, *, label: str, scopes: list[str]) -> IssuedToken:
    if not label.strip() or len(label) > 200:
        raise ValueError("Label must have 1–200 characters")
    if not scopes or not set(scopes) <= VALID_SCOPES:
        raise ValueError("Use read, email:enrich or email:send scopes")
    raw = "fmg_" + secrets.token_urlsafe(32)
    record = AccessToken(
        digest=hashlib.sha256(raw.encode()).hexdigest(),
        label=label.strip(),
        scopes=sorted(set(scopes)),
    )
    session.add(record)
    session.commit()
    return IssuedToken(record.id, raw)


def revoke_token(session: Session, token_id: str) -> bool:
    record = session.get(AccessToken, token_id)
    if record is None:
        return False
    if record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        session.commit()
    return True


def authenticate(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> Principal:
    invalid = ApiError(401, "invalid_access_token", "A valid access token is required.")
    if credentials is None:
        raise invalid
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    with request.app.state.sessions() as session:
        record = session.scalar(select(AccessToken).where(AccessToken.digest == digest))
        if record is None or record.revoked_at is not None:
            raise invalid
        return Principal(record.id, record.label, tuple(record.scopes))


def require_scope(scope: str):
    if scope not in VALID_SCOPES:
        raise ValueError("Unknown scope")

    def check(principal: Principal = Depends(authenticate)) -> Principal:
        if scope not in principal.scopes:
            raise ApiError(
                403, "insufficient_scope", "This token does not allow this operation."
            )
        return principal

    return check
