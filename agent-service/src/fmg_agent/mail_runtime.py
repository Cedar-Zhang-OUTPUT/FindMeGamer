"""Persistent maintenance gates; PostgreSQL row locks drain active senders."""

from contextlib import contextmanager

from sqlalchemy import Boolean, CheckConstraint, Integer, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .errors import ApiError


class MailRuntime(Base):
    __tablename__ = "mail_runtime"
    __table_args__ = (CheckConstraint("id = 1", name="mail_runtime_singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    dispatch_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    send_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


def maintenance():
    return ApiError(
        503, "mail_service_maintenance", "Mail service is under maintenance."
    )


@contextmanager
def runtime_gate(sessions, *, sending=False, both=False):
    """Shared lock outlives the external side effect; missing schema fails closed.

    SQLite supports offline functional tests only; production concurrency relies
    on PostgreSQL FOR SHARE / FOR UPDATE, including across separate processes.
    """
    with sessions() as session:
        try:
            row = session.scalar(
                select(MailRuntime)
                .where(MailRuntime.id == 1)
                .with_for_update(read=True)
            )
        except SQLAlchemyError:
            raise maintenance() from None
        if (
            row is None
            or not (row.send_enabled if sending else row.dispatch_enabled)
            or (both and not (row.dispatch_enabled and row.send_enabled))
        ):
            raise maintenance()
        # Pin the physical connection: a failed transaction must not reconnect
        # while assuming the old shared lock is still held.
        connection = session.connection()
        physical = connection.connection.driver_connection

        def check():
            if (
                connection.closed
                or connection.invalidated
                or connection.connection.driver_connection is not physical
            ):
                raise maintenance()
            connection.execute(text("SELECT 1"))

        yield check
        # Fenced dispatcher sessions share this owner transaction. Their cleanup
        # and interrupted-work recovery must persist before releasing the gate.
        session.commit()


def set_runtime(sessions, *, dispatch_enabled: bool, send_enabled: bool) -> dict:
    """Administrative operation; never exposed through a token-owned API."""
    with sessions() as session:
        row = session.scalar(
            select(MailRuntime).where(MailRuntime.id == 1).with_for_update()
        )
        if row is None:
            row = MailRuntime(id=1)
            session.add(row)
        row.dispatch_enabled = dispatch_enabled
        row.send_enabled = send_enabled
        session.commit()
    return {"dispatch_enabled": dispatch_enabled, "send_enabled": send_enabled}


def check_readiness(settings, sessions, *, registry=None):
    """Fail startup until migration and historical identity verification finish."""
    from .mailboxes import MailboxRegistry
    from .email.identity import register_identities, backfill_mailboxes

    registry = registry or MailboxRegistry.load(settings)
    with sessions() as session:
        revision = session.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != "0013_mail_runtime":
            raise RuntimeError("Mail runtime schema migration is required")
        if session.get(MailRuntime, 1) is None:
            raise RuntimeError("Mail runtime singleton is missing")
        register_identities(session, registry)
        report = backfill_mailboxes(session, registry)
        if report["previews"] or report["tasks"]:
            raise RuntimeError("Mailbox identity backfill is required")
        session.commit()
    return registry
