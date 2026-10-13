"""Durable job contracts; no paid network calls or legacy database access."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def gateway(tmp_path):
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token
    from fmg_agent.config import Settings
    from fmg_agent.db import Base

    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'jobs.sqlite'}"))
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as session:
        a = issue_token(session, label="a", scopes=["email:enrich"])
        b = issue_token(session, label="b", scopes=["email:enrich"])
        read = issue_token(session, label="read", scopes=["read"])
    with TestClient(app) as client:
        yield app, client, a, b, read


def headers(token, key="test-job"):
    return {"Authorization": f"Bearer {token.token}", "Idempotency-Key": key}


def submit(client, token, key="test-job", url="https://example.com/creator"):
    return client.post(
        "/v1/email/enrich", headers=headers(token, key), json={"url": url}
    )


def test_idempotent_submission_returns_same_job_and_conflicts_on_changed_input(gateway):
    _, client, a, _, _ = gateway
    first = submit(client, a)
    assert first.status_code == 202
    assert first.json()["data"]["state"] == "queued"
    assert submit(client, a).json()["data"]["id"] == first.json()["data"]["id"]
    changed = submit(client, a, url="https://example.com/other")
    assert changed.status_code == 409


def test_job_ownership_and_scope(gateway):
    _, client, a, b, read = gateway
    assert submit(client, read).status_code == 403
    response = submit(client, a)
    assert response.status_code == 202
    job_id = response.json()["data"]["id"]
    assert client.get(f"/v1/email/jobs/{job_id}", headers=headers(b)).status_code == 404
    assert (
        client.post(f"/v1/email/jobs/{job_id}/retry", headers=headers(b)).status_code
        == 404
    )
    assert submit(client, b).json()["data"]["id"] != job_id


def test_evidence_is_stored_and_part_of_idempotent_input(gateway):
    app, client, token, _, _ = gateway
    body = {
        "url": "https://www.youtube.com/@creator",
        "evidence": [
            {
                "source_url": "https://www.youtube.com/@creator",
                "text": "Gaming contact: team@example.com",
                "kind": "channel_description",
            }
        ],
    }
    first = client.post("/v1/email/enrich", headers=headers(token), json=body)
    assert first.status_code == 202
    assert (
        first.json()["data"]["input"]["evidence"][0]["text"]
        == body["evidence"][0]["text"]
    )
    assert (
        client.post("/v1/email/enrich", headers=headers(token), json=body).json()[
            "data"
        ]["id"]
        == first.json()["data"]["id"]
    )
    body["evidence"][0]["text"] = "Different evidence"
    assert (
        client.post("/v1/email/enrich", headers=headers(token), json=body).status_code
        == 409
    )


@pytest.mark.parametrize(
    "records",
    [
        [{"source_url": "https://example.com/", "text": "x" * 8001}],
        [{"source_url": "https://example.com/", "text": "x" * 8000}] * 5,
        [{"source_url": "https://example.com/", "text": "x"}] * 11,
        [{"source_url": "http://127.0.0.1/", "text": "contact"}],
        [
            {
                "source_url": "https://example.com/",
                "text": "contact",
                "email": "guessed@example.com",
            }
        ],
        [{"source_url": "https://example.com/", "text": 123}],
    ],
)
def test_evidence_admission_limits(gateway, records):
    _, client, token, _, _ = gateway
    response = client.post(
        "/v1/email/enrich",
        headers=headers(token),
        json={"url": "https://example.com/", "evidence": records},
    )
    assert response.status_code == 422


def test_legacy_input_remains_idempotent_after_optional_evidence_added(gateway):
    from fmg_agent.email.jobs import JobStore

    app, client, token, _, _ = gateway
    old = JobStore(app.state.sessions).create(
        token.id,
        "legacy",
        {"url": "https://example.com/creator", "name": None, "platform": None},
    )
    assert submit(client, token, key="legacy").json()["data"]["id"] == old["id"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/a",
        "http://169.254.169.254/",
        "https://[::1]/",
        "file:///tmp/a",
        "https://user:pass@example.com/",
    ],
)
def test_rejects_obviously_unsafe_targets(gateway, url):
    _, client, a, _, _ = gateway
    assert submit(client, a, url=url).status_code == 422


def test_successful_checkpoint_survives_failed_stage_and_explicit_retry(gateway):
    from fmg_agent.email.jobs import JobStore

    app, client, a, _, _ = gateway
    response = submit(client, a)
    assert response.status_code == 202
    job_id = response.json()["data"]["id"]
    store = JobStore(app.state.sessions)
    lease = store.claim(job_id)
    assert lease is not None
    assert store.claim(job_id) is None
    store.checkpoint(
        job_id,
        lease,
        "public_pages",
        {"emails": [], "source_url": "https://example.com/creator"},
    )
    store.fail(job_id, lease, "upstream_rate_limited", retryable=True)
    assert (
        client.get(f"/v1/email/jobs/{job_id}", headers=headers(a)).json()["data"][
            "state"
        ]
        == "failed"
    )
    retry = client.post(f"/v1/email/jobs/{job_id}/retry", headers=headers(a))
    assert retry.status_code == 202
    # A repeated retry while queued does not clear successful work.
    assert (
        client.post(f"/v1/email/jobs/{job_id}/retry", headers=headers(a)).status_code
        == 202
    )
    second_lease = store.claim(job_id)
    assert second_lease != lease
    assert store.load(job_id)["checkpoints"]["public_pages"]["emails"] == []
    # The previous execution cannot overwrite a new attempt.
    assert store.fail(job_id, lease, "late_failure", retryable=True) is False
    store.complete(job_id, second_lease, [])
    result = client.get(f"/v1/email/jobs/{job_id}", headers=headers(a)).json()["data"]
    assert result["state"] == "completed"
    assert result["emails"] == []
    assert result["error"] is None
    assert (
        client.post(f"/v1/email/jobs/{job_id}/retry", headers=headers(a)).status_code
        == 409
    )


def test_expired_execution_requires_explicit_retry_not_automatic_paid_replay(gateway):
    from fmg_agent.email.jobs import JobStore

    app, client, a, _, _ = gateway
    response = submit(client, a)
    assert response.status_code == 202
    job_id = response.json()["data"]["id"]
    store = JobStore(app.state.sessions)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    assert store.claim(job_id, now=past) is not None
    assert store.recover_expired() == 1
    result = store.load(job_id)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "execution_interrupted"
    assert job_id not in store.pending()
    assert (
        client.post(f"/v1/email/jobs/{job_id}/retry", headers=headers(a)).status_code
        == 202
    )
    assert job_id in store.pending()
