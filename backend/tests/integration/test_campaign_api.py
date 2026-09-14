from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from uuid import UUID, uuid4

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.db.models.match import MatchResultItem
from app.db.models.outreach import Delivery, DeliverySendState, SendBatch, Template
from tests.integration.test_send_batch_api import (
    _configure,
    _create_batch,
    _create_template,
    _payload,
    _published_match,
)


TOKEN_CIPHER = SecretCipher(bytes(range(32)))


def _mark_sent(delivery: Delivery, when: datetime) -> None:
    delivery.send_state = DeliverySendState.SENT
    delivery.sending_at = when
    delivery.sent_at = when + timedelta(seconds=1)


def _mark_failed(delivery: Delivery, when: datetime) -> None:
    delivery.send_state = DeliverySendState.FAILED
    delivery.sending_at = when
    delivery.failed_at = when + timedelta(seconds=1)
    delivery.smtp_error_code = "smtp_rejected"
    delivery.smtp_error_message = "SMTP rejected the request."
    delivery.smtp_retryable = False


def _all_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def test_campaign_list_requires_workspace_authentication(client) -> None:
    response = client.get("/api/v1/outreach/campaigns")

    assert response.status_code == 401


def test_campaign_list_uses_a_bounded_number_of_bulk_queries(
    auth_client, session: Session
) -> None:
    for _ in range(6):
        _published_match(session, [])
    statements: list[str] = []

    def record_selects(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", record_selects)
    try:
        response = auth_client.get("/api/v1/outreach/campaigns")
    finally:
        event.remove(connection, "before_cursor_execute", record_selects)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 6
    assert len(statements) == 4


def test_campaign_list_is_newest_first_cursor_stable_and_reflects_public_response(
    auth_client, session: Session
) -> None:
    task_a, creators_a, campaign_a = _published_match(
        session, [("Accepted Creator", "accepted@example.com")]
    )
    task_b, _creators_b, campaign_b = _published_match(session, [])
    task_c, _creators_c, campaign_c = _published_match(session, [])
    for offset, campaign in enumerate((campaign_a, campaign_b, campaign_c)):
        campaign.created_at = datetime(2026, 9, 2 + offset, 12, tzinfo=UTC)
        campaign.updated_at = campaign.created_at
    _configure(auth_client)
    created = _create_batch(
        auth_client,
        _payload(task_a, creators_a),
        key=f"campaign-list-{uuid4().hex}",
    )
    delivery = session.get(Delivery, UUID(created.json()["deliveries"][0]["id"]))
    assert delivery is not None
    _mark_sent(delivery, delivery.created_at + timedelta(minutes=1))
    session.flush()
    raw_token = TOKEN_CIPHER.derive_outreach_response_token(delivery.id)
    confirmed = auth_client.post(f"/r/{raw_token}", data={"choice": "accepted"})
    assert confirmed.status_code == 200

    cursor = None
    items: list[dict[str, object]] = []
    cursors: list[str] = []
    while True:
        params = {"limit": 1, **({"cursor": cursor} if cursor else {})}
        page = auth_client.get("/api/v1/outreach/campaigns", params=params)
        assert page.status_code == 200, page.text
        body = page.json()
        assert set(body) == {"items", "cursor", "has_more"}
        items.extend(body["items"])
        cursor = body["cursor"]
        if cursor is None:
            break
        cursors.append(cursor)

    assert [item["id"] for item in items] == [
        str(campaign_c.id),
        str(campaign_b.id),
        str(campaign_a.id),
    ]
    assert len({item["id"] for item in items}) == 3
    assert items[0]["state"] == "not_started"
    accepted = items[-1]
    assert accepted["metrics"] == {
        "sent_creators": 1,
        "accepted": 1,
        "declined": 0,
        "no_response": 0,
        "failed": 0,
        "response_rate": 1.0,
    }
    assert accepted["send_batch_count"] == 1
    assert set(accepted["game"]) == {
        "id",
        "name",
        "steam_app_id",
        "steam_url",
        "cover_url",
    }
    assert raw_token not in _all_text(items)

    tampered = cursors[0][:-1] + ("A" if cursors[0][-1] != "A" else "B")
    invalid = auth_client.get("/api/v1/outreach/campaigns", params={"cursor": tampered})
    match_cursor = auth_client.get("/api/v1/matches", params={"limit": 1}).json()[
        "cursor"
    ]
    wrong_scope = auth_client.get(
        "/api/v1/outreach/campaigns", params={"cursor": match_cursor}
    )
    assert invalid.status_code == wrong_scope.status_code == 400
    assert invalid.json()["error"]["code"] == "outreach_campaign_cursor_invalid"
    assert wrong_scope.json()["error"]["code"] == "outreach_campaign_cursor_invalid"


def test_campaign_and_delivery_history_is_complete_frozen_and_safe(
    auth_client, session: Session, captured_logs
) -> None:
    task, creators, campaign = _published_match(
        session,
        [
            ("Resent Creator", "resent@example.com"),
            ("Ready Creator", "ready@example.com"),
            ("Failed Creator", "failed@example.com"),
        ],
    )
    for index, creator in enumerate(creators):
        creator.current_facts = {
            "title": f"Current {creator.sort_name}",
            "avatar_url": f"https://img.example/{index}.png",
        }
    template = _configure(auth_client)
    created = _create_batch(
        auth_client,
        _payload(task, creators, template_id=template["id"]),
        key=f"campaign-detail-{uuid4().hex}",
    )
    original_batch_id = UUID(created.json()["id"])
    delivery_ids = [UUID(row["id"]) for row in created.json()["deliveries"]]
    original = [session.get(Delivery, delivery_id) for delivery_id in delivery_ids]
    assert all(delivery is not None for delivery in original)
    _mark_sent(original[0], original[0].created_at + timedelta(minutes=1))
    _mark_sent(original[1], original[1].created_at + timedelta(minutes=2))
    _mark_failed(original[2], original[2].created_at + timedelta(minutes=3))
    frozen = {
        "rendered_subject": original[0].rendered_subject,
        "rendered_markdown": original[0].rendered_markdown,
        "rendered_html": original[0].rendered_html,
        "template_name": original[0].template_name,
        "template_version": original[0].template_version,
    }
    session.flush()

    changed = auth_client.patch(
        f"/api/v1/outreach/templates/{template['id']}",
        json={
            "name": "Edited invitation",
            "subject_template": "Edited subject",
            "body_markdown": "Edited body",
        },
    )
    assert changed.status_code == 200
    replacement = auth_client.post(
        f"/api/v1/outreach/deliveries/{original[0].id}/resend",
        headers={"Idempotency-Key": f"campaign-resend-{uuid4().hex}"},
    )
    assert replacement.status_code == 201, replacement.text
    replacement_batch_id = UUID(replacement.json()["id"])
    replacement_delivery_id = UUID(replacement.json()["deliveries"][0]["id"])
    replacement_delivery = session.get(Delivery, replacement_delivery_id)
    assert replacement_delivery is not None
    replacement_batch = session.get(SendBatch, replacement_batch_id)
    original_batch = session.get(SendBatch, original_batch_id)
    assert replacement_batch is not None and original_batch is not None
    replacement_batch.requested_at = original_batch.requested_at + timedelta(minutes=1)
    session.flush()

    other = _create_template(auth_client, name="New default invitation")
    assert (
        auth_client.post(
            f"/api/v1/outreach/templates/{other['id']}/default"
        ).status_code
        == 200
    )
    assert (
        auth_client.delete(f"/api/v1/outreach/templates/{template['id']}").status_code
        == 204
    )
    assert session.get(Template, UUID(template["id"])) is None

    raw_tokens = {
        TOKEN_CIPHER.derive_outreach_response_token(delivery_id)
        for delivery_id in [*delivery_ids, replacement_delivery_id]
    }
    response = auth_client.get(f"/api/v1/outreach/campaigns/{campaign.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "queued"
    assert body["metrics"] == {
        "sent_creators": 2,
        "accepted": 0,
        "declined": 0,
        "no_response": 2,
        "failed": 1,
        "response_rate": 0.0,
    }
    assert [UUID(batch["id"]) for batch in body["send_batches"]] == [
        replacement_batch_id,
        original_batch_id,
    ]
    nested = [
        delivery for batch in body["send_batches"] for delivery in batch["deliveries"]
    ]
    assert len(nested) == len({delivery["id"] for delivery in nested}) == 4
    assert {UUID(delivery["id"]) for delivery in nested} == {
        *delivery_ids,
        replacement_delivery_id,
    }
    by_id = {UUID(delivery["id"]): delivery for delivery in nested}
    assert {key: by_id[original[0].id][key] for key in frozen} == frozen
    assert {key: by_id[replacement_delivery_id][key] for key in frozen} == frozen
    assert by_id[original[0].id]["is_current"] is False
    assert by_id[original[0].id]["can_resend"] is False
    assert by_id[replacement_delivery_id]["is_current"] is True
    assert by_id[replacement_delivery_id]["can_resend"] is False
    assert by_id[original[1].id]["can_resend"] is True
    assert by_id[original[2].id]["can_resend"] is True
    assert by_id[original[2].id]["smtp_error"] == {
        "code": "smtp_rejected",
        "message": "SMTP rejected the request.",
        "retryable": False,
    }
    assert by_id[original[1].id]["smtp_error"] is None
    assert set(by_id[original[1].id]["creator"]) == {
        "id",
        "name",
        "platform",
        "platform_account_id",
        "youtube_channel_id",
        "canonical_url",
        "avatar_url",
    }
    assert body["send_batches"][0]["template_id"] is None
    assert body["send_batches"][0]["template_name"] == frozen["template_name"]
    assert body["send_batches"][0]["template_version"] == frozen["template_version"]

    standalone = auth_client.get(f"/api/v1/outreach/deliveries/{original[1].id}")
    assert standalone.status_code == 200
    assert standalone.json() == by_id[original[1].id]
    missing = auth_client.get(f"/api/v1/outreach/deliveries/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "delivery_not_found"

    accepted_token = TOKEN_CIPHER.derive_outreach_response_token(original[1].id)
    accepted = auth_client.post(f"/r/{accepted_token}", data={"choice": "accepted"})
    assert accepted.status_code == 200
    after_response = auth_client.get(
        f"/api/v1/outreach/deliveries/{original[1].id}"
    ).json()
    assert after_response["response_state"] == "accepted"
    assert after_response["responded_at"] is not None
    assert after_response["can_resend"] is False

    unsafe_error = "SMTP password private-smtp-secret must never escape"
    original[2].smtp_error_message = unsafe_error
    session.flush()
    unsafe_projection = auth_client.get(f"/api/v1/outreach/deliveries/{original[2].id}")
    assert unsafe_projection.status_code == 200
    assert unsafe_projection.json()["smtp_error"] is None
    assert unsafe_error not in unsafe_projection.text

    forbidden_names = {
        "response_token",
        "response_token_digest",
        "ciphertext",
        "nonce",
        "password",
        "backend_order",
        "rank",
        "total_score",
        "dimension_scores",
    }
    payload = _all_text(body).casefold()
    schema = auth_client.app.openapi()
    response_components = _all_text(
        {
            name: schema["components"]["schemas"][name]
            for name in (
                "OutreachCampaignDetail",
                "OutreachCampaignGame",
                "OutreachCampaignMetrics",
                "OutreachCampaignPage",
                "OutreachCampaignSummary",
                "OutreachCreatorIdentity",
                "OutreachDeliveryDetail",
                "OutreachSendBatchDetail",
                "OutreachSMTPError",
            )
        }
    ).casefold()
    log_output = "\n".join(record.getMessage() for record in captured_logs.records)
    assert all(name not in payload for name in forbidden_names)
    assert all(name not in response_components for name in forbidden_names)
    assert all(token not in payload for token in raw_tokens)
    assert all(token not in response_components for token in raw_tokens)
    assert all(token not in log_output for token in raw_tokens)
    assert session.scalar(select(func.count()).select_from(MatchResultItem)) == 3


def test_campaign_and_delivery_not_found_are_stable(auth_client) -> None:
    campaign = auth_client.get(f"/api/v1/outreach/campaigns/{uuid4()}")
    delivery = auth_client.get(f"/api/v1/outreach/deliveries/{uuid4()}")

    assert campaign.status_code == delivery.status_code == 404
    assert campaign.json()["error"]["code"] == "outreach_campaign_not_found"
    assert delivery.json()["error"]["code"] == "delivery_not_found"
