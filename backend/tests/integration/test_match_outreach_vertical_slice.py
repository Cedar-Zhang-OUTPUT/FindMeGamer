from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from html import unescape
import json
import re
import socket
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.matching.pairwise import PairwiseService
from app.matching.ranking import RankingService
from app.matching.screening import ScreeningService
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import (
    FinalRankingOutput,
    PairwiseMatchBrief,
    ScreeningOutput,
)
from app.workers.match_tasks import (
    START_MATCH_TASK_NAME,
    MatchTaskExecutor,
    MatchTaskStore,
)
from app.workers.outreach_tasks import DeliveryExecutor


SMTP_PASSWORD = "vertical-smtp-password-never-return"
EXTERNAL_BASE_URL = "https://demo.findmegamer.example"
HIDDEN_BACKEND_ORDER = 7013
HIDDEN_SCORES = {0.9876, 0.8765, 0.8654, 0.8543, 0.8432, 0.8321}
FORBIDDEN_RESPONSE_FIELDS = {
    "response_token",
    "response_token_digest",
    "response_capability",
    "response_capability_digest",
    "ciphertext",
    "nonce",
    "password",
    "master_key",
    "master_key_file",
    "backend_order",
    "rank",
    "total_score",
    "dimension_scores",
}


def _available(value: str) -> dict[str, object]:
    return {
        "status": "available",
        "value": value,
        "evidence": [
            {
                "kind": "source_fact",
                "source_type": "steam_field",
                "reference": "vertical-slice:fixture",
            }
        ],
        "confidence": "high",
    }


def _unavailable(reason: str) -> dict[str, str]:
    return {"status": "unavailable", "reason": reason}


def _game_brief() -> dict[str, object]:
    missing = _unavailable("No additional game evidence is needed for this test.")
    return GameBrief.model_validate(
        {
            "positioning_premise": _available("A cooperative tactical adventure."),
            "core_gameplay_loop": missing,
            "genres": missing,
            "themes": missing,
            "tone": missing,
            "visual_identity": missing,
            "target_audience": missing,
            "key_selling_points": missing,
            "content_hooks": missing,
            "comparable_games": missing,
            "suitable_creator_types": missing,
            "promotion_risks": missing,
        }
    ).model_dump(mode="json")


def _creator_brief() -> dict[str, object]:
    missing = _unavailable("No additional creator evidence is needed for this test.")
    return CreatorBrief.model_validate(
        {
            "positioning": _available("English-language cooperative game coverage."),
            "content_focus": missing,
            "formats": missing,
            "style_and_pacing": missing,
            "audience": {**missing, "provenance": "ai_inference"},
            "performance_context": missing,
            "promotion_fit": missing,
            "brand_safety": missing,
            "suitable_game_types": missing,
            "collaboration_risks": missing,
        }
    ).model_dump(mode="json")


def _seed_profiles(session: Session) -> tuple[GameProfile, CreatorProfile]:
    now = datetime.now(UTC)
    game = GameProfile(
        steam_app_id=str(uuid4().int % 10**16),
        canonical_url="https://store.steampowered.com/app/7013",
        sort_name="Vertical Tactics",
        current_facts={
            "name": "Vertical Tactics",
            "cover_image_url": "https://cdn.example/vertical-game.jpg",
        },
        analysis={},
        brief=_game_brief(),
        source_status={"steam": "current"},
        last_analyzed_at=now,
        next_analysis_at=now + timedelta(days=30),
    )
    channel_id = f"UC{uuid4().hex[:22]}"
    creator = CreatorProfile(
        youtube_channel_id=channel_id,
        canonical_url=f"https://www.youtube.com/channel/{channel_id}",
        sort_name="Vertical Creator",
        current_facts={
            "channel_id": channel_id,
            "canonical_url": f"https://www.youtube.com/channel/{channel_id}",
            "title": "Vertical Creator",
            "subscriber_count": 12345,
            "recent_metrics": {"average_views": 4321, "median_views": 4000},
        },
        analysis={},
        brief=_creator_brief(),
        source_status={"youtube": "current", "freshness": "current"},
        last_analyzed_at=now,
        next_analysis_at=now + timedelta(days=14),
    )
    session.add_all([game, creator])
    session.flush()
    session.add(
        CreatorContact(
            creator_id=creator.id,
            email="vertical.creator@example.com",
            source_type="manual",
            is_manual=True,
            validation_state="verified",
            priority=0,
            is_active=True,
        )
    )
    session.flush()
    return game, creator


