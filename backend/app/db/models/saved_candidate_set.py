"""Explicit immutable candidate membership, not a Profile version or selection."""

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SavedCandidateSet(TimestampMixin, Base):
    __tablename__ = "saved_candidate_sets"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    query_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_queries.id"), nullable=False, index=True
    )
    request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, unique=True
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
