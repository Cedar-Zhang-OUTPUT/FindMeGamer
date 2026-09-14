from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.analysis.creator_identity import creator_job_identity


class ProfileFieldsMixin(TimestampMixin):
    manual_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    profile_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    sort_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    current_facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    analysis: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
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

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    steam_app_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)


class CreatorProfile(ProfileFieldsMixin, Base):
    __tablename__ = "creator_profiles"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "platform_account_id",
            name="uq_creator_profiles_platform_account",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    youtube_channel_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True
    )
    manual_notes: Mapped[str | None] = mapped_column(Text)
    contacts: Mapped[list["CreatorContact"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan"
    )


@event.listens_for(CreatorProfile, "before_insert")
def normalize_creator_identity(mapper, connection, profile: CreatorProfile) -> None:
    """Keep established YouTube producers compatible with generic identity."""
    if profile.platform is None:
        profile.platform = "youtube"
    if profile.platform == "youtube":
        if profile.platform_account_id is None:
            profile.platform_account_id = profile.youtube_channel_id
        if profile.youtube_channel_id is None:
            profile.youtube_channel_id = profile.platform_account_id
        if profile.youtube_channel_id != profile.platform_account_id:
            raise ValueError("Conflicting creator identity")
    elif profile.youtube_channel_id is not None:
        raise ValueError("Non-YouTube creator cannot have a YouTube identity")
    creator_job_identity(profile.platform, profile.platform_account_id)


class CreatorContact(TimestampMixin, Base):
    __tablename__ = "creator_contacts"
    __table_args__ = (
        Index(
            "uq_creator_contacts_active_manual",
            "creator_id",
            unique=True,
            postgresql_where=text("is_manual AND is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey("creator_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creator: Mapped[CreatorProfile] = relationship(back_populates="contacts")
