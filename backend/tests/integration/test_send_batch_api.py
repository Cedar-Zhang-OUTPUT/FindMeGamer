from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from threading import Barrier, Lock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.core.database import get_session
from app.core.security import hash_workspace_key
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.match import (
    MatchCandidateInput,
    MatchPairwiseRecord,
    MatchResultGroup,
    MatchResultItem,
    MatchScreeningRecord,
    MatchStage,
    MatchStatus,
    MatchTask,
    PairwiseState,
)
from app.db.models.outreach import (
    CampaignCreatorResponse,
    Delivery,
    DeliverySendState,
    OutreachCampaign,
    ResponseState,
    SendBatch,
    Template,
)
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.db.models.settings import ServiceSecret, SharedSettings
from app.main import create_app
from app.repositories.settings import SHARED_SETTINGS_ID


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
SEND_BATCH_PATH = "/api/v1/outreach/send-batches"
SMTP_PAYLOAD = {
    "host": "smtp.example.com",
    "port": 465,
    "encryption": "tls",
    "username": "sender@example.com",
    "password": "smtp-secret",
    "from_name": "Find Me Gamer Team",
    "reply_to": "reply@example.com",
    "emails_per_minute": 10,
}


def _claim(value: str) -> dict[str, object]:
    return {
        "status": "available",
        "value": value,
        "evidence": [
            {
                "kind": "source_fact",
                "source_type": "steam_field",
                "reference": "steam:short_description",
            }
        ],
        "confidence": "high",
    }


def _game_brief() -> dict[str, object]:
    unavailable = {"status": "unavailable", "reason": "Not available."}
    return {
        "positioning_premise": _claim("A tactical cooperative adventure."),
        "core_gameplay_loop": unavailable,
        "genres": unavailable,
        "themes": unavailable,
        "tone": unavailable,
        "visual_identity": unavailable,
        "target_audience": unavailable,
        "key_selling_points": unavailable,
        "content_hooks": unavailable,
        "comparable_games": unavailable,
        "suitable_creator_types": unavailable,
        "promotion_risks": unavailable,
    }


def _creator_brief() -> dict[str, object]:
    unavailable = {"status": "unavailable", "reason": "Not available."}
    return {
        "positioning": unavailable,
        "content_focus": unavailable,
        "formats": unavailable,
        "style_and_pacing": unavailable,
        "audience": {**unavailable, "provenance": "ai_inference"},
        "performance_context": unavailable,
        "promotion_fit": unavailable,
        "brand_safety": unavailable,
        "suitable_game_types": unavailable,
        "collaboration_risks": unavailable,
    }


def _create_creator(session: Session, name: str, email: str | None) -> CreatorProfile:
    channel = f"UC{uuid4().hex[:22]}"
    creator = CreatorProfile(
        youtube_channel_id=channel,
        canonical_url=f"https://www.youtube.com/channel/{channel}",
        sort_name=name,
        current_facts={"title": f"{name} Channel"},
        analysis={},
        brief=_creator_brief(),
        source_status={"youtube": "current", "freshness": "current"},
        last_analyzed_at=NOW,
        next_analysis_at=NOW + timedelta(days=14),
    )
    session.add(creator)
    session.flush()
    if email is not None:
        session.add(
            CreatorContact(
                creator_id=creator.id,
                email=email,
                source_type="manual",
                is_manual=True,
                validation_state="verified",
                priority=0,
                is_active=True,
            )
        )
        session.flush()
    return creator


