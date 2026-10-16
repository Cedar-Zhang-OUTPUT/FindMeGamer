"""Offline mailbox isolation and real PostgreSQL monitor leadership."""

from threading import Event, Thread
from email.message import EmailMessage
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_email_sending import sending
from test_inbox import sent_task
from test_send_pacing_postgres import pg_sending


def test_same_uid_across_mailboxes_is_independent(sending):
    from fmg_agent.email.inbox import ingest, EmailReply
    from fmg_agent.email.models import EmailPreview, EmailSend, MailboxIdentity

    app, *_ = sending
    sent_task(sending)
    with app.state.sessions() as session:
        pairs = session.execute(
            select(EmailSend, EmailPreview).join(EmailPreview)
        ).all()
        session.add(MailboxIdentity(id="second", sender="second@example.com"))
        session.flush()
        pairs[1][1].mailbox_id = "second"
        pairs[1][1].message = {**pairs[1][1].message, "from": "second@example.com"}
        session.commit()
    for index, (send, preview) in enumerate(pairs):
        mail = EmailMessage()
        mail["From"] = preview.message["to"]
        mail["Message-ID"] = "<same-uid@example.com>"
        mail["In-Reply-To"] = f"<fmg-{send.id}@example.com>"
        mail.set_content("Interested")
        assert (
            ingest(
                app.state.sessions,
                "box",
                "1",
                7,
                mail.as_bytes(),
                mailbox_id="ontologyplay" if index == 0 else "second",
            )
            == "human"
        )
    with app.state.sessions() as session:
        assert set(session.scalars(select(EmailReply.send_id))) == {
            s.id for s, _ in pairs
        }


def test_foreign_reference_does_not_pause_other_mailbox(sending):
    from fmg_agent.email.inbox import ingest, EmailReply
    from fmg_agent.email.models import EmailSend
    from test_bounce_safety import dsn

    app, *_ = sending
    sent_task(sending)
    with app.state.sessions() as session:
        sid = session.scalar(select(EmailSend.id))
    assert (
        ingest(
            app.state.sessions,
            "foreign",
            "1",
            1,
            dsn(sid, "foreign"),
            mailbox_id="second",
        )
        == "unmatched"
    )
    with app.state.sessions() as session:
        assert session.scalar(select(EmailReply.id)) is None


@pytest.mark.parametrize("mailbox_id", ["ontologyplay", None])
def test_unbound_preview_never_matches(sending, mailbox_id):
    from fmg_agent.email.inbox import ingest, EmailReply
    from fmg_agent.email.models import EmailSend, EmailPreview
    from test_bounce_safety import dsn

    app, *_ = sending
    sent_task(sending)
    with app.state.sessions() as session:
        send = session.scalar(select(EmailSend))
        session.get(EmailPreview, send.preview_id).mailbox_id = None
        session.commit()
    assert (
        ingest(
            app.state.sessions,
            "box",
            "1",
            1,
            dsn(send.id, "unbound"),
            mailbox_id=mailbox_id,
        )
        == "unmatched"
    )
    with app.state.sessions() as session:
        assert session.scalar(select(EmailReply.id)) is None


def test_existing_cursor_is_preserved(sending):
    from fmg_agent.email.inbox import InboxCursor, scan_folder, mailbox_key

    app, *_ = sending
    cfg = app.state.settings
    key = mailbox_key(cfg)
    with app.state.sessions() as session:
        session.add(InboxCursor(id=key, uidvalidity="1", last_uid=777))
        session.commit()

    class EmptyInbox:
        def select(self, folder, readonly):
            return "OK", []

        def response(self, name):
            return name, [b"1"]

        def uid(self, action, charset, criteria):
            assert criteria == "(UID 778:*)"
            return "OK", [b""]

    scan_folder(
        app.state.sessions,
        cfg,
        EmptyInbox(),
        cfg.imap_folder,
        mailbox_id="ontologyplay",
    )
    with app.state.sessions() as session:
        assert session.get(InboxCursor, key).last_uid == 777


@pytest.mark.postgres
def test_duplicate_monitor_has_one_owner(pg_sending):
    from fmg_agent.email.monitor import mailbox_leader

    app, *_ = pg_sending
    mailbox_id = "leader-" + uuid4().hex
    with mailbox_leader(app.state.engine, mailbox_id) as first:
        assert first
        with mailbox_leader(app.state.engine, mailbox_id) as second:
            assert not second
        with mailbox_leader(app.state.engine, mailbox_id + "-other") as other:
            assert other
    with mailbox_leader(app.state.engine, mailbox_id) as next_owner:
        assert next_owner


