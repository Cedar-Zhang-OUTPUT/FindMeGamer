from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html import escape
from threading import Barrier
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.outreach.batches import response_token_digest
from app.db.models.outreach import (
    CampaignCreatorResponse,
    Delivery,
    DeliverySendState,
    ResponseState,
    SendBatch,
    SendBatchState,
    Template,
)
from tests.integration.test_send_batch_api import (
    SEND_BATCH_PATH,
    _cleanup_committed_send_fixture,
    _committed_send_fixture,
    _concurrent_client,
    _create_batch,
    _payload,
    _published_match,
)


TOKEN_CIPHER = SecretCipher(bytes(range(32)))


def _sent_delivery(
    session: Session,
    *,
    accepted_label: str = "Yes, I am interested",
    declined_label: str = "No, thank you",
    superseded: bool = False,
) -> tuple[Delivery, str]:
    _task, creators, campaign = _published_match(
        session, [(f"Response Creator {uuid4()}", "response@example.com")]
    )
    template = Template(
        name=f"Response Template {uuid4()}",
        version=1,
        subject_template="Hello",
        body_markdown="Invitation",
        accepted_label=accepted_label,
        declined_label=declined_label,
        is_default=False,
    )
    session.add(template)
    session.flush()
    batch = SendBatch(
        campaign_id=campaign.id,
        template_id=template.id,
        requested_creator_ids=[str(creators[0].id)],
        state=SendBatchState.SENT,
    )
    session.add(batch)
    session.flush()
    delivery_id = uuid4()
    raw_token = TOKEN_CIPHER.derive_outreach_response_token(delivery_id)
    now = datetime.now(UTC)
    delivery = Delivery(
        id=delivery_id,
        campaign_id=campaign.id,
        send_batch_id=batch.id,
        creator_id=creators[0].id,
        recipient_email="response@example.com",
        rendered_subject="Hello",
        rendered_markdown="Invitation",
        rendered_html="<p>Invitation</p>",
        template_name=template.name,
        template_version=1,
        accepted_label=accepted_label,
        declined_label=declined_label,
        sender_name="Find Me Gamer",
        sender_address="sender@example.com",
        reply_to="reply@example.com",
        send_state=DeliverySendState.SENT,
        response_state=ResponseState.NO_RESPONSE,
        response_token_digest=response_token_digest(raw_token),
        sending_at=now,
        sent_at=now,
        superseded_at=now if superseded else None,
    )
    session.add(delivery)
    session.flush()
    return delivery, raw_token


def _delivery_state(delivery: Delivery) -> tuple[object, ...]:
    return (
        delivery.send_state,
        delivery.response_state,
        delivery.sending_at,
        delivery.sent_at,
        delivery.responded_at,
        delivery.superseded_at,
        delivery.created_at,
        delivery.updated_at,
    )


def test_get_current_sent_capability_renders_confirmation_without_mutation(
    client: TestClient, session: Session
) -> None:
    accepted = '<script>alert("accepted")</script>'
    declined = "No & thanks"
    delivery, token = _sent_delivery(
        session, accepted_label=accepted, declined_label=declined
    )
    before = _delivery_state(delivery)

    response = client.get(f"/r/{token}?choice=accepted")

    session.expire_all()
    stored = session.get(Delivery, delivery.id)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert f'action="/r/{token}"' in response.text
    assert 'method="post"' in response.text
    assert 'value="accepted" checked' in response.text
    assert 'value="declined"' in response.text
    assert escape(accepted) in response.text
    assert escape(declined) in response.text
    assert accepted not in response.text
    assert "https://" not in response.text
    assert "http://" not in response.text
    assert stored is not None and _delivery_state(stored) == before
    assert (
        session.scalar(select(func.count()).select_from(CampaignCreatorResponse)) == 0
    )


