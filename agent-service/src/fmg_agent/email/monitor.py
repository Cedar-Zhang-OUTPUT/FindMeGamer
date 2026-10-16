"""Independent mailbox loops with connection-owned PostgreSQL leadership."""

from contextlib import contextmanager
from hashlib import sha256
import logging
from threading import Event, Thread

from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from ..config import Settings
from ..db import database
from ..mailboxes import MailboxRegistry
from .identity import register_identities
from .inbox import sync_once


@contextmanager
def mailbox_leader(engine, mailbox_id: str):
    """Hold the lock on a dedicated connection throughout each monitor loop."""
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Mailbox monitors require PostgreSQL leadership")
    key = int.from_bytes(
        sha256(f"fmg-inbox:{mailbox_id}".encode()).digest()[:8], "big", signed=True
    )
    with engine.connect() as connection:
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        )
        connection.commit()
        try:
            yield connection if acquired else None
        finally:
            if acquired:
                try:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                    )
                    connection.commit()
                except Exception:
                    # Never return a possibly still locked connection to the pool.
                    connection.invalidate()
                    raise


def leader_sessions(owner):
    """Fence every scan transaction to the physical backend owning its lock.

    A socket read may finish after leadership is lost. Its later ORM writes
    must fail on the dead owner, never reconnect onto an unlocked backend.
    """
    physical = owner.connection.driver_connection
    factory = sessionmaker(bind=owner, expire_on_commit=False)

    def check(*args):
        if (
            owner.closed
            or owner.invalidated
            or owner.connection.driver_connection is not physical
        ):
            raise RuntimeError("Mailbox leadership connection was lost")

    @contextmanager
    def sessions():
        check()
        with factory() as session:
            for name in ("after_begin", "before_flush", "before_commit"):
                event.listen(session, name, check)
            yield session

    return sessions


def monitor_mailbox(settings: Settings, mailbox_id: str, stop: Event) -> None:
    registry = MailboxRegistry.load(settings)
    config = registry.settings_for(mailbox_id)
    engine, sessions = database(config)
    try:
        initialized = False
        while not stop.is_set():
            try:
                if not initialized:
                    with sessions() as session:
                        register_identities(session, registry)
                        session.commit()
                    initialized = True
                with mailbox_leader(engine, mailbox_id) as owner:
                    if owner:
                        fenced_sessions = leader_sessions(owner)
                        while not stop.is_set():
                            # A dropped idle leader connection releases its lock.
                            # Detect that before another IMAP scan, then reacquire.
                            owner.execute(text("SELECT 1"))
                            owner.commit()
                            sync_once(fenced_sessions, config, mailbox_id=mailbox_id)
                            if stop.wait(config.imap_poll_seconds):
                                break
            except Exception:
                logging.getLogger(__name__).warning(
                    "Mailbox monitor unavailable; cursor retained."
                )
            stop.wait(config.imap_poll_seconds)
    finally:
        engine.dispose()


def run_monitors(settings: Settings, stop: Event) -> None:
    from ..mail_runtime import check_readiness

    engine, sessions = database(settings)
    try:
        registry = check_readiness(settings, sessions)
    finally:
        engine.dispose()
    threads = [
        Thread(
            target=monitor_mailbox,
            args=(settings, profile.id, stop),
            name=f"fmg-inbox-{profile.id}",
        )
        for profile in registry.profiles()
        if profile.enabled
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def main():
    stop = Event()
    import signal

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    run_monitors(Settings(), stop)


if __name__ == "__main__":
    main()
