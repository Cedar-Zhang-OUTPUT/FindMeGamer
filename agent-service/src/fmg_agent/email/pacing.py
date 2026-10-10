"""One durable mailbox gate shared by API processes and outreach workers."""

from contextlib import contextmanager
from datetime import timedelta, timezone
from hashlib import sha256
from math import ceil

from sqlalchemy import func, select, update

from .models import EmailSendGate

# Longer than the worker's 600-second hard timeout. A killed process leaves a
# conservative cooldown; live_lock protects still-running API transports too.
SEND_LEASE_SECONDS = 630


@contextmanager
def live_lock(sessions, sender, interval):
    """Keep a live transport exclusive even after its recovery lease expires."""
    with sessions() as session:
        if not interval or session.get_bind().dialect.name == "sqlite":
            # SQLite is only used by offline fixtures; reserve's CAS still applies.
            yield True
            return
        if session.get_bind().dialect.name != "postgresql":
            raise RuntimeError("Unsupported send gate database")
        lock_key = int.from_bytes(
            sha256(("fmg-email:" + sender.casefold()).encode()).digest()[:8],
            "big",
            signed=True,
        )
        # A separate transaction stays open through transport + receipt commit.
        # Closing this session releases the lock, including on errors/process exit.
        yield session.scalar(select(func.pg_try_advisory_xact_lock(lock_key)))


def shared_now(session, fallback):
    if session.get_bind().dialect.name == "postgresql":
        return session.scalar(select(func.clock_timestamp()))
    return fallback


def reserve(session, sender, send_id, now, interval):
    """Reserve in the same transaction as EmailSend; return wait seconds if busy."""
    if not interval:
        return None
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Unsupported send gate database")
    now = shared_now(session, now)
    sender = sender.casefold()
    session.execute(
        insert(EmailSendGate)
        .values(sender=sender, available_at=now, lease_id=None)
        .on_conflict_do_nothing(index_elements=["sender"])
    )
    acquired = session.execute(
        update(EmailSendGate)
        .where(
            EmailSendGate.sender == sender,
            EmailSendGate.available_at <= now,
            EmailSendGate.lease_id.is_(None),
        )
        .values(
            available_at=now + timedelta(seconds=SEND_LEASE_SECONDS), lease_id=send_id
        )
    ).rowcount
    if acquired:
        return None
    # live_lock proves the old PostgreSQL owner is no longer running. An expired
    # lease alone does not prove when it last contacted the provider: start a
    # fresh cooldown once, rather than immediately sending after an interruption.
    session.execute(
        update(EmailSendGate)
        .where(
            EmailSendGate.sender == sender,
            EmailSendGate.available_at <= now,
            EmailSendGate.lease_id.is_not(None),
        )
        .values(available_at=now + timedelta(seconds=interval), lease_id=None)
    )
    gate = session.get(EmailSendGate, sender, populate_existing=True)
    if gate.lease_id:
        return max(1, interval)
    available = gate.available_at
    if available.tzinfo is None:
        available = available.replace(tzinfo=timezone.utc)
    return max(1, ceil((available - now).total_seconds()))


def finish(session, sender, send_id, now, interval):
    if not interval:
        return
    now = shared_now(session, now)
    session.execute(
        update(EmailSendGate)
        .where(
            EmailSendGate.sender == sender.casefold(), EmailSendGate.lease_id == send_id
        )
        .values(available_at=now + timedelta(seconds=interval), lease_id=None)
    )