def test_scanner_get_invalid_choice_token_and_superseded_token_are_read_only(
    client: TestClient, session: Session
) -> None:
    current, token = _sent_delivery(session)
    superseded, old_token = _sent_delivery(session, superseded=True)
    states = {
        current.id: _delivery_state(current),
        superseded.id: _delivery_state(superseded),
    }

    scanner = client.get(f"/r/{token}?choice=declined")
    invalid_choice = client.get(f"/r/{token}?choice=maybe")
    invalid_token = client.get("/r/not-a-capability?choice=accepted")
    inactive = client.get(f"/r/{old_token}?choice=accepted")

    session.expire_all()
    assert scanner.status_code == 200
    assert invalid_choice.status_code == 400
    assert invalid_token.status_code == 404
    assert inactive.status_code == 200
    assert "inactive" in inactive.text.casefold()
    assert "<form" not in inactive.text.casefold()
    assert all(
        _delivery_state(session.get(Delivery, delivery_id)) == state
        for delivery_id, state in states.items()
    )
    assert (
        session.scalar(select(func.count()).select_from(CampaignCreatorResponse)) == 0
    )


def test_first_valid_post_wins_for_current_and_superseded_capabilities(
    client: TestClient, session: Session
) -> None:
    old, old_token = _sent_delivery(session)
    old.superseded_at = datetime.now(UTC)
    replacement_id = uuid4()
    replacement_token = TOKEN_CIPHER.derive_outreach_response_token(replacement_id)
    replacement_batch = SendBatch(
        campaign_id=old.campaign_id,
        template_id=None,
        requested_creator_ids=[str(old.creator_id)],
        state=SendBatchState.SENT,
    )
    session.add(replacement_batch)
    session.flush()
    now = datetime.now(UTC)
    replacement = Delivery(
        id=replacement_id,
        campaign_id=old.campaign_id,
        send_batch_id=replacement_batch.id,
        creator_id=old.creator_id,
        resends_delivery_id=old.id,
        recipient_email=old.recipient_email,
        rendered_subject=old.rendered_subject,
        rendered_markdown=old.rendered_markdown,
        rendered_html=old.rendered_html,
        template_name=old.template_name,
        template_version=old.template_version,
        accepted_label=old.accepted_label,
        declined_label=old.declined_label,
        sender_name=old.sender_name,
        sender_address=old.sender_address,
        reply_to=old.reply_to,
        send_state=DeliverySendState.SENT,
        response_state=ResponseState.NO_RESPONSE,
        response_token_digest=response_token_digest(replacement_token),
        sending_at=now,
        sent_at=now,
    )
    session.add(replacement)
    session.flush()

    first = client.post(f"/r/{replacement_token}", data={"choice": "accepted"})
    same = client.post(f"/r/{replacement_token}", data={"choice": "accepted"})
    alternate = client.post(f"/r/{replacement_token}", data={"choice": "declined"})
    old_alternate = client.post(f"/r/{old_token}", data={"choice": "declined"})

    session.expire_all()
    final = session.scalar(
        select(CampaignCreatorResponse).where(
            CampaignCreatorResponse.campaign_id == old.campaign_id,
            CampaignCreatorResponse.creator_id == old.creator_id,
        )
    )
    assert [value.status_code for value in (first, same, alternate, old_alternate)] == [
        200,
        200,
        200,
        200,
    ]
    assert all(
        "accepted" in value.text.casefold()
        for value in (first, same, alternate, old_alternate)
    )
    assert final is not None
    assert final.state is ResponseState.ACCEPTED
    assert final.final_delivery_id == replacement.id
    assert final.responded_at is not None
    assert (
        session.get(Delivery, replacement.id).response_state is ResponseState.ACCEPTED
    )
    assert session.get(Delivery, replacement.id).responded_at == final.responded_at
    assert session.get(Delivery, old.id).response_state is ResponseState.NO_RESPONSE
    assert session.get(Delivery, old.id).responded_at is None