@pytest.mark.postgres
def test_duplicate_monitor_does_not_scan(pg_sending, monkeypatch):
    from contextlib import contextmanager
    from fmg_agent.email import monitor
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile

    app, *_ = pg_sending
    stop, entered, release, contender_done = Event(), Event(), Event(), Event()
    registry = MailboxRegistry(
        app.state.settings,
        [
            MailboxProfile(
                id="duplicate",
                smtp_from="duplicate@example.com",
                imap_host="imap.example.com",
                imap_username="duplicate",
                imap_password="offline",
            )
        ],
        legacy=False,
    )
    monkeypatch.setattr(MailboxRegistry, "load", lambda settings: registry)
    calls = []

    def sync(sessions, settings, *, mailbox_id):
        calls.append(mailbox_id)
        entered.set()
        assert release.wait(10)

    real_leader = monitor.mailbox_leader

    @contextmanager
    def observed_leader(engine, mailbox_id):
        with real_leader(engine, mailbox_id) as owner:
            yield owner
        if not owner:
            contender_done.set()

    monkeypatch.setattr(monitor, "sync_once", sync)
    monkeypatch.setattr(monitor, "mailbox_leader", observed_leader)
    first = Thread(
        target=monitor.monitor_mailbox, args=(app.state.settings, "duplicate", stop)
    )
    second = Thread(
        target=monitor.monitor_mailbox, args=(app.state.settings, "duplicate", stop)
    )
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert contender_done.wait(5)
    finally:
        stop.set()
        release.set()
        first.join(10)
        if second.ident is not None:
            second.join(10)
    assert not first.is_alive() and not second.is_alive()
    assert calls == ["duplicate"]


@pytest.mark.postgres
def test_lost_leader_reacquires_before_next_scan(pg_sending, monkeypatch):
    from contextlib import contextmanager
    from hashlib import sha256
    from sqlalchemy import text
    from fmg_agent.email import monitor
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile

    app, *_ = pg_sending
    stop = Event()
    mailbox_id = "disconnect-" + uuid4().hex[:20]
    profile = MailboxProfile(id=mailbox_id, smtp_from="lost@example.com").model_copy(
        update={"imap_poll_seconds": 0.01}
    )
    registry = MailboxRegistry(app.state.settings, [profile], legacy=False)
    monkeypatch.setattr(MailboxRegistry, "load", lambda settings: registry)
    real_leader = monitor.mailbox_leader
    acquisitions, scans = [], []

    @contextmanager
    def observed_leader(engine, identity):
        with real_leader(engine, identity) as owner:
            if owner:
                acquisitions.append(identity)
            yield owner

    def sync(sessions, settings, *, mailbox_id):
        scans.append(len(acquisitions))
        if len(scans) == 1:
            key = int.from_bytes(
                sha256(f"fmg-inbox:{mailbox_id}".encode()).digest()[:8], "big"
            )
            with app.state.engine.begin() as connection:
                pid = connection.scalar(
                    text(
                        "SELECT pid FROM pg_locks WHERE locktype='advisory' "
                        "AND classid=:high AND objid=:low AND granted"
                    ),
                    {"high": key >> 32, "low": key & 0xFFFFFFFF},
                )
                assert pid is not None
                assert connection.scalar(
                    text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                )
        else:
            stop.set()

    monkeypatch.setattr(monitor, "mailbox_leader", observed_leader)
    monkeypatch.setattr(monitor, "sync_once", sync)
    thread = Thread(
        target=monitor.monitor_mailbox, args=(app.state.settings, mailbox_id, stop)
    )
    thread.start()
    try:
        assert stop.wait(5)
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()
    assert scans == [1, 2]


@pytest.mark.postgres
def test_stalled_a_does_not_stop_b_monitor(pg_sending, monkeypatch):
    from fmg_agent.email import monitor
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile
    from fmg_agent.email.inbox import InboxCursor, mailbox_key

    app, *_ = pg_sending
    stop, entered, release, progressed = Event(), Event(), Event(), Event()
    profiles = [
        MailboxProfile(
            id=key,
            smtp_from=key + "@example.com",
            imap_host="imap.example.com",
            imap_username=key,
            imap_password="offline",
        )
        for key in ("a", "b")
    ]
    registry = MailboxRegistry(app.state.settings, profiles, legacy=False)
    monkeypatch.setattr(MailboxRegistry, "load", lambda settings: registry)

    def sync(sessions, settings, *, mailbox_id):
        if mailbox_id == "a":
            entered.set()
            assert release.wait(10)
        else:
            assert entered.wait(5)
            with sessions() as session:
                session.add(InboxCursor(id=mailbox_key(settings), last_uid=9))
                session.commit()
            progressed.set()
            stop.set()

    monkeypatch.setattr(monitor, "sync_once", sync)
    thread = Thread(target=monitor.run_monitors, args=(app.state.settings, stop))
    thread.start()
    try:
        assert entered.wait(5)
        assert progressed.wait(5)
        with app.state.sessions() as session:
            assert (
                session.get(
                    InboxCursor, mailbox_key(registry.settings_for("b"))
                ).last_uid
                == 9
            )
    finally:
        stop.set()
        release.set()
        thread.join(10)
    assert not thread.is_alive()
