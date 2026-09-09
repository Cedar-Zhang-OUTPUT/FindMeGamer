from datetime import timedelta
from email import policy
from email.parser import BytesParser
import smtplib
from uuid import UUID

from app.core.crypto import SecretCipher
from app.core.idempotency import utc_now
from app.db.models.activity_sending import ActivityDelivery
from app.outreach.smtp import SMTPGateway
from app.workers import activity_send_tasks as tasks
from app.workers.celery_app import celery_app
from tests.integration.test_activity_qualification import (
    ready_composition,
    preview,
    configure_smtp,
)
from tests.integration.test_activity_final_send import final_send, get_batch
from tests.integration.test_activity_preparation import post
from tests.integration.test_discovery_evaluation import sessions_for
from tests.unit.workers.test_outreach_tasks import SequenceLimiter


class CaptureSMTP:
    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.messages = []
        self.logins = []

    def factory(self, host, address, port, encryption, context, timeout):
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if outcome == "connect_timeout":
            raise TimeoutError("upstream secret")
        owner = self

        class Connection:
            def starttls(self, *, context):
                pass

            def login(self, username, password):
                owner.logins.append(username)
                assert password == "fixture-password"

            def send_message(self, message):
                owner.messages.append(
                    BytesParser(policy=policy.default).parsebytes(message.as_bytes())
                )
                if outcome == "unknown":
                    raise smtplib.SMTPServerDisconnected("upstream secret")
                if outcome == "reject":
                    raise smtplib.SMTPDataError(550, b"upstream secret")
                return {}

            def quit(self):
                pass

            def close(self):
                pass

        return Connection()


def worker(session, capture, *, limiter=None, dispatcher=None):
    gateway = SMTPGateway(
        factory=capture.factory, resolver=lambda host, port: ("8.8.8.8",)
    )
    return lambda identity: tasks.run_delivery(
        UUID(identity),
        session_factory=sessions_for(session),
        smtp_gateway=gateway,
        secret_cipher=SecretCipher(bytes(range(32))),
        limiter=limiter or SequenceLimiter(0),
        dispatcher=dispatcher,
    )


def seeded(client, session, monkeypatch, count=1):
    _, composition = ready_composition(client, session, monkeypatch, count=count)
    qualified = preview(client, composition).json()
    response = final_send(client, composition, qualified)
    assert response.status_code == 201, response.text
    return response.json()


def test_http_queue_worker_smtp_capture_uses_exact_snapshot_without_cta(
    auth_client, session, monkeypatch
):
    activity, composition = ready_composition(
        auth_client, session, monkeypatch, count=2
    )
    queued = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, args: queued.append((name, args))
    )
    batch = final_send(
        auth_client, composition, preview(auth_client, composition).json()
    ).json()
    assert len(queued) == 2 and all(
        name == "find_me_gamer.outreach.send_activity_delivery" for name, _ in queued
    )
    capture = CaptureSMTP()
    run = worker(session, capture)
    for _, args in queued:
        run(args[0])
    sent = get_batch(auth_client, batch["id"])
    assert [d["state"] for d in sent["deliveries"]] == ["sent", "sent"]
    assert len(capture.messages) == 2
    for delivery, message in zip(sent["deliveries"], capture.messages):
        frozen = delivery["snapshot"]
        assert str(message["To"]) == frozen["recipient_email"]
        assert str(message["From"]) == "Toki <producer@example.com>"
        assert str(message["Reply-To"]) == "reply@example.com"
        assert str(message["Subject"]) == frozen["subject"]
        html = message.get_body(preferencelist=("html",)).get_content().rstrip("\n")
        assert html == frozen["html"]
        assert "LIMINAL" not in html and "Choice=" not in html and "/r/" not in html
        assert "Yes, I'm in" not in html
    for _, args in queued:
        run(args[0])
    assert len(capture.messages) == 2


def test_known_connection_failure_can_explicitly_retry_same_frozen_delivery(
    auth_client, session, monkeypatch
):
    batch = seeded(auth_client, session, monkeypatch)
    identity = batch["deliveries"][0]["id"]
    capture = CaptureSMTP(["connect_timeout", "ok"])
    run = worker(session, capture)
    run(identity)
    failed = get_batch(auth_client, batch["id"])["deliveries"][0]
    assert failed["state"] == "failed" and failed["retryable"] and not capture.messages
    response = post(
        auth_client,
        f"/api/v2/outreach/deliveries/{identity}/retry",
        {"expected_attempt": failed["attempt"]},
    )
    assert response.status_code == 200, response.text
    run(identity)
    assert get_batch(auth_client, batch["id"])["deliveries"][0]["state"] == "sent"
    assert len(capture.messages) == 1


