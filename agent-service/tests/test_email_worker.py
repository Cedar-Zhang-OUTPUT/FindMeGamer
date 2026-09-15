from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from test_email_jobs import gateway, submit


def test_dispatch_recovers_pending_and_does_not_publish_failed_jobs(gateway):
    from fmg_agent.worker import dispatch_once
    from fmg_agent.email.jobs import JobStore

    app, client, token, _, _ = gateway
    store = JobStore(app.state.sessions)
    first = submit(client, token, key="first").json()["data"]["id"]
    second = submit(client, token, key="second").json()["data"]["id"]
    store.fail(second, store.claim(second), "model_output_invalid", retryable=True)
    published = []
    dispatch_once(store, published.append, retention_days=30)
    assert published == [first]

    # Broker errors do not remove durable pending work.
    def rejected(job_id):
        raise ConnectionError("test broker outage")

    with pytest.raises(ConnectionError):
        dispatch_once(store, rejected, retention_days=30)
    assert store.pending() == [first]


def test_cleanup_only_expires_terminal_new_jobs(gateway):
    from fmg_agent.worker import dispatch_once
    from fmg_agent.email.jobs import JobStore
    from fmg_agent.email.models import EmailJob

    app, client, token, _, _ = gateway
    store = JobStore(app.state.sessions)
    done = submit(client, token, key="done").json()["data"]["id"]
    queued = submit(client, token, key="queued").json()["data"]["id"]
    store.complete(done, store.claim(done), [])
    with app.state.sessions() as session:
        session.execute(
            update(EmailJob).values(
                updated_at=datetime.now(timezone.utc) - timedelta(days=31)
            )
        )
        session.commit()
    published = []
    dispatch_once(store, published.append, retention_days=30)
    assert published == [queued]
    assert store.load(queued)["state"] == "queued"
    from fmg_agent.errors import ApiError

    with pytest.raises(ApiError):
        store.load(done)


def test_revoked_owner_job_never_reaches_upstream(gateway):
    from fmg_agent.auth import revoke_token
    from fmg_agent.email.jobs import JobStore

    app, client, token, _, _ = gateway
    job_id = submit(client, token).json()["data"]["id"]
    with app.state.sessions() as session:
        revoke_token(session, token.id)
    store = JobStore(app.state.sessions)
    assert store.claim(job_id) is None
    assert store.load(job_id)["state"] == "failed"
    assert store.load(job_id)["error"]["code"] == "access_revoked"
