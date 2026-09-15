"""Per-token/run request ledger. Unknown prices are never zero."""

import re
from decimal import Decimal
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
    cost: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
        "search_queries",
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

    def finish(
        self,
        request_id,
        status,
        *,
        resource_counts=None,
        usage=None,
        data=None,
        model=None
    ):
        from .pricing import estimate

        with self.sessions() as session:
            row = session.get(UsageRecord, request_id)
            if row is None:
                raise ValueError("Missing usage reservation")
            row.status = status
            row.resource_counts = numbers(resource_counts)
            row.usage = numbers(usage)
            row.cost = estimate(
                row.provider,
                row.operation,
                status,
                data=data,
                usage=row.usage,
                model=model,
            )
            session.commit()
            return row.cost

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
                        "cost_breakdown": [],
                        "unpriced_request_count": 0,
                    },
                )
                p["request_count"] += 1
                cost = row.cost or {
                    "estimated_cost": None,
                    "complete": False,
                    "unpriced_components": ["legacy_or_incomplete_record"],
                }
                p["cost_breakdown"].append(
                    {
                        "request_id": row.request_id,
                        "operation": row.operation,
                        "status": row.status,
                        **cost,
                    }
                )
                if cost.get("estimated_cost") is not None:
                    p["estimated_cost"] = str(
                        Decimal(p["estimated_cost"] or "0")
                        + Decimal(cost["estimated_cost"])
                    )
                    p["currency"] = "USD"
                if not cost.get("complete"):
                    p["unpriced_request_count"] += 1
                p["pricing_version"] = sorted(
                    {
                        c["pricing_version"]
                        for c in p["cost_breakdown"]
                        if c.get("pricing_version")
                    }
                )
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
        known = [
            Decimal(p["estimated_cost"])
            for p in providers.values()
            if p["estimated_cost"] is not None
        ]
        unpriced = sum(p["unpriced_request_count"] for p in providers.values())
        return {
            "run_id": run,
            "request_count": count,
            "providers": providers,
            "actual_cost": None,
            "estimated_cost": str(sum(known, Decimal(0))) if known else None,
            "currency": "USD" if known else None,
            "pricing_version": sorted(
                {v for p in providers.values() for v in p["pricing_version"] or []}
            ),
            "complete_cost_known": count > 0 and unpriced == 0,
            "unpriced_request_count": unpriced,
            "cost_note": "Estimated USD subtotal, not an invoice. Unknown components excluded. Before discounts/free allowances/X daily deduplication; excludes hosting and subscriptions. Historical records are not repriced. Started requests may have completed upstream.",
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