def test_unknown_submission_never_retries_until_explicit_not_sent_verification(
    auth_client, session, monkeypatch
):
    batch = seeded(auth_client, session, monkeypatch)
    identity = batch["deliveries"][0]["id"]
    capture = CaptureSMTP(["unknown", "ok"])
    run = worker(session, capture)
    run(identity)
    unknown = get_batch(auth_client, batch["id"])["deliveries"][0]
    assert unknown["state"] == "unknown" and not unknown["retryable"]
    assert "upstream secret" not in str(unknown)
    run(identity)
    assert len(capture.messages) == 1
    path = f"/api/v2/outreach/deliveries/{identity}"
    assert (
        post(
            auth_client, path + "/retry", {"expected_attempt": unknown["attempt"]}
        ).status_code
        == 409
    )
    resolved = post(
        auth_client,
        path + "/resolve",
        {
            "expected_attempt": unknown["attempt"],
            "outcome": "not_sent",
            "source_note": "Operator checked the provider submission logs; this message was not accepted.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert (
        resolved.json()["state"] == "failed"
        and resolved.json()["resolution"]["source_note"]
    )
    assert len(capture.messages) == 1
    assert (
        post(
            auth_client, path + "/retry", {"expected_attempt": unknown["attempt"]}
        ).status_code
        == 200
    )
    run(identity)
    assert len(capture.messages) == 2


def test_expired_sending_and_sender_change_do_not_silently_send(
    auth_client, session, monkeypatch
):
    batch = seeded(auth_client, session, monkeypatch)
    row = session.get(ActivityDelivery, UUID(batch["deliveries"][0]["id"]))
    row.state, row.attempt, row.sending_at = (
        "sending",
        1,
        utc_now() - timedelta(minutes=6),
    )
    row.lease_expires_at = utc_now() - timedelta(seconds=1)
    session.commit()
    assert get_batch(auth_client, batch["id"])["deliveries"][0]["state"] == "unknown"
    capture = CaptureSMTP()
    worker(session, capture)(str(row.id))
    assert not capture.messages


def test_changed_sending_account_after_final_confirmation_requires_new_review(
    auth_client, session, monkeypatch
):
    batch = seeded(auth_client, session, monkeypatch)
    configure_smtp(auth_client, username="other@example.com")
    capture = CaptureSMTP()
    worker(session, capture)(batch["deliveries"][0]["id"])
    failed = get_batch(auth_client, batch["id"])["deliveries"][0]
    assert (
        failed["state"] == "failed"
        and failed["error_code"] == "sending_account_changed"
    )
    assert not capture.messages and not capture.logins


def test_queue_failure_replays_same_committed_final_batch(
    auth_client, session, monkeypatch
):
    from uuid import uuid4

    _, composition = ready_composition(auth_client, session, monkeypatch, count=1)
    qualified = preview(auth_client, composition).json()
    request_id, key = uuid4(), str(uuid4())

    def unavailable(*args, **kwargs):
        raise RuntimeError("broker private")

    monkeypatch.setattr(celery_app, "send_task", unavailable)
    failed = final_send(
        auth_client, composition, qualified, request_id=request_id, key=key
    )
    assert failed.status_code == 503, failed.text
    old = auth_client.get(
        f"/api/v2/activities/{composition['activity_id']}/send-batches"
    ).json()["items"][0]
    queued = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, args: queued.append(args[0])
    )
    replay = final_send(
        auth_client, composition, qualified, request_id=request_id, key=key
    )
    assert replay.status_code == 201 and replay.json()["id"] == old["id"]
    assert queued == [old["deliveries"][0]["id"]]


def test_rate_limit_defers_without_smtp_submission(auth_client, session, monkeypatch):
    batch = seeded(auth_client, session, monkeypatch)
    capture, deferred = CaptureSMTP(), []

    class Dispatcher:
        def dispatch(self, identity, *, delay=0):
            deferred.append((str(identity), delay))

    worker(session, capture, limiter=SequenceLimiter(3), dispatcher=Dispatcher())(
        batch["deliveries"][0]["id"]
    )
    assert not capture.messages
    assert deferred == [(batch["deliveries"][0]["id"], 3)]
    assert get_batch(auth_client, batch["id"])["deliveries"][0]["state"] == "queued"


def test_explicit_rejection_is_failed_and_manual_verified_sent_never_resends(
    auth_client, session, monkeypatch
):
    batch = seeded(auth_client, session, monkeypatch)
    identity = batch["deliveries"][0]["id"]
    capture = CaptureSMTP(["reject", "unknown"])
    run = worker(session, capture)
    run(identity)
    failed = get_batch(auth_client, batch["id"])["deliveries"][0]
    assert failed["state"] == "failed" and failed["error_code"] == "smtp_rejected"
    assert (
        post(
            auth_client,
            f"/api/v2/outreach/deliveries/{identity}/retry",
            {"expected_attempt": failed["attempt"]},
        ).status_code
        == 200
    )
    run(identity)
    unknown = get_batch(auth_client, batch["id"])["deliveries"][0]
    response = post(
        auth_client,
        f"/api/v2/outreach/deliveries/{identity}/resolve",
        {
            "expected_attempt": unknown["attempt"],
            "outcome": "sent",
            "source_note": "Provider logs confirm this Message-ID was accepted.",
        },
    )
    assert response.status_code == 200 and response.json()["state"] == "sent"
    run(identity)
    assert len(capture.messages) == 2
    assert (
        post(
            auth_client,
            f"/api/v2/outreach/deliveries/{identity}/retry",
            {"expected_attempt": unknown["attempt"]},
        ).status_code
        == 409
    )


def test_new_send_routes_are_authenticated(client):
    from uuid import uuid4

    identity = uuid4()
    assert client.get(f"/api/v2/outreach/send-batches/{identity}").status_code == 401
    assert client.get(f"/api/v2/activities/{identity}/send-batches").status_code == 401
    for suffix in ("retry", "resolve"):
        assert (
            client.post(
                f"/api/v2/outreach/deliveries/{identity}/{suffix}", json={}
            ).status_code
            == 401
        )
    assert (
        client.post(
            f"/api/v2/outreach/compositions/{identity}/send-batches", json={}
        ).status_code
        == 401
    )