def _published_match(
    session: Session, creator_emails: list[tuple[str, str | None]]
) -> tuple[MatchTask, list[CreatorProfile], OutreachCampaign]:
    game = GameProfile(
        steam_app_id=str(uuid4().int % 10**16),
        canonical_url="https://store.steampowered.com/app/12345",
        sort_name="Tactics Together",
        current_facts={"name": "Tactics Together"},
        analysis={},
        brief=_game_brief(),
        source_status={"steam": "current"},
        last_analyzed_at=NOW,
        next_analysis_at=NOW + timedelta(days=30),
    )
    session.add(game)
    session.flush()
    creators = [_create_creator(session, name, email) for name, email in creator_emails]
    task = MatchTask(
        game_id=game.id,
        locked_game_brief=_game_brief(),
        shuffle_seed=42,
        recommended_match_threshold=Decimal("0.7000"),
        status=MatchStatus.SUCCEEDED,
        stage=MatchStage.RANKING,
        completed_units=len(creators) + 2,
        total_units=len(creators) + 2,
        result_count=len(creators),
        retryable=False,
        input_expires_at=NOW + timedelta(days=30),
        started_at=NOW,
        completed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(task)
    session.flush()
    for order, creator in enumerate(creators):
        session.add(
            MatchScreeningRecord(
                match_task_id=task.id,
                creator_id=creator.id,
                screening_order=order,
                locked_creator_brief=_creator_brief(),
                selected=True,
                expires_at=task.input_expires_at,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            MatchCandidateInput(
                match_task_id=task.id,
                creator_id=creator.id,
                locked_creator_profile={"id": str(creator.id)},
                input_model_metadata={},
                input_prompt_metadata={},
                expires_at=task.input_expires_at,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        pairwise = {
            "english_language_check": True,
            "creator_id": str(creator.id),
            "content_fit": {"analysis": "Fit.", "evidence": ["Evidence."]},
            "audience_fit": {"analysis": "Fit.", "evidence": ["Evidence."]},
            "performance_fit": {"analysis": "Fit.", "evidence": ["Evidence."]},
            "promotion_fit": {"analysis": "Fit.", "evidence": ["Evidence."]},
            "brand_safety": {"analysis": "Fit.", "evidence": ["Evidence."]},
            "strengths": ["Strong fit."],
            "risks": ["Manageable."],
            "evidence": ["Evidence."],
            "match_reasons": [f"{creator.sort_name} fits the launch."],
        }
        session.add(
            MatchPairwiseRecord(
                match_task_id=task.id,
                creator_id=creator.id,
                state=PairwiseState.SUCCEEDED,
                attempt_count=1,
                match_brief=pairwise,
                retryable=False,
                started_at=NOW,
                completed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            MatchResultItem(
                match_task_id=task.id,
                creator_id=creator.id,
                backend_order=order,
                match_brief=pairwise,
                total_score=Decimal("0.8000"),
                dimension_scores={"content_fit": 0.8},
                dimension_outcomes={
                    name: "Good fit."
                    for name in (
                        "content_fit",
                        "audience_fit",
                        "performance_fit",
                        "promotion_fit",
                        "brand_safety",
                    )
                },
                match_reasons=[f"{creator.sort_name} fits the launch."],
                result_group=MatchResultGroup.RECOMMENDED,
                qualitative_label="Good Match",
            )
        )
    campaign = OutreachCampaign(match_task_id=task.id)
    session.add(campaign)
    session.flush()
    return task, creators, campaign


def _create_template(auth_client, **overrides: object) -> dict[str, object]:
    response = auth_client.post(
        "/api/v1/outreach/templates",
        json={
            "name": "Launch invitation",
            "subject_template": "{{creator_name}} × {{game_name}}",
            "body_markdown": (
                "Hello {{channel_name}}. {{game_summary}} "
                "Why: {{match_reason}} From {{sender_name}}. {{steam_url}}"
            ),
            "accepted_label": "Interested",
            "declined_label": "Pass",
            **overrides,
        },
    )
    assert response.status_code == 201
    return response.json()


def _configure(auth_client) -> dict[str, object]:
    assert (
        auth_client.put("/api/v1/outreach/smtp", json=SMTP_PAYLOAD).status_code == 200
    )
    return _create_template(auth_client)


def _payload(task: MatchTask, creators: list[CreatorProfile], **extra: object) -> dict:
    return {
        "match_task_id": str(task.id),
        "creator_ids": [str(creator.id) for creator in creators],
        **extra,
    }


def _create_batch(auth_client, payload: dict, key: str = "send-batch-0001"):
    return auth_client.post(
        SEND_BATCH_PATH, json=payload, headers={"Idempotency-Key": key}
    )


def test_preview_applies_send_only_overrides_per_creator_without_side_effects(
    auth_client, session: Session, smtp_gateway, smtp_rate_limiter
) -> None:
    task, creators, _campaign = _published_match(
        session,
        [("Alpha Creator", "alpha@example.com"), ("Beta Creator", "beta@example.com")],
    )
    template = _configure(auth_client)
    counts_before = {
        model: session.scalar(select(func.count()).select_from(model))
        for model in (SendBatch, Delivery, IdempotencyRecord)
    }

    response = auth_client.post(
        f"{SEND_BATCH_PATH}/preview",
        json=_payload(
            task,
            creators,
            template_id=template["id"],
            subject_override="Preview for {{creator_name}}",
            body_markdown_override="{{channel_name}} / {{match_reason}}",
        ),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "match_task_id",
        "template_id",
        "template_name",
        "template_version",
        "items",
    }
    assert [item["creator_id"] for item in body["items"]] == [
        str(creator.id) for creator in creators
    ]
    assert [item["subject"] for item in body["items"]] == [
        "Preview for Alpha Creator",
        "Preview for Beta Creator",
    ]
    assert "Alpha Creator Channel" in body["items"][0]["markdown"]
    assert "Beta Creator fits the launch." in body["items"][1]["markdown"]
    assert body["items"][0]["html"].index("Interested") < body["items"][0][
        "html"
    ].index("Pass")
    assert "example.invalid" in body["items"][0]["html"]
    assert (
        session.get(Template, UUID(template["id"])).subject_template
        == "{{creator_name}} × {{game_name}}"
    )
    assert counts_before == {
        model: session.scalar(select(func.count()).select_from(model))
        for model in counts_before
    }
    assert smtp_gateway.sends == []
    assert smtp_rate_limiter.calls == []


def test_preview_uses_current_game_identity_when_locked_summary_is_unavailable(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    unavailable = {"status": "unavailable", "reason": "Not available."}
    task.locked_game_brief = {name: unavailable for name in task.locked_game_brief}
    session.flush()
    _configure(auth_client)

    response = auth_client.post(
        f"{SEND_BATCH_PATH}/preview",
        json=_payload(
            task,
            creators,
            subject_override="{{game_name}}",
            body_markdown_override="{{game_summary}}",
        ),
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["subject"] == "Tactics Together"
    assert response.json()["items"][0]["markdown"] == "Tactics Together"


def test_default_and_explicit_template_selection_are_independent(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    default = _configure(auth_client)
    explicit = _create_template(
        auth_client,
        name="Explicit invitation",
        subject_template="Explicit {{creator_name}}",
    )

    selected_default = auth_client.post(
        f"{SEND_BATCH_PATH}/preview", json=_payload(task, creators)
    )
    selected_explicit = auth_client.post(
        f"{SEND_BATCH_PATH}/preview",
        json=_payload(task, creators, template_id=explicit["id"]),
    )

    assert selected_default.status_code == selected_explicit.status_code == 200
    assert selected_default.json()["template_id"] == default["id"]
    assert selected_default.json()["items"][0]["subject"] == "Alpha × Tactics Together"
    assert selected_explicit.json()["template_id"] == explicit["id"]
    assert selected_explicit.json()["items"][0]["subject"] == "Explicit Alpha"


def test_preview_and_create_require_complete_smtp_configuration(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    _create_template(auth_client)
    idempotency_before = session.scalar(
        select(func.count()).select_from(IdempotencyRecord)
    )

    preview = auth_client.post(
        f"{SEND_BATCH_PATH}/preview", json=_payload(task, creators)
    )
    created = _create_batch(auth_client, _payload(task, creators))

    assert preview.status_code == created.status_code == 409
    assert preview.json()["error"]["code"] == "smtp_not_configured"
    assert created.json()["error"]["code"] == "smtp_not_configured"
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 0
    assert (
        session.scalar(select(func.count()).select_from(IdempotencyRecord))
        == idempotency_before
    )


def test_match_campaign_membership_and_render_validation_are_atomic(
    auth_client, session: Session
) -> None:
    task, creators, campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    template = _configure(auth_client)
    outsider = _create_creator(session, "Outsider", "outside@example.com")
    idempotency_before = session.scalar(
        select(func.count()).select_from(IdempotencyRecord)
    )

    not_a_member = _create_batch(
        auth_client,
        _payload(task, [outsider]),
        "invalid-membership",
    )
    selected_template = session.get(Template, UUID(str(template["id"])))
    assert selected_template is not None
    selected_template.body_markdown = "{{unknown_value}}"
    session.flush()
    invalid_render = _create_batch(
        auth_client,
        _payload(task, creators),
        "invalid-render",
    )
    selected_template.body_markdown = "Body"
    session.delete(campaign)
    session.flush()
    missing_campaign = _create_batch(
        auth_client,
        _payload(task, creators),
        "invalid-campaign",
    )

    assert not_a_member.status_code == 422
    assert not_a_member.json()["error"]["code"] == "creator_not_in_match"
    assert invalid_render.status_code == 422
    assert invalid_render.json()["error"]["code"] == "template_invalid"
    assert missing_campaign.status_code == 409
    assert missing_campaign.json()["error"]["code"] == "outreach_campaign_invalid"
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Delivery)) == 0
    assert (
        session.scalar(select(func.count()).select_from(IdempotencyRecord))
        == idempotency_before
    )


def test_corrupt_template_snapshot_is_a_safe_atomic_validation_error(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    template = _configure(auth_client)
    selected = session.get(Template, UUID(str(template["id"])))
    assert selected is not None
    selected.accepted_label = "   "
    session.flush()
    idempotency_before = session.scalar(
        select(func.count()).select_from(IdempotencyRecord)
    )

    response = _create_batch(
        auth_client, _payload(task, creators), "corrupt-template-snapshot"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "template_invalid"
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Delivery)) == 0
    assert (
        session.scalar(select(func.count()).select_from(IdempotencyRecord))
        == idempotency_before
    )


def test_contact_selection_matches_manual_and_stale_profile_policy(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(session, [("Alpha", None)])
    creator = creators[0]
    session.add(
        CreatorContact(
            creator_id=creator.id,
            email="discovered@example.com",
            source_type="website",
            is_manual=False,
            validation_state="verified",
            priority=99,
            is_active=True,
        )
    )
    creator.source_status = {"youtube": "stale", "freshness": "stale"}
    session.flush()
    _configure(auth_client)

    stale_without_manual = auth_client.post(
        f"{SEND_BATCH_PATH}/preview", json=_payload(task, creators)
    )
    session.add(
        CreatorContact(
            creator_id=creator.id,
            email="manual@example.com",
            source_type="manual",
            is_manual=True,
            validation_state="verified",
            priority=0,
            is_active=True,
        )
    )
    session.flush()
    with_manual = auth_client.post(
        f"{SEND_BATCH_PATH}/preview", json=_payload(task, creators)
    )
    stale_discovered_selection = auth_client.post(
        f"{SEND_BATCH_PATH}/preview",
        json=_payload(
            task,
            creators,
            recipient_selections=[
                {"creator_id": str(creator.id), "email": "discovered@example.com"}
            ],
        ),
    )

    assert stale_without_manual.status_code == 422
    assert stale_without_manual.json()["error"]["code"] == "recipient_email_unavailable"
    assert with_manual.status_code == 200
    assert with_manual.json()["items"][0]["recipient_email"] == "manual@example.com"
    assert stale_discovered_selection.status_code == 422
    assert (
        stale_discovered_selection.json()["error"]["code"]
        == "recipient_email_selection_invalid"
    )


def test_multiple_emails_require_one_explicit_valid_recipient_selection(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(session, [("Alpha", None)])
    creator = creators[0]
    for priority, email in enumerate(("business@example.com", "press@example.com"), 1):
        session.add(
            CreatorContact(
                creator_id=creator.id,
                email=email,
                source_type="public_web_research",
                purpose="Business" if priority == 1 else "Press",
                validation_state="unverified",
                priority=priority,
                is_active=True,
            )
        )
    session.flush()
    _configure(auth_client)

    missing = auth_client.post(
        f"{SEND_BATCH_PATH}/preview", json=_payload(task, creators)
    )
    invalid = auth_client.post(
        f"{SEND_BATCH_PATH}/preview",
        json=_payload(
            task,
            creators,
            recipient_selections=[
                {"creator_id": str(creator.id), "email": "other@example.com"}
            ],
        ),
    )
    selected_payload = _payload(
        task,
        creators,
        recipient_selections=[
            {"creator_id": str(creator.id), "email": "press@example.com"}
        ],
    )
    selected = auth_client.post(
        f"{SEND_BATCH_PATH}/preview",
        json=selected_payload,
    )
    created = _create_batch(auth_client, selected_payload, "selected-recipient")

    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "recipient_email_selection_required"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "recipient_email_selection_invalid"
    assert selected.status_code == 200
    assert len(selected.json()["items"]) == 1
    assert selected.json()["items"][0]["recipient_email"] == "press@example.com"
    assert created.status_code == 201
    assert [item["recipient_email"] for item in created.json()["deliveries"]] == [
        "press@example.com"
    ]
    deliveries = session.scalars(
        select(Delivery).where(Delivery.creator_id == creator.id)
    ).all()
    assert len(deliveries) == 1
    assert deliveries[0].recipient_email == "press@example.com"


def test_recipient_selections_reject_duplicates_and_creators_outside_request(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(
        session,
        [("Alpha", "alpha@example.com"), ("Beta", "beta@example.com")],
    )
    _configure(auth_client)
    duplicate = [
        {"creator_id": str(creators[0].id), "email": "alpha@example.com"},
        {"creator_id": str(creators[0].id), "email": "alpha@example.com"},
    ]
    extra = [
        {"creator_id": str(creators[1].id), "email": "beta@example.com"},
    ]

    duplicate_response = auth_client.post(
        f"{SEND_BATCH_PATH}/preview",
        json=_payload(task, [creators[0]], recipient_selections=duplicate),
    )
    extra_response = auth_client.post(
        f"{SEND_BATCH_PATH}/preview",
        json=_payload(task, [creators[0]], recipient_selections=extra),
    )

    assert duplicate_response.status_code == 422
    assert duplicate_response.json()["error"]["code"] == "request_invalid"
    assert extra_response.status_code == 422
    assert extra_response.json()["error"]["code"] == "recipient_email_selection_invalid"


def test_create_persists_atomic_secret_free_batch_and_replays_byte_equivalently(
    auth_client, session: Session, smtp_gateway, smtp_rate_limiter
) -> None:
    task, creators, campaign = _published_match(
        session,
        [("Alpha Creator", "alpha@example.com"), ("Beta Creator", "beta@example.com")],
    )
    template = _configure(auth_client)
    payload = _payload(task, creators, template_id=template["id"])

    response = _create_batch(auth_client, payload)
    replay = _create_batch(auth_client, payload)

    assert response.status_code == replay.status_code == 201, response.text
    assert response.content == replay.content
    body = response.json()
    assert set(body) == {
        "id",
        "campaign_id",
        "match_task_id",
        "template_id",
        "state",
        "requested_creator_ids",
        "requested_at",
        "deliveries",
    }
    assert body["campaign_id"] == str(campaign.id)
    assert body["state"] == "queued"
    assert body["requested_creator_ids"] == [str(value.id) for value in creators]
    assert [item["creator_id"] for item in body["deliveries"]] == [
        str(value.id) for value in creators
    ]
    assert all(
        set(item)
        == {
            "id",
            "creator_id",
            "recipient_email",
            "send_state",
            "response_state",
            "resends_delivery_id",
        }
        for item in body["deliveries"]
    )
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 1
    deliveries = session.scalars(select(Delivery).order_by(Delivery.creator_id)).all()
    assert len(deliveries) == 2
    assert len({value.response_token_digest for value in deliveries}) == 2
    assert all(
        value.rendered_html.count("__FIND_ME_GAMER_") == 2 for value in deliveries
    )
    assert all("example.invalid" not in value.rendered_html for value in deliveries)
    assert SMTP_PAYLOAD["password"] not in response.text
    assert all(value.response_token_digest not in response.text for value in deliveries)
    record = session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.key == "send-batch-0001")
    )
    assert record is not None
    assert "digest" not in str(record.response_body).casefold()
    assert "token" not in str(record.response_body).casefold()
    assert smtp_gateway.sends == []
    assert smtp_rate_limiter.calls == []


def test_invalid_recipient_rejects_entire_batch(auth_client, session: Session) -> None:
    task, creators, _campaign = _published_match(
        session, [("Ready", "ready@example.com"), ("Missing", None)]
    )
    _configure(auth_client)
    idempotency_before = session.scalar(
        select(func.count()).select_from(IdempotencyRecord)
    )

    response = _create_batch(auth_client, _payload(task, creators))

    assert response.status_code == 422
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Delivery)) == 0
    assert (
        session.scalar(select(func.count()).select_from(IdempotencyRecord))
        == idempotency_before
    )


def test_duplicate_send_requires_resend_endpoint(auth_client, session: Session) -> None:
    task, creators, _campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    _configure(auth_client)
    first = _create_batch(auth_client, _payload(task, creators), "send-batch-first")

    response = _create_batch(auth_client, _payload(task, creators), "send-batch-second")

    assert first.status_code == 201
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "explicit_resend_required"
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 1
    assert session.scalar(select(func.count()).select_from(Delivery)) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"creator_ids": []},
        {"subject_override": None},
        {"body_markdown_override": "   "},
        {"unexpected": True},
    ],
)
def test_closed_create_and_preview_requests_reject_invalid_values(
    auth_client, session: Session, payload: dict[str, object]
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    _configure(auth_client)
    request = _payload(task, creators)
    request.update(payload)

    for path, headers in (
        (f"{SEND_BATCH_PATH}/preview", {}),
        (SEND_BATCH_PATH, {"Idempotency-Key": "send-closed-0001"}),
    ):
        response = auth_client.post(path, json=request, headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "request_invalid"


def test_write_headers_and_cross_endpoint_idempotency_conflict(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    _configure(auth_client)
    payload = _payload(task, creators)

    missing = auth_client.post(SEND_BATCH_PATH, json=payload)
    invalid = _create_batch(auth_client, payload, "short")
    created = _create_batch(auth_client, payload, "shared-global-key")
    conflict = auth_client.post(
        f"/api/v1/outreach/deliveries/{created.json()['deliveries'][0]['id']}/resend",
        headers={"Idempotency-Key": "shared-global-key"},
    )

    assert missing.status_code == 422
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "idempotency_key_invalid"
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_conflict"


@pytest.mark.parametrize(
    ("send_state", "response_state", "allowed"),
    [
        (DeliverySendState.QUEUED, ResponseState.NO_RESPONSE, False),
        (DeliverySendState.SENDING, ResponseState.NO_RESPONSE, False),
        (DeliverySendState.SENT, ResponseState.NO_RESPONSE, True),
        (DeliverySendState.FAILED, ResponseState.NO_RESPONSE, True),
        (DeliverySendState.SENT, ResponseState.ACCEPTED, False),
        (DeliverySendState.SENT, ResponseState.DECLINED, False),
    ],
)
def test_resend_state_rules_and_snapshot_clone(
    auth_client,
    session: Session,
    send_state: DeliverySendState,
    response_state: ResponseState,
    allowed: bool,
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    _configure(auth_client)
    created = _create_batch(
        auth_client, _payload(task, creators), f"seed-{send_state}-{response_state}"
    )
    delivery_id = UUID(created.json()["deliveries"][0]["id"])
    delivery = session.get(Delivery, delivery_id)
    assert delivery is not None
    event_at = delivery.created_at
    delivery.send_state = send_state
    delivery.response_state = response_state
    if send_state in {
        DeliverySendState.SENDING,
        DeliverySendState.SENT,
        DeliverySendState.FAILED,
    }:
        delivery.sending_at = event_at
    if send_state is DeliverySendState.SENT:
        delivery.sent_at = event_at
    if send_state is DeliverySendState.FAILED:
        delivery.failed_at = event_at
        delivery.smtp_error_code = "smtp_failed"
        delivery.smtp_error_message = "Safe failure"
    if response_state is not ResponseState.NO_RESPONSE:
        delivery.responded_at = event_at
    session.flush()
    snapshot = {
        name: getattr(delivery, name)
        for name in (
            "campaign_id",
            "creator_id",
            "recipient_email",
            "rendered_subject",
            "rendered_markdown",
            "rendered_html",
            "template_name",
            "template_version",
            "accepted_label",
            "declined_label",
            "sender_name",
            "sender_address",
            "reply_to",
        )
    }

    response = auth_client.post(
        f"/api/v1/outreach/deliveries/{delivery_id}/resend",
        headers={"Idempotency-Key": f"resend-{send_state}-{response_state}"},
    )

    assert response.status_code == (201 if allowed else 409)
    session.expire_all()
    old = session.get(Delivery, delivery_id)
    assert old is not None
    if allowed:
        replacement_id = UUID(response.json()["deliveries"][0]["id"])
        replacement = session.get(Delivery, replacement_id)
        assert old.superseded_at is not None
        assert replacement is not None
        assert replacement.resends_delivery_id == old.id
        assert replacement.response_token_digest != old.response_token_digest
        assert {name: getattr(replacement, name) for name in snapshot} == snapshot
        assert replacement.send_state is DeliverySendState.QUEUED
        assert replacement.response_state is ResponseState.NO_RESPONSE
    else:
        assert old.superseded_at is None
        assert session.scalar(select(func.count()).select_from(Delivery)) == 1


def test_resend_replays_same_key_and_old_delivery_stays_read_only(
    auth_client, session: Session
) -> None:
    task, creators, _campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    _configure(auth_client)
    created = _create_batch(auth_client, _payload(task, creators), "resend-seed-0001")
    delivery = session.get(Delivery, UUID(created.json()["deliveries"][0]["id"]))
    assert delivery is not None
    delivery.send_state = DeliverySendState.SENT
    delivery.sending_at = delivery.created_at
    delivery.sent_at = delivery.created_at
    session.flush()
    path = f"/api/v1/outreach/deliveries/{delivery.id}/resend"

    first = auth_client.post(path, headers={"Idempotency-Key": "resend-replay-0001"})
    replay = auth_client.post(path, headers={"Idempotency-Key": "resend-replay-0001"})
    repeated = auth_client.post(path, headers={"Idempotency-Key": "resend-replay-0002"})
    queued_replacement = auth_client.post(
        f"/api/v1/outreach/deliveries/{first.json()['deliveries'][0]['id']}/resend",
        headers={"Idempotency-Key": "resend-queued-0001"},
    )

    assert first.status_code == replay.status_code == 201
    assert first.content == replay.content
    assert repeated.status_code == queued_replacement.status_code == 409
    assert repeated.json()["error"]["code"] == "delivery_not_resendable"
    assert queued_replacement.json()["error"]["code"] == "delivery_not_resendable"
    assert session.scalar(select(func.count()).select_from(SendBatch)) == 2
    assert session.scalar(select(func.count()).select_from(Delivery)) == 2


def test_confirmed_campaign_response_permanently_forbids_resend(
    auth_client, session: Session
) -> None:
    task, creators, campaign = _published_match(
        session, [("Alpha", "alpha@example.com")]
    )
    _configure(auth_client)
    created = _create_batch(
        auth_client, _payload(task, creators), "confirmed-seed-0001"
    )
    delivery = session.get(Delivery, UUID(created.json()["deliveries"][0]["id"]))
    assert delivery is not None
    delivery.send_state = DeliverySendState.SENT
    delivery.sending_at = delivery.created_at
    delivery.sent_at = delivery.created_at
    session.add(
        CampaignCreatorResponse(
            campaign_id=campaign.id,
            creator_id=delivery.creator_id,
            state=ResponseState.ACCEPTED,
            final_delivery_id=delivery.id,
            responded_at=delivery.created_at,
        )
    )
    session.flush()

    response = auth_client.post(
        f"/api/v1/outreach/deliveries/{delivery.id}/resend",
        headers={"Idempotency-Key": "confirmed-resend-0001"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "delivery_not_resendable"
    assert delivery.superseded_at is None
    assert session.scalar(select(func.count()).select_from(Delivery)) == 1


class _AllowAll:
    def allow(self, _workspace: str, _address: str) -> bool:
        return True


class _NoOutboundSMTP:
    def probe(self, _config: object) -> None:
        raise AssertionError("Send Batch must not probe SMTP")

    def send(self, _config: object, _message: object) -> None:
        raise AssertionError("Send Batch must not send SMTP")


class _NoRateLimit:
    def acquire(self, _workspace: str, _rate: int) -> float:
        raise AssertionError("Send Batch must not call Redis rate limiting")


def _concurrent_client(engine: Engine, workspace_key: str) -> TestClient:
    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_key),
        rate_limiter=_AllowAll(),
        secret_cipher=SecretCipher(bytes(range(32))),
        smtp_gateway=_NoOutboundSMTP(),
        smtp_rate_limiter=_NoRateLimit(),
    )

    @contextmanager
    def session_scope():
        with Session(engine) as value:
            try:
                yield value
            except Exception:
                value.rollback()
                raise

    def override_get_session():
        with session_scope() as value:
            yield value

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app, headers={"Authorization": f"Bearer {workspace_key}"})


def _committed_send_fixture(
    engine: Engine,
) -> tuple[UUID, list[UUID], UUID, UUID, UUID]:
    with Session(engine) as setup:
        assert (
            setup.scalar(select(ServiceSecret).where(ServiceSecret.service == "smtp"))
            is None
        )
        settings = setup.get(SharedSettings, SHARED_SETTINGS_ID)
        assert settings is not None
        state = dict(settings.service_connection_state)
        state["smtp"] = {
            **{
                name: SMTP_PAYLOAD[name]
                for name in (
                    "host",
                    "port",
                    "encryption",
                    "username",
                    "from_name",
                    "reply_to",
                )
            },
            "configured": True,
            "last_test_succeeded": None,
            "last_test_at": None,
        }
        settings.service_connection_state = state
        encrypted = SecretCipher(bytes(range(32))).encrypt("smtp-secret")
        setup.add(
            ServiceSecret(
                service="smtp",
                ciphertext=encrypted.ciphertext,
                nonce=encrypted.nonce,
            )
        )
        template = Template(
            name=f"Concurrent {uuid4()}",
            version=1,
            subject_template="Hello {{creator_name}}",
            body_markdown="{{match_reason}}",
            accepted_label="Yes",
            declined_label="No",
            is_default=False,
        )
        setup.add(template)
        setup.flush()
        task, creators, campaign = _published_match(
            setup, [("Concurrent Creator", "concurrent@example.com")]
        )
        setup.commit()
        return (
            task.id,
            [value.id for value in creators],
            campaign.id,
            template.id,
            task.game_id,
        )


def _cleanup_committed_send_fixture(
    engine: Engine,
    *,
    task_id: UUID,
    creator_ids: list[UUID],
    template_id: UUID,
    game_id: UUID,
) -> None:
    with Session(engine) as cleanup, cleanup.begin():
        cleanup.query(IdempotencyRecord).filter(
            IdempotencyRecord.path.like("/api/v1/outreach/%")
        ).delete(synchronize_session=False)
        cleanup.query(MatchTask).filter_by(id=task_id).delete()
        cleanup.query(Template).filter_by(id=template_id).delete()
        cleanup.query(CreatorProfile).filter(CreatorProfile.id.in_(creator_ids)).delete(
            synchronize_session=False
        )
        cleanup.query(GameProfile).filter_by(id=game_id).delete()
        cleanup.query(ServiceSecret).filter_by(service="smtp").delete()
        settings = cleanup.get(SharedSettings, SHARED_SETTINGS_ID)
        assert settings is not None
        state = dict(settings.service_connection_state)
        state.pop("smtp", None)
        settings.service_connection_state = state


def test_concurrent_same_key_create_converges_on_one_atomic_batch(
    database_engine: Engine, workspace_access_key: str, request
) -> None:
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
    payload = {
        "match_task_id": str(task_id),
        "creator_ids": [str(value) for value in creator_ids],
        "template_id": str(template_id),
    }

    def create() -> tuple[int, bytes]:
        with _concurrent_client(database_engine, workspace_access_key) as client:
            response = client.post(
                SEND_BATCH_PATH,
                json=payload,
                headers={"Idempotency-Key": "concurrent-same-key"},
            )
            return response.status_code, response.content

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _value: create(), range(2)))

    assert [status for status, _body in results] == [201, 201]
    assert results[0][1] == results[1][1]
    with Session(database_engine) as verify:
        assert verify.scalar(select(func.count()).select_from(SendBatch)) == 1
        assert verify.scalar(select(func.count()).select_from(Delivery)) == 1
        assert (
            verify.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.key == "concurrent-same-key")
            )
            == 1
        )


def test_concurrent_different_key_overlap_leaves_no_partial_batch(
    database_engine: Engine, workspace_access_key: str, request
) -> None:
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
    payload = {
        "match_task_id": str(task_id),
        "creator_ids": [str(value) for value in creator_ids],
        "template_id": str(template_id),
    }

    def create(key: str) -> tuple[int, str | None]:
        with _concurrent_client(database_engine, workspace_access_key) as client:
            response = client.post(
                SEND_BATCH_PATH, json=payload, headers={"Idempotency-Key": key}
            )
            return response.status_code, response.json().get("error", {}).get("code")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ("concurrent-key-one", "concurrent-key-two")))

    assert sorted(status for status, _code in results) == [201, 409]
    assert [code for status, code in results if status == 409] == [
        "explicit_resend_required"
    ]
    with Session(database_engine) as verify:
        assert verify.scalar(select(func.count()).select_from(SendBatch)) == 1
        assert verify.scalar(select(func.count()).select_from(Delivery)) == 1


