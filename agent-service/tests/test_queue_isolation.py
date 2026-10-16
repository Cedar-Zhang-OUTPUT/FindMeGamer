import pytest
from sqlalchemy import text

from test_send_pacing_postgres import pg_sending
from test_email_sending import sending
from test_mailbox_delivery import setup_mailboxes, draft


def test_worker_routes_and_concurrency(tmp_path):
    from fmg_agent.worker import worker_args, create_worker
    from fmg_agent.config import Settings

    for role, mailbox, queue, concurrency in [
        ("enrichment", None, "fmg_enrichment", 4),
        ("mail", "alpha", "fmg_mail.alpha", 2),
        ("mail", "beta", "fmg_mail.beta", 2),
    ]:
        args = worker_args(role, mailbox)
        assert f"--queues={queue}" in args
        assert f"--concurrency={concurrency}" in args
        app = create_worker(
            Settings(database_url=f"sqlite:///{tmp_path / 'routes.sqlite'}"),
            role=role,
            mailbox_id=mailbox,
        )
        assert [q.name for q in app.conf.task_queues] == [queue]
    for role, mailbox in [
        ("mail", None),
        ("other", None),
        ("mail", "bad.name"),
        ("enrichment", "alpha"),
    ]:
        with pytest.raises(ValueError):
            worker_args(role, mailbox)


def seed_batches(app, client, owner):
    from fmg_agent.outreach import OutreachTask, OutreachRecipient

    setup_mailboxes(app)
    ids = {}
    for name in ("alpha", "beta"):
        pid = draft(client, owner, name)
        with app.state.sessions() as session:
            session.add(
                OutreachTask(
                    id=name,
                    token_id=owner.id,
                    mailbox_id=name,
                    idempotency_key=name,
                    fingerprint="f",
                    revision="r",
                    state="sending",
                    name=name,
                    run_id=name,
                    template={},
                )
            )
            session.flush()
            for n in range(25):
                # Separate frozen previews ensure the same mailbox has > one budget.
                from fmg_agent.email.models import EmailPreview

                original = session.get(EmailPreview, pid)
                row = EmailPreview(
                    token_id=owner.id,
                    mailbox_id=name,
                    template_id=original.template_id,
                    template_version=original.template_version,
                    message=original.message,
                )
                session.add(row)
                session.flush()
                rid = f"{name}-{n:02}"
                session.add(
                    OutreachRecipient(
                        id=rid, task_id=name, creator_id=rid, preview_id=row.id
                    )
                )
                ids[rid] = name
            session.commit()
    return ids


def test_dispatch_filters_each_mailbox(sending, monkeypatch):
    from fmg_agent.dispatch import dispatch_once
    from fmg_agent.mail_runtime import set_runtime

    app, client, owner, _, _ = sending
    ids = seed_batches(app, client, owner)
    monkeypatch.setattr(
        "fmg_agent.dispatch.MailboxRegistry.load", lambda _: app.state.mailboxes
    )
    set_runtime(app.state.sessions, dispatch_enabled=True, send_enabled=True)
    published = []
    counts = dispatch_once(
        app.state.settings,
        app.state.sessions,
        lambda task, identifier, queue: published.append((task, identifier, queue)),
    )
    assert counts == {"fmg_enrichment": 0, "fmg_mail.alpha": 20, "fmg_mail.beta": 20}
    assert len(published) == 40
    for task, identifier, queue in published:
        assert task == "fmg_agent.outreach.send"
        assert queue == "fmg_mail." + ids[identifier]


def test_broker_failure_preserves_pending(sending, monkeypatch):
    from fmg_agent.dispatch import dispatch_once
    from fmg_agent.mail_runtime import set_runtime
    from fmg_agent.outreach import pending

    app, client, owner, _, _ = sending
    seed_batches(app, client, owner)
    monkeypatch.setattr(
        "fmg_agent.dispatch.MailboxRegistry.load", lambda _: app.state.mailboxes
    )
    set_runtime(app.state.sessions, dispatch_enabled=True, send_enabled=True)
    before = pending(app.state.sessions, mailbox_id="alpha")

    def reject(*args):
        raise ConnectionError("offline broker")

    with pytest.raises(ConnectionError):
        dispatch_once(app.state.settings, app.state.sessions, reject)
    assert pending(app.state.sessions, mailbox_id="alpha") == before


