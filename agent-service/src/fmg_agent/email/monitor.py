"""Independent mailbox loops with connection-owned PostgreSQL leadership."""

from contextlib import contextmanager
from hashlib import sha256
import logging
from threading import Event, Thread

from sqlalchemy import text

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


def monitor_mailbox(settings: Settings, mailbox_id: str, stop: Event) -> None:
    registry = MailboxRegistry.load(settings)
    config = registry.settings_for(mailbox_id)
    engine, sessions = database(config)
    try:
        with sessions() as session:
            register_identities(session, registry)
            session.commit()
        while not stop.is_set():
            try:
                with mailbox_leader(engine, mailbox_id) as owner:
                    if owner:
                        while not stop.is_set():
                            # A dropped idle leader connection releases its lock.
                            # Detect that before another IMAP scan, then reacquire.
                            owner.execute(text("SELECT 1"))
                            owner.commit()
                            sync_once(sessions, config, mailbox_id=mailbox_id)
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
    registry = MailboxRegistry.load(settings)
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