def test_only_current_sent_delivery_can_create_a_final_response(
    client: TestClient, session: Session
) -> None:
    delivery, token = _sent_delivery(session)
    delivery.send_state = DeliverySendState.QUEUED
    delivery.sending_at = None
    delivery.sent_at = None
    session.flush()

    response = client.post(f"/r/{token}", data={"choice": "accepted"})

    session.expire_all()
    assert response.status_code == 200
    assert "inactive" in response.text.casefold()
    assert (
        session.get(Delivery, delivery.id).response_state is ResponseState.NO_RESPONSE
    )
    assert (
        session.scalar(select(func.count()).select_from(CampaignCreatorResponse)) == 0
    )


class _RecordingLimiter:
    def __init__(self, outcomes: list[bool | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, str]] = []

    def allow(self, identity: str, client_address: str) -> bool:
        self.calls.append((identity, client_address))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_rate_exhaustion_and_outage_return_safe_html_without_mutation(
    session: Session, workspace_access_key: str
) -> None:
    from contextlib import contextmanager

    from app.core.database import get_session
    from app.core.security import hash_workspace_key
    from app.main import create_app

    delivery, token = _sent_delivery(session)
    before = _delivery_state(delivery)

    def make_client(limiter: _RecordingLimiter) -> TestClient:
        app = create_app(
            workspace_key_hash=hash_workspace_key(workspace_access_key),
            rate_limiter=limiter,
            secret_cipher=TOKEN_CIPHER,
        )

        @contextmanager
        def scope():
            yield session

        def override_get_session():
            with scope() as value:
                yield value

        app.dependency_overrides[get_session] = override_get_session
        return TestClient(app)

    exhausted_limiter = _RecordingLimiter([True, False])
    with make_client(exhausted_limiter) as limited:
        exhausted = limited.post(f"/r/{token}", data={"choice": "accepted"})
    outage_limiter = _RecordingLimiter([RuntimeError(f"redis failed for {token}")])
    with make_client(outage_limiter) as unavailable:
        outage = unavailable.post(f"/r/{token}", data={"choice": "accepted"})

    session.expire_all()
    assert exhausted.status_code == 429
    assert outage.status_code == 503
    assert all(
        value.headers["content-type"].startswith("text/html")
        for value in (exhausted, outage)
    )
    assert token not in repr(exhausted_limiter.calls)
    assert token not in repr(outage_limiter.calls)
    assert token not in exhausted.text
    assert token not in outage.text
    assert _delivery_state(session.get(Delivery, delivery.id)) == before
    assert (
        session.scalar(select(func.count()).select_from(CampaignCreatorResponse)) == 0
    )