def test_mixed_retries_share_budget_without_starving_other_mailbox(
    sending, monkeypatch
):
    from fmg_agent.dispatch import dispatch_once
    from fmg_agent.email.models import EmailSend, EmailBounceRetry
    from fmg_agent.email.safety import SenderSafety
    from fmg_agent.email.jobs import utcnow, JobStore
    from datetime import timedelta

    app, client, owner, _, _ = sending
    seed_batches(app, client, owner)
    monkeypatch.setattr(
        "fmg_agent.dispatch.MailboxRegistry.load", lambda _: app.state.mailboxes
    )
    for n in range(25):
        JobStore(app.state.sessions).create(
            owner.id, f"enrich-{n}", {"url": "https://example.com"}
        )
    for name in ("alpha", "beta"):
        with app.state.sessions() as session:
            session.add(SenderSafety(sender=name + "@example.com"))
            session.commit()
        for n in range(12):
            original, child = draft(client, owner, name), draft(client, owner, name)
            with app.state.sessions() as session:
                row = EmailSend(
                    token_id=owner.id,
                    preview_id=original,
                    idempotency_key=f"{name}-retry-{n}",
                    state="sent",
                )
                session.add(row)
                session.flush()
                session.add(
                    EmailBounceRetry(
                        original_send_id=row.id,
                        preview_id=child,
                        state="queued",
                        due_at=utcnow() - timedelta(seconds=1),
                    )
                )
                session.commit()
    published = []
    counts = dispatch_once(
        app.state.settings,
        app.state.sessions,
        lambda task, identifier, queue: published.append((task, identifier, queue)),
    )
    assert counts == {"fmg_enrichment": 20, "fmg_mail.alpha": 20, "fmg_mail.beta": 20}
    for name in ("alpha", "beta"):
        tasks = [task for task, _, queue in published if queue == "fmg_mail." + name]
        assert tasks.count("fmg_agent.email.bounce_retry") == 10
        assert tasks.count("fmg_agent.outreach.send") == 10
    from fmg_agent.mail_runtime import set_runtime

    set_runtime(app.state.sessions, dispatch_enabled=False, send_enabled=True)
    assert all(
        value == 0
        for value in dispatch_once(
            app.state.settings,
            app.state.sessions,
            lambda *args: pytest.fail("closed dispatcher published work"),
        ).values()
    )


@pytest.mark.postgres
def test_second_dispatcher_does_not_publish(pg_sending):
    from fmg_agent.dispatch import dispatch_leader

    app, _, _ = pg_sending
    with dispatch_leader(app.state.engine) as first:
        assert first is not None
        with dispatch_leader(app.state.engine) as second:
            assert second is None
    with dispatch_leader(app.state.engine) as next_owner:
        assert next_owner is not None


