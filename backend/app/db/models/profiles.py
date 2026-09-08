from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ProfileFieldsMixin(TimestampMixin):
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
    steam_app_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True
    )
    manual_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    reference_works: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    manual_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class CreatorProfile(ProfileFieldsMixin, Base):
    __tablename__ = "creator_profiles"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "platform_account_id",
            name="uq_creator_profiles_platform_account",
        ),
        CheckConstraint(
            "platform IN ('youtube', 'x', 'twitch', 'instagram')",
            name="ck_creator_profiles_platform",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    youtube_channel_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True
    )
    platform: Mapped[str] = mapped_column(
        String(32), nullable=False, default="youtube", server_default="youtube"
    )
    platform_account_id: Mapped[str | None] = mapped_column(String(128))
    identity_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    identity_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    manual_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    manual_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    manual_notes: Mapped[str | None] = mapped_column(Text)
    contacts: Mapped[list["CreatorContact"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan"
    )
    works: Mapped[list["CreatorWork"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan"
    )


class CreatorContact(TimestampMixin, Base):
    __tablename__ = "creator_contacts"
    __table_args__ = (
        Index(
            "uq_creator_contacts_active_manual_email",
            "creator_id",
            text("lower(email)"),
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
    identity_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    purpose: Mapped[str | None] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    manual_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creator: Mapped[CreatorProfile] = relationship(back_populates="contacts")


class CreatorWork(TimestampMixin, Base):
    __tablename__ = "creator_works"
    __table_args__ = (
        UniqueConstraint(
            "creator_id",
            "identity_revision",
            "platform",
            "source_content_id",
            name="uq_creator_works_source_identity",
        ),
        CheckConstraint(
            "platform IN ('youtube', 'x', 'twitch', 'instagram')",
            name="ck_creator_works_platform",
        ),
        CheckConstraint(
            "origin IN ('manual', 'source')", name="ck_creator_works_origin"
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
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    source_content_id: Mapped[str | None] = mapped_column(String(255))
    identity_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    source_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    manual_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    source_collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    creator: Mapped[CreatorProfile] = relationship(back_populates="works")


class CreatorIdentityBinding(Base):
    __tablename__ = "creator_identity_bindings"
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey("creator_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(128))
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