def test_public_response_headers_logging_and_auth_boundary(
    client: TestClient, session: Session, captured_logs
) -> None:
    delivery, token = _sent_delivery(session)

    public = client.get(f"/r/{token}?choice=accepted")
    protected = client.get("/api/v1/outreach/templates")

    log_output = "\n".join(record.getMessage() for record in captured_logs.records)
    assert public.status_code == 200
    assert protected.status_code == 401
    assert public.headers["cache-control"] == "no-store"
    assert public.headers["referrer-policy"] == "no-referrer"
    assert public.headers["x-content-type-options"] == "nosniff"
    assert public.headers["content-security-policy"] == (
        "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    assert '"route":"/r/{token}"' in log_output
    assert token not in log_output
    assert (
        session.get(Delivery, delivery.id).response_state is ResponseState.NO_RESPONSE
    )


def _create_committed_sent_delivery(
    database_engine: Engine,
    workspace_access_key: str,
    request,
) -> tuple[UUID, str]:
    task_id, creator_ids, _campaign_id, template_id, game_id = _committed_send_fixture(
        database_engine
    )
    request.addfinalizer(
        lambda: _cleanup_committed_send_fixture(
            database_engine,
            task_id=task_id,
            creator_ids=creator_ids,
            template_id=template_id,
            game_id=game_id,
        )
    )
    with _concurrent_client(database_engine, workspace_access_key) as setup_client:
        created = _create_batch(
            setup_client,
            {
                "match_task_id": str(task_id),
                "creator_ids": [str(creator_ids[0])],
                "template_id": str(template_id),
            },
            f"response-concurrency-{uuid4()}",
        )
    assert created.status_code == 201
    delivery_id = UUID(created.json()["deliveries"][0]["id"])
    with Session(database_engine) as setup, setup.begin():
        delivery = setup.get(Delivery, delivery_id)
        assert delivery is not None
        now = datetime.now(UTC)
        delivery.send_state = DeliverySendState.SENT
        delivery.sending_at = now
        delivery.sent_at = now
    return delivery_id, TOKEN_CIPHER.derive_outreach_response_token(delivery_id)


def test_real_postgresql_conflicting_posts_converge_on_one_final_response(
    database_engine: Engine, workspace_access_key: str, request
) -> None:
    delivery_id, token = _create_committed_sent_delivery(
        database_engine, workspace_access_key, request
    )
    start = Barrier(2)

    def respond(choice: str) -> tuple[int, str]:
        with _concurrent_client(database_engine, workspace_access_key) as concurrent:
            start.wait(timeout=10)
            response = concurrent.post(f"/r/{token}", data={"choice": choice})
            return response.status_code, response.text

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(respond, ("accepted", "declined")))

    assert [status for status, _body in results] == [200, 200]
    with Session(database_engine) as verify:
        delivery = verify.get(Delivery, delivery_id)
        finals = verify.scalars(select(CampaignCreatorResponse)).all()
        assert delivery is not None
        assert len(finals) == 1
        assert finals[0].state in {ResponseState.ACCEPTED, ResponseState.DECLINED}
        assert delivery.response_state is finals[0].state
        assert delivery.responded_at == finals[0].responded_at
        assert all(
            finals[0].state.value in body.casefold() for _status, body in results
        )


def test_real_postgresql_response_and_resend_race_has_one_coherent_winner(
    database_engine: Engine, workspace_access_key: str, request
) -> None:
    delivery_id, token = _create_committed_sent_delivery(
        database_engine, workspace_access_key, request
    )
    start = Barrier(2)

    def respond() -> tuple[str, int, str | None]:
        with _concurrent_client(database_engine, workspace_access_key) as concurrent:
            start.wait(timeout=10)
            response = concurrent.post(f"/r/{token}", data={"choice": "accepted"})
            return "response", response.status_code, None

    def resend() -> tuple[str, int, str | None]:
        with _concurrent_client(database_engine, workspace_access_key) as concurrent:
            start.wait(timeout=10)
            response = concurrent.post(
                f"/api/v1/outreach/deliveries/{delivery_id}/resend",
                headers={"Idempotency-Key": f"response-resend-{uuid4()}"},
            )
            error = (
                response.json().get("error", {}).get("code")
                if response.status_code != 201
                else None
            )
            return "resend", response.status_code, error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda function: function(), (respond, resend)))

    by_kind = {kind: (status, error) for kind, status, error in results}
    assert by_kind["response"][0] == 200
    assert by_kind["resend"] in {
        (201, None),
        (409, "delivery_not_resendable"),
    }
    with Session(database_engine) as verify:
        old = verify.get(Delivery, delivery_id)
        finals = verify.scalars(select(CampaignCreatorResponse)).all()
        assert old is not None
        if by_kind["resend"][0] == 409:
            assert len(finals) == 1
            assert finals[0].state is ResponseState.ACCEPTED
            assert old.response_state is ResponseState.ACCEPTED
            assert old.superseded_at is None
            assert verify.scalar(select(func.count()).select_from(Delivery)) == 1
        else:
            assert finals == []
            assert old.response_state is ResponseState.NO_RESPONSE
            assert old.superseded_at is not None
            assert verify.scalar(select(func.count()).select_from(Delivery)) == 2