class DeterministicMatchAI:
    def __init__(self, creator_id: UUID) -> None:
        self.creator_id = creator_id
        self.schemas: list[type] = []

    def complete_structured(self, _model: str, _messages: list, schema: type) -> object:
        self.schemas.append(schema)
        if schema is ScreeningOutput:
            return ScreeningOutput.model_validate(
                {
                    "english_language_check": True,
                    "selected": [
                        {
                            "creator_id": self.creator_id,
                            "screening_reason": "The supplied evidence supports a fit.",
                            "evidence": ["The creator covers cooperative games."],
                        }
                    ],
                }
            )
        dimension = {
            "analysis": "The supplied evidence supports this fit.",
            "evidence": ["The creator covers cooperative games."],
        }
        if schema is PairwiseMatchBrief:
            return PairwiseMatchBrief.model_validate(
                {
                    "english_language_check": True,
                    "creator_id": self.creator_id,
                    "content_fit": dimension,
                    "audience_fit": dimension,
                    "performance_fit": dimension,
                    "promotion_fit": dimension,
                    "brand_safety": dimension,
                    "strengths": ["Clear alignment with the game."],
                    "risks": ["Timing still needs confirmation."],
                    "evidence": ["The creator covers cooperative games."],
                    "match_reasons": ["The content focus suits this launch."],
                }
            )
        if schema is FinalRankingOutput:
            return FinalRankingOutput.model_validate(
                {
                    "english_language_check": True,
                    "items": [
                        {
                            "creator_id": self.creator_id,
                            "total_score": 0.9876,
                            "dimension_scores": {
                                "content_fit": 0.8765,
                                "audience_fit": 0.8654,
                                "performance_fit": 0.8543,
                                "promotion_fit": 0.8432,
                                "brand_safety": 0.8321,
                            },
                            "backend_order": HIDDEN_BACKEND_ORDER,
                            "result_group": "recommended",
                            "qualitative_label": "Strong Match",
                            "dimension_outcomes": {
                                "content_fit": "The content aligns well.",
                                "audience_fit": "The audience is suitable.",
                                "performance_fit": "Recent performance is suitable.",
                                "promotion_fit": "The format suits the launch.",
                                "brand_safety": "No concern appears in the evidence.",
                            },
                            "match_reasons": [
                                "The creator is a strong qualitative fit."
                            ],
                        }
                    ],
                }
            )
        raise AssertionError(f"Unexpected AI schema: {schema!r}")


class EagerGraphDispatcher:
    def __init__(self) -> None:
        self.pairwise: list[tuple[UUID, UUID]] = []
        self.advance: list[UUID] = []
        self.ranking: list[UUID] = []

    def dispatch_pairwise(self, task_id: UUID, creator_id: UUID) -> None:
        self.pairwise.append((task_id, creator_id))

    def dispatch_advance(self, task_id: UUID) -> None:
        self.advance.append(task_id)

    def dispatch_ranking(self, task_id: UUID) -> None:
        self.ranking.append(task_id)


@contextmanager
def _nested_session(outer: Session) -> Iterator[Session]:
    nested = Session(bind=outer.get_bind(), join_transaction_mode="create_savepoint")
    try:
        yield nested
    finally:
        nested.close()


def _finish_match(session: Session, task_id: UUID, creator_id: UUID) -> list[type]:
    clock = lambda: datetime.now(UTC)
    session_factory = lambda: _nested_session(session)
    ai = DeterministicMatchAI(creator_id)
    dispatcher = EagerGraphDispatcher()

    @contextmanager
    def pairwise_factory() -> Iterator[PairwiseService]:
        yield PairwiseService(session_factory=session_factory, ai=ai, clock=clock)

    @contextmanager
    def ranking_factory() -> Iterator[RankingService]:
        yield RankingService(session_factory=session_factory, ai=ai, clock=clock)

    executor = MatchTaskExecutor(
        screening=ScreeningService(
            session_factory=session_factory,
            ai=ai,
            clock=clock,
        ),
        pairwise_factory=pairwise_factory,
        store=MatchTaskStore(session_factory=session_factory, clock=clock),
        dispatcher=dispatcher,
        ranking_factory=ranking_factory,
    )
    executor.start(task_id)
    assert dispatcher.pairwise == [(task_id, creator_id)]
    while dispatcher.pairwise:
        pair_task_id, pair_creator_id = dispatcher.pairwise.pop(0)
        executor.run_pair(pair_task_id, pair_creator_id)
    assert dispatcher.advance == [task_id]
    while dispatcher.advance:
        executor.advance(dispatcher.advance.pop(0))
    assert dispatcher.ranking == [task_id]
    while dispatcher.ranking:
        executor.finalize(dispatcher.ranking.pop(0))
    return ai.schemas


