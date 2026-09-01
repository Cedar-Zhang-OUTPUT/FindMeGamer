from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ProfileFieldsMixin(TimestampMixin):
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    sort_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    current_facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    analysis: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    brief: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_status: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    model_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    prompt_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )


class GameProfile(ProfileFieldsMixin, Base):
    __tablename__ = "game_profiles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    steam_app_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)


class CreatorProfile(ProfileFieldsMixin, Base):
    __tablename__ = "creator_profiles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    youtube_channel_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    manual_notes: Mapped[str | None] = mapped_column(Text)
    contacts: Mapped[list["CreatorContact"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan"
    )


class CreatorContact(TimestampMixin, Base):
    __tablename__ = "creator_contacts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey("creator_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creator: Mapped[CreatorProfile] = relationship(back_populates="contacts")
