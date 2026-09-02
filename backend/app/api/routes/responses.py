"""Unauthenticated Creator response confirmation pages."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.rate_limit import RateLimiter
from app.db.models.outreach import ResponseState
from app.outreach.responses import (
    ResponseConfirmation,
    confirm_response,
    parse_response_capability,
    show_response_confirmation,
)


_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "templates" / "response_confirmation.html"
).read_text(encoding="utf-8")
_PUBLIC_BUCKET = sha256(b"find-me-gamer:public-responses:v1").hexdigest()
_CHOICES = {"accepted": ResponseState.ACCEPTED, "declined": ResponseState.DECLINED}
_MAX_FORM_BYTES = 1_024
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        "default-src 'none'; form-action 'self'; base-uri 'none'; "
        "frame-ancestors 'none'"
    ),
}
_HTML_RESPONSE = {
    200: {"content": {"text/html": {"schema": {"type": "string"}}}},
    400: {"content": {"text/html": {"schema": {"type": "string"}}}},
    404: {"content": {"text/html": {"schema": {"type": "string"}}}},
    429: {"content": {"text/html": {"schema": {"type": "string"}}}},
    503: {"content": {"text/html": {"schema": {"type": "string"}}}},
}


def _html(
    title: str, message: str, *, status_code: int = 200, form: str = ""
) -> HTMLResponse:
    document = (
        _TEMPLATE.replace("%%TITLE%%", escape(title))
        .replace("%%MESSAGE%%", escape(message))
        .replace("%%FORM%%", form)
    )
    return HTMLResponse(
        content=document,
        status_code=status_code,
        headers=_SECURITY_HEADERS,
    )


def _render(
    view: ResponseConfirmation,
    *,
    token: str = "",
    selected: str = "accepted",
) -> HTMLResponse:
    if view.kind == "not_found":
        return _html(
            "Response link not found",
            "This response link could not be found.",
            status_code=404,
        )
    if view.kind == "inactive":
        return _html(
            "Response link inactive",
            "This response link is inactive and cannot record a response.",
        )
    if view.kind == "final" and view.state is not None:
        state = "Accepted" if view.state is ResponseState.ACCEPTED else "Declined"
        return _html(
            "Response recorded",
            f"Your final response is {state}.",
        )
    accepted_checked = " checked" if selected == "accepted" else ""
    declined_checked = " checked" if selected == "declined" else ""
    form = (
        f'<form action="/r/{escape(token, quote=True)}" method="post">'
        f'<label><input type="radio" name="choice" value="accepted"'
        f"{accepted_checked}> {escape(view.accepted_label)}</label>"
        f'<label><input type="radio" name="choice" value="declined"'
        f"{declined_checked}> {escape(view.declined_label)}</label>"
        '<button type="submit">Confirm response</button>'
        "</form>"
    )
    return _html(
        "Confirm your response",
        "Choose one option, then confirm your final response.",
        form=form,
    )


def _client_address(
    request: Request,
    resolve_client_address: Callable[[str | None, str | None], str],
) -> str:
    peer = request.client.host if request.client is not None else None
    return resolve_client_address(peer, request.headers.get("X-Forwarded-For"))


def _limited(
    rate_limiter: RateLimiter,
    client_address: str,
    digest: str | None,
) -> HTMLResponse | None:
    try:
        if not rate_limiter.allow(_PUBLIC_BUCKET, client_address):
            return _html(
                "Too many requests",
                "Too many requests. Please try again later.",
                status_code=429,
            )
        if digest is not None and not rate_limiter.allow(digest, client_address):
            return _html(
                "Too many requests",
                "Too many requests. Please try again later.",
                status_code=429,
            )
    except Exception:
        return _html(
            "Temporarily unavailable",
            "Response confirmation is temporarily unavailable. Please try again.",
            status_code=503,
        )
    return None


async def _choice_from_form(request: Request) -> ResponseState | None:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip()
    if content_type.casefold() != "application/x-www-form-urlencoded":
        return None
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_FORM_BYTES:
                return None
        except ValueError:
            return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_FORM_BYTES:
            return None
    try:
        values = parse_qs(
            bytes(body).decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=4,
        )
    except (UnicodeDecodeError, ValueError):
        return None
    choices = values.get("choice", [])
    if set(values) != {"choice"} or len(choices) != 1:
        return None
    return _CHOICES.get(choices[0])


def create_router(
    *,
    rate_limiter: RateLimiter,
    resolve_client_address: Callable[[str | None, str | None], str],
) -> APIRouter:
    router = APIRouter(tags=["creator responses"])

    @router.get(
        "/r/{token}",
        response_class=HTMLResponse,
        responses=_HTML_RESPONSE,
        operation_id="showCreatorResponseConfirmation",
    )
    def show_confirmation(
        token: str,
        request: Request,
        choice: str = "accepted",
        database_session: Session = Depends(get_session),
    ) -> HTMLResponse:
        digest = parse_response_capability(token)
        limited = _limited(
            rate_limiter,
            _client_address(request, resolve_client_address),
            digest,
        )
        if limited is not None:
            return limited
        if digest is None:
            return _render(ResponseConfirmation(kind="not_found"))
        if choice not in _CHOICES:
            return _html(
                "Invalid response",
                "Choose accepted or declined.",
                status_code=400,
            )
        return _render(
            show_response_confirmation(database_session, digest),
            token=token,
            selected=choice,
        )

    @router.post(
        "/r/{token}",
        response_class=HTMLResponse,
        responses=_HTML_RESPONSE,
        operation_id="confirmCreatorResponse",
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/x-www-form-urlencoded": {
                        "schema": {
                            "type": "object",
                            "required": ["choice"],
                            "properties": {
                                "choice": {
                                    "type": "string",
                                    "enum": ["accepted", "declined"],
                                }
                            },
                        }
                    }
                },
            }
        },
    )
    async def confirm(
        token: str,
        request: Request,
        database_session: Session = Depends(get_session),
    ) -> HTMLResponse:
        digest = parse_response_capability(token)
        limited = _limited(
            rate_limiter,
            _client_address(request, resolve_client_address),
            digest,
        )
        if limited is not None:
            return limited
        if digest is None:
            return _render(ResponseConfirmation(kind="not_found"))
        choice = await _choice_from_form(request)
        if choice is None:
            return _html(
                "Invalid response",
                "Choose accepted or declined.",
                status_code=400,
            )
        try:
            view = confirm_response(database_session, digest, choice)
            database_session.commit()
        except Exception:
            database_session.rollback()
            return _html(
                "Temporarily unavailable",
                "Response confirmation is temporarily unavailable. Please try again.",
                status_code=503,
            )
        return _render(view)

    return router


__all__ = ["create_router"]