def test_actual_mail_worker_rejects_other_mailbox(sending, monkeypatch):
    from fmg_agent.worker import create_worker
    from fmg_agent.outreach import OutreachTask

    app, client, owner, _, _ = sending
    seed_batches(app, client, owner)
    monkeypatch.setattr(
        "fmg_agent.worker.MailboxRegistry.load", lambda _: app.state.mailboxes
    )
    calls = []
    monkeypatch.setattr(
        "fmg_agent.email.smtp.deliver",
        lambda *args: calls.append(args) or {"state": "sent"},
    )
    alpha = create_worker(app.state.settings, role="mail", mailbox_id="alpha")
    beta = create_worker(app.state.settings, role="mail", mailbox_id="beta")
    assert (
        alpha.tasks["fmg_agent.outreach.send"].run("beta-00")["code"]
        == "mailbox_queue_mismatch"
    )
    assert (
        beta.tasks["fmg_agent.outreach.send"].run("alpha-00")["code"]
        == "mailbox_queue_mismatch"
    )
    assert calls == []
    with app.state.sessions() as session:
        assert session.get(OutreachTask, "alpha").state == "sending"
    from test_email_sending import send
    from test_bounce_safety import dsn
    from test_bounce_retry import retry_row, advance
    from fmg_agent.email.inbox import ingest

    app.state.smtp_transport = lambda *args: {"state": "sent"}
    sid = send(client, owner, draft(client, owner, "alpha"), key="worker-retry").json()[
        "data"
    ]["id"]
    ingest(
        app.state.sessions, "junk", "1", 1, dsn(sid, "worker-retry"), mailbox_id="alpha"
    )
    advance(monkeypatch, retry_row(app, sid).due_at)
    assert (
        beta.tasks["fmg_agent.email.bounce_retry"].run(sid)["code"]
        == "mailbox_queue_mismatch"
    )
    assert retry_row(app, sid).state == "queued"
    assert calls == []


@pytest.mark.postgres
def test_leadership_loss_stops_next_publication(pg_sending):
    from fmg_agent.dispatch import dispatch_leader, dispatch_once
    from fmg_agent.email.monitor import leader_sessions
    from fmg_agent.email.jobs import JobStore

    app, _, owner = pg_sending
    for n in range(3):
        JobStore(app.state.sessions).create(
            owner.id, f"lost-{n}", {"url": "https://example.com"}
        )
    published = []
    with pytest.raises(Exception):
        with dispatch_leader(app.state.engine) as leader:
            pid = leader.scalar(text("SELECT pg_backend_pid()"))
            leader.commit()

            def publish(*args):
                published.append(args)
                with app.state.engine.begin() as other:
                    other.execute(
                        text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                    )

            dispatch_once(app.state.settings, leader_sessions(leader), publish)
    assert len(published) == 1
    assert len(JobStore(app.state.sessions).pending()) == 3


@pytest.mark.postgres
def test_dispatch_shared_gate_survives_internal_commits(pg_sending):
    from fmg_agent.dispatch import dispatch_leader, dispatch_once
    from fmg_agent.email.monitor import leader_sessions
    from fmg_agent.email.jobs import JobStore
    from fmg_agent.mail_runtime import set_runtime
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    app, _, owner = pg_sending
    JobStore(app.state.sessions).create(
        owner.id, "dispatch-hold", {"url": "https://example.com"}
    )
    started = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:

        def hold():
            started.set()
            return set_runtime(
                app.state.sessions, dispatch_enabled=False, send_enabled=False
            )

        def publish(*args):
            future = pool.submit(hold)
            assert started.wait(5)
            # PostgreSQL reports the exclusive transaction waiting on our share lock.
            with app.state.engine.connect() as observer:
                from time import monotonic

                deadline = monotonic() + 3
                while monotonic() < deadline:
                    waiting = observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock' AND query LIKE '%mail_runtime%FOR UPDATE%'"
                        )
                    )
                    if waiting:
                        break
                assert waiting
            assert not future.done()

        with dispatch_leader(app.state.engine) as leader:
            counts = dispatch_once(app.state.settings, leader_sessions(leader), publish)
        assert counts["fmg_enrichment"] == 1


@pytest.mark.postgres
def test_fenced_dispatch_persists_recovery(pg_sending):
    from fmg_agent.dispatch import dispatch_leader, dispatch_once
    from fmg_agent.email.monitor import leader_sessions
    from fmg_agent.email.jobs import JobStore

    app, _, owner = pg_sending
    store = JobStore(app.state.sessions)
    job = store.create(owner.id, "expired-dispatch", {"url": "https://example.com"})
    store.claim(job["id"])
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE email_jobs SET lease_until=now()-interval '1 hour'"))
    with dispatch_leader(app.state.engine) as leader:
        dispatch_once(app.state.settings, leader_sessions(leader), lambda *args: None)
    assert store.load(job["id"])["state"] == "failed"