def _configure_outreach(auth_client) -> list[dict[str, object]]:
    smtp = auth_client.put(
        "/api/v1/outreach/smtp",
        json={
            "host": "smtp.example.com",
            "port": 465,
            "encryption": "tls",
            "username": "sender@example.com",
            "password": SMTP_PASSWORD,
            "from_name": "Find Me Gamer Team",
            "reply_to": "reply@example.com",
            "emails_per_minute": 10,
        },
    )
    assert smtp.status_code == 200, smtp.text
    template = auth_client.post(
        "/api/v1/outreach/templates",
        json={
            "name": "Vertical invitation",
            "subject_template": "{{creator_name}} and {{game_name}}",
            "body_markdown": (
                "Hello {{channel_name}}. {{game_summary}} "
                "Why this fits: {{match_reason}} From {{sender_name}}. {{steam_url}}"
            ),
            "accepted_label": "Interested",
            "declined_label": "Not now",
        },
    )
    assert template.status_code == 201, template.text
    assert template.json()["is_default"] is True
    return [smtp.json(), template.json()]


def _all_mapping_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            *(str(key).casefold() for key in value),
            *(key for item in value.values() for key in _all_mapping_keys(item)),
        }
    if isinstance(value, list):
        return {key for item in value for key in _all_mapping_keys(item)}
    return set()


def _all_scalar_values(value: object) -> list[object]:
    if isinstance(value, dict):
        return [
            item for nested in value.values() for item in _all_scalar_values(nested)
        ]
    if isinstance(value, list):
        return [item for nested in value for item in _all_scalar_values(nested)]
    return [value]


def _reachable_openapi_components(
    schema: dict[str, object], roots: tuple[str, ...]
) -> dict[str, object]:
    components = schema["components"]["schemas"]
    pending = list(roots)
    reached: dict[str, object] = {}
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        component = components[name]
        reached[name] = component
        serialized = json.dumps(component, sort_keys=True)
        pending.extend(
            candidate
            for candidate in re.findall(r"#/components/schemas/([^\"/]+)", serialized)
            if candidate not in reached
        )
    return reached


def _accepted_url(message: EmailMessage) -> str:
    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    html = html_part.get_content()
    match = re.search(r'href="(?P<url>[^\"]+/r/[^\"]+\?choice=accepted)"', html)
    assert match is not None
    return unescape(match.group("url"))


