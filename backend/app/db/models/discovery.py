"""Durable discovery, separate from analysis and selection."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


def json_object():
    return mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


def counter():
    return mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


class Activity(TimestampMixin, Base):
    __tablename__ = "activities"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("game_profiles.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_snapshot: Mapped[dict] = json_object()


class DiscoveryQuery(TimestampMixin, Base):
    __tablename__ = "discovery_queries"
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    activity_id: Mapped[UUID] = mapped_column(
        ForeignKey("activities.id"), nullable=False, index=True
    )
    conditions: Mapped[dict] = json_object()
    source_snapshot: Mapped[dict] = json_object()
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    stop_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    provider_states: Mapped[dict] = json_object()
    result_count: Mapped[int] = counter()
    requests_reserved: Mapped[int] = counter()
    scanned_reserved: Mapped[int] = counter()


class DiscoveryBatch(TimestampMixin, Base):
    __tablename__ = "discovery_batches"
    __table_args__ = (
        UniqueConstraint("query_id", "ordinal", name="uq_discovery_batch_ordinal"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    query_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_queries.id"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    initial_result_count: Mapped[int] = counter()
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    requests_reserved: Mapped[int] = counter()
    scanned_reserved: Mapped[int] = counter()
    reason: Mapped[str | None] = mapped_column(String(64))


class DiscoveryAttempt(TimestampMixin, Base):
    __tablename__ = "discovery_attempts"
    __table_args__ = (
        UniqueConstraint("batch_id", "sequence", name="uq_discovery_attempt_sequence"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_batches.id"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    input: Mapped[dict] = json_object()
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="in_flight", server_default="in_flight"
    )
    lease_token: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, default=uuid4
    )
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    requests_reserved: Mapped[int] = counter()
    scan_reserved: Mapped[int] = counter()
    outcome: Mapped[dict] = json_object()
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (
        UniqueConstraint(
            "query_id", "platform", "account_id", name="uq_discovery_candidate_account"
        ),
        UniqueConstraint("query_id", "ordinal", name="uq_discovery_candidate_ordinal"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    query_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_queries.id"), nullable=False, index=True
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey("creator_profiles.id"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    identity_revision: Mapped[int] = counter()
    account_snapshot: Mapped[dict] = json_object()
    filter_notes: Mapped[dict] = json_object()
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
