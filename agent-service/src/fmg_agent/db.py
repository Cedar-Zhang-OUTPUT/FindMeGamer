from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class AccessToken(Base):
    __tablename__ = "access_tokens"
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def database(settings):
    args = (
        {"check_same_thread": False}
        if settings.database_url.startswith("sqlite:")
        else {"connect_timeout": 5}
    )
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args=args,
    )
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