def test_match_to_accepted_response_vertical_slice(
    auth_client,
    session: Session,
    match_dispatcher,
    outreach_batch_dispatcher,
    smtp_gateway,
    smtp_rate_limiter,
    captured_logs,
    monkeypatch,
) -> None:
    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("vertical slice attempted external network access")

    class GuardedSocket(socket.socket):
        def connect(self, *_args, **_kwargs):
            unexpected_network()

        def connect_ex(self, *_args, **_kwargs):
            unexpected_network()

    monkeypatch.setattr(socket, "socket", GuardedSocket)
    monkeypatch.setattr(socket, "create_connection", unexpected_network)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_network)
    monkeypatch.setattr(socket, "gethostbyname", unexpected_network)
    monkeypatch.setattr(socket, "gethostbyname_ex", unexpected_network)

    game, creator = _seed_profiles(session)
    authenticated_payloads = _configure_outreach(auth_client)

    created = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "vertical-match-create"},
        json={"game_id": str(game.id)},
    )
    assert created.status_code == 202, created.text
    created_match = created.json()
    match_id = UUID(created_match["id"])
    assert match_dispatcher.calls == [(START_MATCH_TASK_NAME, match_id)]
    assert _finish_match(session, match_id, creator.id) == [
        ScreeningOutput,
        PairwiseMatchBrief,
        FinalRankingOutput,
    ]

    match_response = auth_client.get(f"/api/v1/matches/{match_id}")
    assert match_response.status_code == 200, match_response.text
    match_detail = match_response.json()
    assert match_detail["status"] == "succeeded"
    assert match_detail["result_state"] == "available"
    assert len(match_detail["recommended_matches"]) == 1
    recommended = match_detail["recommended_matches"][0]
    assert recommended["creator"]["id"] == str(creator.id)
    assert recommended["creator"]["contact"] == {
        "email": "vertical.creator@example.com",
        "purpose": None,
        "source": "manual",
        "source_url": None,
        "validation_state": "verified",
    }
    assert recommended["creator"]["contacts"] == [recommended["creator"]["contact"]]
    assert recommended["creator"]["subscriber_count"] == 12345

    batch_response = auth_client.post(
        "/api/v1/outreach/send-batches",
        headers={"Idempotency-Key": "vertical-send-batch"},
        json={
            "match_task_id": str(match_id),
            "creator_ids": [recommended["creator"]["id"]],
        },
    )
    assert batch_response.status_code == 201, batch_response.text
    batch = batch_response.json()
    batch_id = UUID(batch["id"])
    campaign_id = UUID(batch["campaign_id"])
    delivery_id = UUID(batch["deliveries"][0]["id"])
    assert outreach_batch_dispatcher.calls == [batch_id]

    executor = DeliveryExecutor(
        session_factory=lambda: _nested_session(session),
        secret_cipher=SecretCipher(bytes(range(32))),
        smtp_gateway=smtp_gateway,
        smtp_rate_limiter=smtp_rate_limiter,
        external_base_url=EXTERNAL_BASE_URL,
        clock=lambda: datetime.now(UTC),
        sleeper=lambda _delay: None,
    )
    executor.execute(delivery_id, retrying=False)
    assert len(smtp_gateway.sends) == 1
    assert len(smtp_rate_limiter.calls) == 1

    accepted_url = _accepted_url(smtp_gateway.sends[0][1])
    parsed_url = urlsplit(accepted_url)
    assert f"{parsed_url.scheme}://{parsed_url.netloc}" == EXTERNAL_BASE_URL
    assert parse_qs(parsed_url.query) == {"choice": ["accepted"]}
    raw_capability = parsed_url.path.rsplit("/", 1)[-1]
    assert raw_capability

    confirmation = auth_client.post(
        parsed_url.path,
        data={"choice": "accepted"},
    )
    assert confirmation.status_code == 200
    assert "Your final response is Accepted." in confirmation.text

    campaign_response = auth_client.get(f"/api/v1/outreach/campaigns/{campaign_id}")
    assert campaign_response.status_code == 200, campaign_response.text
    campaign = campaign_response.json()
    assert campaign["metrics"] == {
        "sent_creators": 1,
        "accepted": 1,
        "declined": 0,
        "no_response": 0,
        "failed": 0,
        "response_rate": 1.0,
    }
    assert campaign["state"] == "completed"
    deliveries = [
        delivery
        for send_batch in campaign["send_batches"]
        for delivery in send_batch["deliveries"]
    ]
    assert len(deliveries) == 1
    assert deliveries[0]["id"] == str(delivery_id)
    assert deliveries[0]["send_state"] == "sent"
    assert deliveries[0]["response_state"] == "accepted"

    executor.execute(delivery_id, retrying=False)
    repeated_match = auth_client.get(f"/api/v1/matches/{match_id}")
    repeated_campaign = auth_client.get(f"/api/v1/outreach/campaigns/{campaign_id}")
    assert repeated_match.status_code == repeated_campaign.status_code == 200
    assert len(smtp_gateway.sends) == 1

    authenticated_payloads.extend(
        [
            created_match,
            match_detail,
            batch,
            campaign,
            repeated_match.json(),
            repeated_campaign.json(),
        ]
    )
    for payload in authenticated_payloads:
        assert _all_mapping_keys(payload).isdisjoint(FORBIDDEN_RESPONSE_FIELDS)
        values = _all_scalar_values(payload)
        assert HIDDEN_BACKEND_ORDER not in values
        assert HIDDEN_SCORES.isdisjoint(values)
        assert raw_capability not in json.dumps(payload, sort_keys=True)
        assert SMTP_PASSWORD not in json.dumps(payload, sort_keys=True)

    openapi_components = _reachable_openapi_components(
        auth_client.app.openapi(),
        (
            "MatchDetail",
            "OutreachSendBatchResponse",
            "OutreachCampaignDetail",
            "OutreachDeliveryDetail",
            "SMTPSettingsResponse",
        ),
    )
    assert _all_mapping_keys(openapi_components).isdisjoint(FORBIDDEN_RESPONSE_FIELDS)
    openapi_text = json.dumps(openapi_components, sort_keys=True).casefold()
    assert raw_capability.casefold() not in openapi_text
    assert SMTP_PASSWORD.casefold() not in openapi_text

    log_output = "\n".join(record.getMessage() for record in captured_logs.records)
    assert '"route":"/r/{token}"' in log_output
    assert raw_capability not in log_output
    assert SMTP_PASSWORD not in log_output