def test_concurrent_resends_supersede_once_and_report_read_only_loser(
    database_engine: Engine, workspace_access_key: str, request
) -> None:
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
    payload = {
        "match_task_id": str(task_id),
        "creator_ids": [str(value) for value in creator_ids],
        "template_id": str(template_id),
    }
    with _concurrent_client(database_engine, workspace_access_key) as client:
        created = client.post(
            SEND_BATCH_PATH,
            json=payload,
            headers={"Idempotency-Key": "concurrent-resend-seed"},
        )
    delivery_id = UUID(created.json()["deliveries"][0]["id"])
    with Session(database_engine) as setup, setup.begin():
        delivery = setup.get(Delivery, delivery_id)
        assert delivery is not None
        delivery.send_state = DeliverySendState.SENT
        delivery.sending_at = delivery.created_at
        delivery.sent_at = delivery.created_at

    initial_reads = Barrier(2)
    seen_connections: set[int] = set()
    seen_lock = Lock()

    def synchronize_initial_reads(
        connection, _cursor, statement, parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.casefold().split())
        if (
            "from deliveries" not in normalized
            or "for update" in normalized
            or delivery_id not in parameters.values()
        ):
            return
        connection_id = id(connection)
        with seen_lock:
            if connection_id in seen_connections:
                return
            seen_connections.add(connection_id)
        initial_reads.wait(timeout=10)

    event.listen(database_engine, "after_cursor_execute", synchronize_initial_reads)

    def resend(key: str) -> tuple[int, str | None]:
        with _concurrent_client(database_engine, workspace_access_key) as client:
            response = client.post(
                f"/api/v1/outreach/deliveries/{delivery_id}/resend",
                headers={"Idempotency-Key": key},
            )
            return response.status_code, response.json().get("error", {}).get("code")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(resend, ("resend-race-one", "resend-race-two")))
    finally:
        event.remove(database_engine, "after_cursor_execute", synchronize_initial_reads)

    assert sorted(status for status, _code in results) == [201, 409]
    assert [code for status, code in results if status == 409] == [
        "delivery_not_resendable"
    ]
    with Session(database_engine) as verify:
        old = verify.get(Delivery, delivery_id)
        assert old is not None and old.superseded_at is not None
        assert verify.scalar(select(func.count()).select_from(SendBatch)) == 2
        assert verify.scalar(select(func.count()).select_from(Delivery)) == 2
