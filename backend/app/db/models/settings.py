from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SharedSettings(TimestampMixin, Base):
    __tablename__ = "shared_settings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_name: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Find Me Gamer"
    )
    creator_interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    game_interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    recommended_match_threshold: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("0.70")
    )
    smtp_rate_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    service_connection_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )


class ServiceSecret(TimestampMixin, Base):
    __tablename__ = "service_secrets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    service: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    last_test_succeeded: Mapped[bool | None] = mapped_column(Boolean)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
