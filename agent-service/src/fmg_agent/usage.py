"""Per-token/run request ledger. Unknown prices are never zero."""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import JSON, DateTime, ForeignKey, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .auth import Principal, authenticate
from .db import Base
from .errors import ApiError


class UsageRecord(Base):
    __tablename__ = "usage_records"
    request_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    token_id: Mapped[str] = mapped_column(ForeignKey("access_tokens.id"), index=True)
    run_id: Mapped[str] = mapped_column(String(100), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(100))
    resource_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def run_id(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value
    ):
        raise ApiError(
            422,
            "invalid_run_id",
            "Run ID must contain 1–100 letters, digits, dots, underscores or hyphens.",
        )
    return value


def numbers(value):
    allowed = {
        "promptTokenCount",
        "candidatesTokenCount",
        "totalTokenCount",
        "cachedContentTokenCount",
        "thoughtsTokenCount",
        "toolUsePromptTokenCount",
        "returned_items",
        "emails",
    }
    return (
        {
            k: v
            for k, v in (value or {}).items()
            if k in allowed and type(v) is int and v >= 0
        }
        if isinstance(value, dict)
        else {}
    )


class Ledger:
    def __init__(self, sessions):
        self.sessions = sessions

    def start(self, request_id, token_id, run, provider, operation):
        with self.sessions() as session:
            session.add(
                UsageRecord(
                    request_id=request_id,
                    token_id=token_id,
                    run_id=run,
                    provider=provider,
                    operation=operation,
                    status="started",
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if session.get(UsageRecord, request_id) is None:
                    raise
                return False
            return True

    def finish(self, request_id, status, *, resource_counts=None, usage=None):
        with self.sessions() as session:
            row = session.get(UsageRecord, request_id)
            if row is None:
                raise ValueError("Missing usage reservation")
            row.status = status
            row.resource_counts = numbers(resource_counts)
            row.usage = numbers(usage)
            session.commit()

    def summary(self, token_id, run):
        providers = {}
        with self.sessions() as session:
            rows = session.scalars(
                select(UsageRecord).where(
                    UsageRecord.token_id == token_id, UsageRecord.run_id == run
                )
            )
            count = 0
            for row in rows:
                count += 1
                p = providers.setdefault(
                    row.provider,
                    {
                        "request_count": 0,
                        "statuses": {},
                        "resource_counts": {},
                        "usage": {},
                        "actual_cost": None,
                        "estimated_cost": None,
                        "currency": None,
                        "pricing_version": None,
                    },
                )
                p["request_count"] += 1
                if row.provider == "youtube":
                    quota = p.setdefault(
                        "quota_estimate",
                        {
                            "successful_calls": {},
                            "unresolved_calls": 0,
                            "pricing_version": "youtube-quota-2026-09-14",
                            "source_url": "https://developers.google.com/youtube/v3/determine_quota_cost",
                        },
                    )
                    one_unit = {
                        "activities.list",
                        "channels.list",
                        "channelSections.list",
                        "comments.list",
                        "commentThreads.list",
                        "i18nLanguages.list",
                        "i18nRegions.list",
                        "playlistItems.list",
                        "playlists.list",
                        "subscriptions.list",
                        "videoAbuseReportReasons.list",
                        "videoCategories.list",
                        "videos.list",
                    }
                    bucket = (
                        "search_calls"
                        if row.operation == "search.list"
                        else "other_units"
                    )
                    if row.status == "succeeded" and (
                        row.operation == "search.list" or row.operation in one_unit
                    ):
                        quota["successful_calls"][bucket] = (
                            quota["successful_calls"].get(bucket, 0) + 1
                        )
                    else:
                        quota["unresolved_calls"] += 1
                p["statuses"][row.status] = p["statuses"].get(row.status, 0) + 1
                for group in ("resource_counts", "usage"):
                    for key, val in getattr(row, group).items():
                        p[group][key] = p[group].get(key, 0) + val
        return {
            "run_id": run,
            "request_count": count,
            "providers": providers,
            "actual_cost": None,
            "estimated_cost": None,
            "currency": None,
            "pricing_version": None,
            "complete_cost_known": False,
            "cost_note": "No attributable provider billing or verified pricing configured; request counts are not money. Started requests may have completed upstream.",
            "codex_task_usage": None,
        }


router = APIRouter()


@router.get("/v1/usage")
def usage(request: Request, run_id: str, principal: Principal = Depends(authenticate)):
    return {
        "data": Ledger(request.app.state.sessions).summary(
            principal.id, validate_run(run_id)
        ),
        "meta": {"request_id": request.state.request_id},
    }


validate_run = run_id
