from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from threading import Barrier, Event, Lock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine

from app.core.crypto import SecretCipher
from app.core.security import hash_workspace_key
from app.main import create_app

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
    Delivery,
    DeliverySendState,
    OutreachCampaign,
    ResponseState,
    SendBatch,
)
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.db.models.settings import SharedSettings
from app.repositories.match import MatchRepository
from app.repositories.settings import SHARED_SETTINGS_ID
from app.matching.pairwise import SQLPairwiseRepository
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import PairwiseMatchBrief
from app.workers.match_tasks import FINALIZE_MATCH_TASK_NAME, START_MATCH_TASK_NAME


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _unavailable(reason: str) -> dict[str, str]:
    return {"status": "unavailable", "reason": reason}


def _game_brief() -> dict[str, object]:
    claim = _unavailable("Game fact unavailable.")
    return GameBrief.model_validate(
        {
            "positioning_premise": claim,
            "core_gameplay_loop": claim,
            "genres": claim,
            "themes": claim,
            "tone": claim,
            "visual_identity": claim,
            "target_audience": claim,
            "key_selling_points": claim,
            "content_hooks": claim,
            "comparable_games": claim,
            "suitable_creator_types": claim,
            "promotion_risks": claim,
        }
    ).model_dump(mode="json")


def _creator_brief() -> dict[str, object]:
    claim = _unavailable("Creator fact unavailable.")
    return CreatorBrief.model_validate(
        {
            "positioning": claim,
            "content_focus": claim,
            "formats": claim,
            "style_and_pacing": claim,
            "audience": {**claim, "provenance": "ai_inference"},
            "performance_context": claim,
            "promotion_fit": claim,
            "brand_safety": claim,
            "suitable_game_types": claim,
            "collaboration_risks": claim,
        }
    ).model_dump(mode="json")


def _pairwise(creator_id: UUID) -> dict[str, object]:
    dimension = {"analysis": "A useful fit.", "evidence": ["Public evidence."]}
    return PairwiseMatchBrief.model_validate(
        {
            "english_language_check": True,
            "creator_id": creator_id,
            "content_fit": dimension,
            "audience_fit": dimension,
            "performance_fit": dimension,
            "promotion_fit": dimension,
            "brand_safety": dimension,
            "strengths": ["Clear strength."],
            "risks": ["Manageable risk."],
            "evidence": ["Public evidence."],
            "match_reasons": ["Task-specific reason."],
        }
    ).model_dump(mode="json")


def _profiles(session: Session) -> tuple[GameProfile, CreatorProfile]:
    game = GameProfile(
        steam_app_id=str(uuid4().int % 10**16),
        canonical_url="https://store.steampowered.com/app/10",
        sort_name="Current Game",
        current_facts={
            "name": "Current Game",
            "cover_image_url": "https://cdn.example/game.jpg",
        },
        analysis={},
        brief=_game_brief(),
        source_status={"steam": "current"},
        last_analyzed_at=NOW,
        next_analysis_at=NOW + timedelta(days=30),
    )
    channel = f"UC{uuid4().hex[:22]}"
    creator = CreatorProfile(
        youtube_channel_id=channel,
        canonical_url=f"https://www.youtube.com/channel/{channel}",
        sort_name="Current Creator",
        current_facts={
            "channel_id": channel,
            "canonical_url": f"https://www.youtube.com/channel/{channel}",
            "title": "Current Creator",
            "custom_url": "@currentcreator",
            "published_at": "2020-01-01T00:00:00Z",
            "country": "US",
            "avatar_url": "https://cdn.example/avatar.jpg",
            "banner_url": "https://cdn.example/banner.jpg",
            "subscriber_count": 1234,
            "hidden_subscriber_count": False,
            "total_view_count": 10000,
            "public_video_count": 20,
            "recent_metrics": {
                "recent_public_video_count": 3,
                "numeric_view_sample_count": 2,
                "average_views": 321.5,
                "median_views": 300.5,
                "publishing_frequency": None,
                "newest_published_at": "2026-08-30T00:00:00Z",
                "oldest_published_at": "2026-08-01T00:00:00Z",
            },
            "representative_videos": [],
        },
        analysis={
            "recent_performance_summary": {
                "status": "available",
                "value": "Steady recent performance.",
                "evidence": [
                    {
                        "kind": "source_fact",
                        "source_type": "video_id",
                        "reference": "video:video-1",
                        "observation": "Recent public views are consistent.",
                    }
                ],
                "confidence": "high",
            }
        },
        brief=_creator_brief(),
        source_status={"youtube": "current", "freshness": "current"},
        favorite=True,
        last_analyzed_at=NOW,
        next_analysis_at=NOW + timedelta(days=14),
    )
    session.add_all([game, creator])
    session.flush()
    return game, creator


def _task(
    session: Session,
    game: GameProfile,
    *,
    status: MatchStatus = MatchStatus.QUEUED,
    stage: MatchStage = MatchStage.SCREENING,
    created_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> MatchTask:
    terminal = status in {
        MatchStatus.SUCCEEDED,
        MatchStatus.FAILED,
        MatchStatus.SUPERSEDED,
    }
    task = MatchTask(
        game_id=game.id,
        locked_game_brief=_game_brief(),
        shuffle_seed=42,
        recommended_match_threshold=Decimal("0.7000"),
        status=status,
        stage=stage,
        completed_units=1 if status is not MatchStatus.QUEUED else 0,
        total_units=1 if status is not MatchStatus.QUEUED else 0,
        result_count=0,
        error_code="deepseek_unavailable" if status is MatchStatus.FAILED else None,
        error_message=(
            "secret raw provider text" if status is MatchStatus.FAILED else None
        ),
        retryable=status is MatchStatus.FAILED,
        correlation_id=str(uuid4()),
        input_expires_at=expires_at or NOW + timedelta(days=30),
        started_at=None if status is MatchStatus.QUEUED else created_at,
        completed_at=created_at if terminal else None,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(task)
    session.flush()
    return task


def test_match_routes_require_authentication_and_idempotency(
    client: TestClient, auth_client: TestClient, session: Session
) -> None:
    game, _creator = _profiles(session)
    authorization = client.headers.pop("Authorization")
    assert client.get("/api/v1/matches").status_code == 401
    client.headers["Authorization"] = authorization
    missing_key = auth_client.post("/api/v1/matches", json={"game_id": str(game.id)})
    assert missing_key.status_code == 422
    closed = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-closed"},
        json={"game_id": str(game.id), "seed": 99},
    )
    assert closed.status_code == 422


def test_create_match_freezes_settings_dispatches_once_and_replays_current_state(
    auth_client: TestClient, session: Session, match_dispatcher
) -> None:
    game, creator = _profiles(session)
    settings = session.get(SharedSettings, SHARED_SETTINGS_ID)
    assert settings is not None
    settings.recommended_match_threshold = Decimal("0.83")
    response = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-create-1"},
        json={"game_id": str(game.id)},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["stage"] == "screening"
    assert body["game"]["id"] == str(game.id)
    assert body["game"]["cover_url"] == "https://cdn.example/game.jpg"
    assert set(body).isdisjoint(
        {"shuffle_seed", "recommended_match_threshold", "locked_game_brief"}
    )
    saved = session.get(MatchTask, UUID(body["id"]))
    assert saved is not None
    assert saved.recommended_match_threshold == Decimal("0.8300")
    assert -(2**63) <= saved.shuffle_seed <= 2**63 - 1
    assert saved.correlation_id == response.headers["X-Correlation-ID"]
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatchCandidateInput)
            .where(MatchCandidateInput.match_task_id == saved.id)
        )
        == 1
    )
    assert match_dispatcher.calls == [(START_MATCH_TASK_NAME, saved.id)]
    replay = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-create-1"},
        json={"game_id": str(game.id)},
    )
    assert replay.status_code == 202
    assert replay.json()["id"] == body["id"]
    assert match_dispatcher.calls == [(START_MATCH_TASK_NAME, saved.id)]
    assert creator.id


def test_create_rejects_missing_or_unusable_game_and_key_conflict(
    auth_client: TestClient, session: Session
) -> None:
    missing = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-missing"},
        json={"game_id": str(uuid4())},
    )
    assert missing.status_code == 404
    game, _creator = _profiles(session)
    first = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-conflict"},
        json={"game_id": str(game.id)},
    )
    assert first.status_code == 202
    other, _ = _profiles(session)
    conflict = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-conflict"},
        json={"game_id": str(other.id)},
    )
    assert conflict.status_code == 409
    game.brief = {"bad": "brief"}
    unusable = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-unusable"},
        json={"game_id": str(game.id)},
    )
    assert unusable.status_code == 409


def test_broker_failure_safely_fails_committed_task_and_replay_does_not_dispatch(
    auth_client: TestClient, session: Session, match_dispatcher
) -> None:
    game, _ = _profiles(session)
    match_dispatcher.error = RuntimeError("redis://user:password@private:6379")
    response = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-broker"},
        json={"game_id": str(game.id)},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "failed"
    assert body["retryable"] is True
    assert body["error"] == {
        "code": "match_queue_unavailable",
        "message": "Match could not be queued. Please retry.",
    }
    assert "password" not in json.dumps(body)
    saved = session.get(MatchTask, UUID(body["id"]))
    assert saved is not None and saved.locked_game_brief is not None
    match_dispatcher.error = None
    replay = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-broker"},
        json={"game_id": str(game.id)},
    )
    assert replay.json() == body
    assert len(match_dispatcher.calls) == 1


def test_match_history_is_reverse_paginated_current_game_and_cursor_is_scoped(
    auth_client: TestClient, session: Session
) -> None:
    game, _ = _profiles(session)
    older = _task(session, game, created_at=NOW - timedelta(hours=1))
    newer = _task(session, game, status=MatchStatus.FAILED, created_at=NOW)
    game.sort_name = "Renamed Game"
    first = auth_client.get("/api/v1/matches", params={"limit": 1})
    assert first.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == [str(newer.id)]
    item = first.json()["items"][0]
    assert item["game"]["name"] == "Renamed Game"
    assert item["error"]["message"] != newer.error_message
    assert set(item).isdisjoint(
        {"shuffle_seed", "recommended_match_threshold", "backend_order"}
    )
    second = auth_client.get(
        "/api/v1/matches", params={"cursor": first.json()["cursor"], "limit": 1}
    )
    assert [item["id"] for item in second.json()["items"]] == [str(older.id)]
    tampered = first.json()["cursor"][:-1] + (
        "A" if first.json()["cursor"][-1] != "A" else "B"
    )
    assert (
        auth_client.get("/api/v1/matches", params={"cursor": tampered}).status_code
        == 400
    )


def test_match_detail_groups_hidden_order_and_projects_current_creator_contact_outreach(
    auth_client: TestClient, session: Session
) -> None:
    game, creator = _profiles(session)
    task = _task(session, game, status=MatchStatus.SUCCEEDED, stage=MatchStage.RANKING)
    task.completed_units = task.total_units = 3
    task.result_count = 2
    contact = CreatorContact(
        creator_id=creator.id,
        email="manual@example.com",
        source_type="manual",
        source_url=None,
        is_manual=True,
        validation_state="verified",
        priority=0,
        is_active=True,
    )
    session.add(contact)
    session.add(
        CreatorContact(
            creator_id=creator.id,
            email="press@example.com",
            purpose="Press requests",
            source_type="public_web_research",
            source_url="https://creator.example/press",
            is_manual=False,
            validation_state="unverified",
            priority=10,
            is_active=True,
        )
    )
    screening = MatchScreeningRecord(
        match_task_id=task.id,
        creator_id=creator.id,
        screening_order=0,
        locked_creator_brief=_creator_brief(),
        selected=True,
        expires_at=task.input_expires_at,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(screening)
    session.flush()
    candidate = MatchCandidateInput(
        match_task_id=task.id,
        creator_id=creator.id,
        locked_creator_profile={"id": str(creator.id)},
        input_model_metadata={},
        input_prompt_metadata={},
        expires_at=task.input_expires_at,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(candidate)
    session.flush()
    pair = MatchPairwiseRecord(
        match_task_id=task.id,
        creator_id=creator.id,
        state=PairwiseState.SUCCEEDED,
        attempt_count=1,
        match_brief=_pairwise(creator.id),
        retryable=False,
        started_at=NOW,
        completed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(pair)
    session.flush()
    second_creator = _second_creator(session)
    _add_checkpoint_chain(session, task, second_creator, order=1)
    for creator_value, order, group in (
        (creator, 8, MatchResultGroup.OTHER),
        (second_creator, 2, MatchResultGroup.RECOMMENDED),
    ):
        session.add(
            MatchResultItem(
                match_task_id=task.id,
                creator_id=creator_value.id,
                backend_order=order,
                match_brief=_pairwise(creator_value.id),
                total_score=Decimal("0.8000"),
                dimension_scores={"hidden": 1},
                dimension_outcomes={
                    key: "Public outcome."
                    for key in (
                        "content_fit",
                        "audience_fit",
                        "performance_fit",
                        "promotion_fit",
                        "brand_safety",
                    )
                },
                match_reasons=["Current task reason."],
                result_group=group,
                qualitative_label="Good Match",
            )
        )
    campaign = OutreachCampaign(match_task_id=task.id)
    session.add(campaign)
    session.flush()
    batch = SendBatch(
        campaign_id=campaign.id, requested_creator_ids=[str(creator.id)], state="sent"
    )
    session.add(batch)
    session.flush()
    session.add(
        Delivery(
            campaign_id=campaign.id,
            send_batch_id=batch.id,
            creator_id=creator.id,
            recipient_email="manual@example.com",
            rendered_subject="Subject",
            rendered_markdown="Body",
            rendered_html="<p>Body</p>",
            template_name="Template",
            template_version=1,
            accepted_label="Yes",
            declined_label="No",
            sender_name="Team",
            sender_address="team@example.com",
            reply_to="reply@example.com",
            send_state=DeliverySendState.SENT,
            response_state=ResponseState.ACCEPTED,
            response_token_digest="a" * 64,
            sending_at=NOW,
            sent_at=NOW,
            responded_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()
    current_body = auth_client.get(f"/api/v1/matches/{task.id}").json()
    current_visible = current_body["other_matches"][0]["creator"]
    assert current_visible["subscriber_count"] == 1234
    assert current_visible["recent_average_views"] == 322
    assert current_visible["recent_median_views"] == 301
    assert current_visible["performance_summary"] == "Steady recent performance."
    assert current_visible["contact"]["email"] == "manual@example.com"
    assert [contact["email"] for contact in current_visible["contacts"]] == [
        "manual@example.com",
        "press@example.com",
    ]
    assert current_visible["contacts"][1]["purpose"] == "Press requests"

    creator.source_status = {"youtube": "stale", "freshness": "stale"}
    session.flush()
    body = auth_client.get(f"/api/v1/matches/{task.id}").json()
    assert [item["creator"]["id"] for item in body["recommended_matches"]] == [
        str(second_creator.id)
    ]
    assert [item["creator"]["id"] for item in body["other_matches"]] == [
        str(creator.id)
    ]
    visible = body["other_matches"][0]
    assert visible["creator"]["name"] == "Current Creator"
    assert visible["creator"]["contact"]["email"] == "manual@example.com"
    assert [contact["email"] for contact in visible["creator"]["contacts"]] == [
        "manual@example.com"
    ]
    assert visible["creator"]["subscriber_count"] is None
    assert visible["creator"]["recent_average_views"] is None
    assert visible["outreach"]["send_state"] == "sent"
    assert visible["outreach"]["response_state"] == "accepted"
    assert "backend_order" not in json.dumps(body)
    assert "dimension_scores" not in json.dumps(body)


def test_match_detail_uses_available_creator_brief_performance_fallback(
    auth_client: TestClient, session: Session
) -> None:
    game, creator = _profiles(session)
    creator.analysis = {
        "recent_performance_summary": _unavailable(
            "Recent performance analysis unavailable."
        )
    }
    brief = _creator_brief()
    brief["performance_context"] = {
        "status": "available",
        "value": "Brief-backed recent performance.",
        "evidence": [
            {
                "kind": "source_fact",
                "source_type": "video_id",
                "reference": "video:video-1",
            }
        ],
        "confidence": "high",
    }
    creator.brief = CreatorBrief.model_validate(brief).model_dump(mode="json")
    task = _task(session, game, status=MatchStatus.SUCCEEDED, stage=MatchStage.RANKING)
    task.completed_units = task.total_units = 3
    task.result_count = 1
    _add_checkpoint_chain(session, task, creator, order=0)
    session.add(
        MatchResultItem(
            match_task_id=task.id,
            creator_id=creator.id,
            backend_order=0,
            match_brief=_pairwise(creator.id),
            total_score=Decimal("0.8000"),
            dimension_scores={"hidden": 1},
            dimension_outcomes={
                key: "Public outcome."
                for key in (
                    "content_fit",
                    "audience_fit",
                    "performance_fit",
                    "promotion_fit",
                    "brand_safety",
                )
            },
            match_reasons=["Current task reason."],
            result_group=MatchResultGroup.RECOMMENDED,
            qualitative_label="Good Match",
        )
    )
    session.add(OutreachCampaign(match_task_id=task.id))
    session.flush()

    response = auth_client.get(f"/api/v1/matches/{task.id}")

    assert response.status_code == 200
    creator_body = response.json()["recommended_matches"][0]["creator"]
    assert creator_body["performance_summary"] == "Brief-backed recent performance."
    assert "performance_context" not in creator_body


def _second_creator(session: Session) -> CreatorProfile:
    channel = f"UC{uuid4().hex[:22]}"
    creator = CreatorProfile(
        youtube_channel_id=channel,
        canonical_url=f"https://www.youtube.com/channel/{channel}",
        sort_name="Second Creator",
        current_facts={"title": "Second Creator"},
        analysis={},
        brief=_creator_brief(),
        source_status={"youtube": "current", "freshness": "current"},
        last_analyzed_at=NOW,
        next_analysis_at=NOW + timedelta(days=14),
    )
    session.add(creator)
    session.flush()
    return creator


def _add_checkpoint_chain(
    session: Session, task: MatchTask, creator: CreatorProfile, *, order: int
) -> None:
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
    session.add(
        MatchPairwiseRecord(
            match_task_id=task.id,
            creator_id=creator.id,
            state=PairwiseState.SUCCEEDED,
            attempt_count=1,
            match_brief=_pairwise(creator.id),
            retryable=False,
            started_at=NOW,
            completed_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()


def test_zero_result_is_explicit_and_zero_selection_creates_one_campaign(
    auth_client: TestClient, session: Session
) -> None:
    game, _ = _profiles(session)
    task = MatchRepository(session, clock=lambda: NOW).create_locked_task(
        game.id, 7, Decimal("0.7000")
    )
    MatchRepository(
        session, clock=lambda: NOW + timedelta(minutes=1)
    ).apply_screening_output(task.id, [])
    MatchRepository(
        session, clock=lambda: NOW + timedelta(minutes=2)
    ).apply_screening_output(task.id, [])
    body = auth_client.get(f"/api/v1/matches/{task.id}").json()
    assert body["status"] == "succeeded"
    assert body["result_state"] == "no_suitable_creators"
    assert body["recommended_matches"] == []
    assert body["other_matches"] == []
    assert (
        session.scalar(
            select(func.count())
            .select_from(OutreachCampaign)
            .where(OutreachCampaign.match_task_id == task.id)
        )
        == 1
    )


def test_running_or_failed_detail_never_exposes_partial_results(
    auth_client: TestClient, session: Session
) -> None:
    game, _ = _profiles(session)
    for status in (MatchStatus.RUNNING, MatchStatus.FAILED):
        task = _task(session, game, status=status, stage=MatchStage.PAIRWISE)
        body = auth_client.get(f"/api/v1/matches/{task.id}").json()
        assert body["recommended_matches"] == []
        assert body["other_matches"] == []


def test_retry_resumes_screening_pairwise_and_ranking_checkpoints(
    auth_client: TestClient, session: Session, match_dispatcher
) -> None:
    game, creator = _profiles(session)
    for index, stage in enumerate(
        (MatchStage.SCREENING, MatchStage.PAIRWISE, MatchStage.RANKING)
    ):
        task = _task(session, game, status=MatchStatus.FAILED, stage=stage)
        if stage is not MatchStage.SCREENING:
            _add_checkpoint_chain(
                session,
                task,
                creator if index == 1 else _second_creator(session),
                order=index,
            )
            task.total_units = 3
            task.completed_units = 1 if stage is MatchStage.PAIRWISE else 2
            if stage is MatchStage.RANKING:
                task.ranking_enqueued_at = NOW
        response = auth_client.post(
            f"/api/v1/matches/{task.id}/retry",
            headers={"Idempotency-Key": f"retry-stage-{index}"},
        )
        assert response.status_code == 202
        assert response.json()["id"] == str(task.id)
        session.refresh(task)
        assert task.status is MatchStatus.RUNNING
        expected = (
            FINALIZE_MATCH_TASK_NAME
            if stage is MatchStage.RANKING
            else START_MATCH_TASK_NAME
        )
        assert match_dispatcher.calls[-1] == (expected, task.id)


@pytest.mark.parametrize(
    ("pair_retryability", "expected_status"),
    [((False, True), 409), ((True, True), 202)],
    ids=["mixed-permanence", "all-retryable"],
)
def test_pairwise_retry_requires_every_failed_checkpoint_to_be_retryable(
    auth_client: TestClient,
    session: Session,
    match_dispatcher,
    pair_retryability: tuple[bool, bool],
    expected_status: int,
) -> None:
    game, first_creator = _profiles(session)
    second_creator = _second_creator(session)
    task = _task(session, game, status=MatchStatus.FAILED, stage=MatchStage.PAIRWISE)
    task.completed_units = 1
    task.total_units = 4
    task.error_code = "deepseek_unavailable"
    task.error_message = "Match is temporarily unavailable. Please retry."
    task.retryable = True
    for order, (creator, retryable) in enumerate(
        zip((first_creator, second_creator), pair_retryability, strict=True)
    ):
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
        session.add(
            MatchPairwiseRecord(
                match_task_id=task.id,
                creator_id=creator.id,
                state=PairwiseState.FAILED,
                attempt_count=1,
                error_code=(
                    "deepseek_unavailable" if retryable else "deepseek_input_invalid"
                ),
                error_message=(
                    "Match is temporarily unavailable. Please retry."
                    if retryable
                    else "Match could not be completed. Please retry."
                ),
                retryable=retryable,
                started_at=NOW,
                completed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    session.flush()
    assert auth_client.get(f"/api/v1/matches/{task.id}").json()["retryable"] is True

    response = auth_client.post(
        f"/api/v1/matches/{task.id}/retry",
        headers={"Idempotency-Key": f"retry-mixed-{task.id}"},
    )

    assert response.status_code == expected_status
    session.refresh(task)
    if expected_status == 409:
        assert response.json()["error"]["code"] == "match_not_retryable"
        assert task.status is MatchStatus.FAILED
        assert match_dispatcher.calls == []
    else:
        assert task.status is MatchStatus.RUNNING
        assert match_dispatcher.calls == [(START_MATCH_TASK_NAME, task.id)]


def test_expired_retry_atomically_supersedes_and_replays_one_new_task(
    auth_client: TestClient, session: Session, match_dispatcher
) -> None:
    game, _ = _profiles(session)
    old = _task(session, game, status=MatchStatus.FAILED, expires_at=NOW)
    response = auth_client.post(
        f"/api/v1/matches/{old.id}/retry",
        headers={"Idempotency-Key": "retry-expired"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["id"] != str(old.id)
    assert body["supersedes_id"] == str(old.id)
    session.refresh(old)
    assert old.status is MatchStatus.SUPERSEDED
    assert old.error_code == "deepseek_unavailable"
    replay = auth_client.post(
        f"/api/v1/matches/{old.id}/retry",
        headers={"Idempotency-Key": "retry-expired-other-key"},
    )
    assert replay.status_code == 202
    assert replay.json()["id"] == body["id"]
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatchTask)
            .where(MatchTask.supersedes_id == old.id)
        )
        == 1
    )
    assert len(match_dispatcher.calls) == 1


def test_expired_retry_rolls_back_supersession_when_current_game_is_unusable(
    auth_client: TestClient, session: Session
) -> None:
    game, _ = _profiles(session)
    old = _task(session, game, status=MatchStatus.FAILED, expires_at=NOW)
    game.brief = {"invalid": "current brief"}
    response = auth_client.post(
        f"/api/v1/matches/{old.id}/retry",
        headers={"Idempotency-Key": "retry-expired-invalid"},
    )
    assert response.status_code == 409
    session.refresh(old)
    assert old.status is MatchStatus.FAILED
    assert old.retryable is True
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatchTask)
            .where(MatchTask.supersedes_id == old.id)
        )
        == 0
    )


class _AllowAll:
    def allow(self, _workspace: str, _address: str) -> bool:
        return True


class _ConcurrentDispatcher:
    def __init__(self) -> None:
        from threading import Lock

        self.lock = Lock()
        self.calls: list[tuple[str, UUID]] = []

    def dispatch(self, task_name: str, task_id: UUID) -> None:
        with self.lock:
            self.calls.append((task_name, task_id))


class _BlockingFailureDispatcher:
    def __init__(self) -> None:
        self.called = Event()
        self.failure_released = Event()

    def dispatch(self, _task_name: str, _task_id: UUID) -> None:
        self.called.set()
        if not self.failure_released.wait(timeout=10):
            raise AssertionError("dispatcher failure was not released")
        raise RuntimeError("broker unavailable")


def _committing_factory(engine: Engine):
    @contextmanager
    def factory():
        with Session(engine) as value:
            try:
                yield value
            except Exception:
                value.rollback()
                raise

    return factory


def _concurrent_client(engine: Engine, workspace_key: str, dispatcher):
    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_key),
        rate_limiter=_AllowAll(),
        secret_cipher=SecretCipher(bytes(range(32))),
        job_session_factory=_committing_factory(engine),
        match_dispatcher=dispatcher,
        match_clock=lambda: NOW,
        match_seed_factory=lambda: 77,
    )
    return TestClient(app, headers={"Authorization": f"Bearer {workspace_key}"})


def _committed_retryable_pair(
    engine: Engine,
) -> tuple[UUID, UUID, UUID]:
    with Session(engine) as setup:
        game, creator = _profiles(setup)
        task = _task(
            setup,
            game,
            status=MatchStatus.FAILED,
            stage=MatchStage.PAIRWISE,
        )
        task.total_units = 3
        task.completed_units = 1
        task.error_code = "deepseek_unavailable"
        task.error_message = "Match is temporarily unavailable. Please retry."
        setup.add(
            MatchScreeningRecord(
                match_task_id=task.id,
                creator_id=creator.id,
                screening_order=0,
                locked_creator_brief=_creator_brief(),
                selected=True,
                expires_at=task.input_expires_at,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        setup.flush()
        setup.add(
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
        setup.flush()
        setup.add(
            MatchPairwiseRecord(
                match_task_id=task.id,
                creator_id=creator.id,
                state=PairwiseState.FAILED,
                attempt_count=1,
                error_code=task.error_code,
                error_message=task.error_message,
                retryable=True,
                started_at=NOW,
                completed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        setup.commit()
        return task.id, game.id, creator.id


def _match_task_row_lock(statement: str) -> bool:
    normalized = " ".join(statement.casefold().split())
    return "from match_tasks" in normalized and "for update" in normalized


def _cleanup_committed_match(
    engine: Engine,
    *,
    task_id: UUID,
    game_id: UUID,
    creator_id: UUID,
    idempotency_key: str,
) -> None:
    with Session(engine) as value, value.begin():
        value.query(IdempotencyRecord).filter_by(key=idempotency_key).delete()
        value.query(MatchTask).filter_by(id=task_id).delete()
        value.query(CreatorProfile).filter_by(id=creator_id).delete()
        value.query(GameProfile).filter_by(id=game_id).delete()


def test_late_pair_success_and_retry_share_row_then_feed_lock_order(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
    request,
) -> None:
    task_id, game_id, creator_id = _committed_retryable_pair(database_engine)
    idempotency_key = f"retry-lock-order-{task_id}"
    request.addfinalizer(
        lambda: _cleanup_committed_match(
            database_engine,
            task_id=task_id,
            game_id=game_id,
            creator_id=creator_id,
            idempotency_key=idempotency_key,
        )
    )
    worker_has_row = Event()
    retry_attempted_row = Event()
    release_worker = Event()

    def after_cursor_execute(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if (
            _connection.info.get("lock_order_actor") == "worker"
            and _match_task_row_lock(statement)
            and not worker_has_row.is_set()
        ):
            worker_has_row.set()
            assert release_worker.wait(timeout=10)

    def before_cursor_execute(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if (
            worker_has_row.is_set()
            and _connection.info.get("lock_order_actor") != "worker"
            and _match_task_row_lock(statement)
        ):
            retry_attempted_row.set()

    event.listen(database_engine, "after_cursor_execute", after_cursor_execute)
    event.listen(database_engine, "before_cursor_execute", before_cursor_execute)
    request.addfinalizer(
        lambda: event.remove(
            database_engine, "before_cursor_execute", before_cursor_execute
        )
    )
    request.addfinalizer(
        lambda: event.remove(
            database_engine, "after_cursor_execute", after_cursor_execute
        )
    )
    dispatcher = _ConcurrentDispatcher()

    def late_success():
        try:
            with Session(database_engine) as value, value.begin():
                connection = value.connection()
                connection.info["lock_order_actor"] = "worker"
                try:
                    return SQLPairwiseRepository(
                        value, clock=lambda: NOW
                    ).apply_success(
                        task_id,
                        creator_id,
                        PairwiseMatchBrief.model_validate(
                            {**_pairwise(creator_id), "creator_id": creator_id}
                        ),
                    )
                finally:
                    connection.info.pop("lock_order_actor", None)
        except Exception as error:
            return error

    def retry():
        try:
            with _concurrent_client(
                database_engine, workspace_access_key, dispatcher
            ) as client:
                return client.post(
                    f"/api/v1/matches/{task_id}/retry",
                    headers={"Idempotency-Key": idempotency_key},
                )
        except Exception as error:
            return error

    try:
        with (
            ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="late-worker"
            ) as worker_pool,
            ThreadPoolExecutor(max_workers=1) as api_pool,
        ):
            worker_result = worker_pool.submit(late_success)
            if not worker_has_row.wait(timeout=5):
                pytest.fail(
                    f"worker did not lock Match row: {worker_result.result()!r}"
                )
            retry_result = api_pool.submit(retry)
            assert retry_attempted_row.wait(timeout=5)
            release_worker.set()
            worker_value = worker_result.result(timeout=10)
            retry_value = retry_result.result(timeout=10)
    finally:
        release_worker.set()

    assert not isinstance(worker_value, Exception)
    assert not isinstance(retry_value, Exception)
    assert retry_value.status_code == 409
    assert retry_value.json()["error"]["code"] == "match_not_retryable"
    assert dispatcher.calls == []
    with Session(database_engine) as verify:
        task = verify.get(MatchTask, task_id)
        pair = verify.scalar(
            select(MatchPairwiseRecord).where(
                MatchPairwiseRecord.match_task_id == task_id,
                MatchPairwiseRecord.creator_id == creator_id,
            )
        )
        assert task is not None and task.status is MatchStatus.RUNNING
        assert pair is not None and pair.state is PairwiseState.SUCCEEDED


def test_queue_compensation_and_late_pair_success_use_the_same_lock_order(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
    request,
) -> None:
    task_id, game_id, creator_id = _committed_retryable_pair(database_engine)
    idempotency_key = f"queue-lock-order-{task_id}"
    request.addfinalizer(
        lambda: _cleanup_committed_match(
            database_engine,
            task_id=task_id,
            game_id=game_id,
            creator_id=creator_id,
            idempotency_key=idempotency_key,
        )
    )
    dispatcher = _BlockingFailureDispatcher()
    worker_has_row = Event()
    compensation_attempted_row = Event()
    release_worker = Event()

    def after_cursor_execute(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if (
            _connection.info.get("lock_order_actor") == "worker"
            and _match_task_row_lock(statement)
            and not worker_has_row.is_set()
        ):
            worker_has_row.set()
            assert release_worker.wait(timeout=10)

    def before_cursor_execute(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if dispatcher.failure_released.is_set() and _match_task_row_lock(statement):
            compensation_attempted_row.set()

    event.listen(database_engine, "after_cursor_execute", after_cursor_execute)
    event.listen(database_engine, "before_cursor_execute", before_cursor_execute)
    request.addfinalizer(
        lambda: event.remove(
            database_engine, "before_cursor_execute", before_cursor_execute
        )
    )
    request.addfinalizer(
        lambda: event.remove(
            database_engine, "after_cursor_execute", after_cursor_execute
        )
    )

    def late_success():
        try:
            with Session(database_engine) as value, value.begin():
                connection = value.connection()
                connection.info["lock_order_actor"] = "worker"
                try:
                    return SQLPairwiseRepository(
                        value, clock=lambda: NOW
                    ).apply_success(
                        task_id,
                        creator_id,
                        PairwiseMatchBrief.model_validate(
                            {**_pairwise(creator_id), "creator_id": creator_id}
                        ),
                    )
                finally:
                    connection.info.pop("lock_order_actor", None)
        except Exception as error:
            return error

    def retry():
        try:
            with _concurrent_client(
                database_engine, workspace_access_key, dispatcher
            ) as client:
                return client.post(
                    f"/api/v1/matches/{task_id}/retry",
                    headers={"Idempotency-Key": idempotency_key},
                )
        except Exception as error:
            return error

    try:
        with (
            ThreadPoolExecutor(max_workers=1) as api_pool,
            ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="queue-worker"
            ) as worker_pool,
        ):
            retry_result = api_pool.submit(retry)
            assert dispatcher.called.wait(timeout=5)
            worker_result = worker_pool.submit(late_success)
            if not worker_has_row.wait(timeout=5):
                pytest.fail(
                    f"worker did not lock Match row: {worker_result.result()!r}"
                )
            dispatcher.failure_released.set()
            assert compensation_attempted_row.wait(timeout=5)
            release_worker.set()
            worker_value = worker_result.result(timeout=10)
            retry_value = retry_result.result(timeout=10)
    finally:
        dispatcher.failure_released.set()
        release_worker.set()

    assert not isinstance(worker_value, Exception)
    assert not isinstance(retry_value, Exception)
    assert retry_value.status_code == 202
    body = retry_value.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "match_queue_unavailable"
    with Session(database_engine) as verify:
        task = verify.get(MatchTask, task_id)
        pair = verify.scalar(
            select(MatchPairwiseRecord).where(
                MatchPairwiseRecord.match_task_id == task_id,
                MatchPairwiseRecord.creator_id == creator_id,
            )
        )
        assert task is not None and task.status is MatchStatus.FAILED
        assert pair is not None and pair.state is PairwiseState.SUCCEEDED


def test_concurrent_same_key_unexpired_retries_replay_the_accepted_response(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
    request,
) -> None:
    task_id, game_id, creator_id = _committed_retryable_pair(database_engine)
    idempotency_key = f"retry-same-key-{task_id}"
    request.addfinalizer(
        lambda: _cleanup_committed_match(
            database_engine,
            task_id=task_id,
            game_id=game_id,
            creator_id=creator_id,
            idempotency_key=idempotency_key,
        )
    )
    initial_reads = Barrier(2)
    synchronized_connections: set[int] = set()
    synchronization_lock = Lock()

    def synchronize_initial_idempotency_reads(
        connection, _cursor, statement, parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.casefold().split())
        if (
            "from idempotency_records" not in normalized
            or "for update" not in normalized
            or idempotency_key not in parameters.values()
        ):
            return
        connection_id = id(connection)
        with synchronization_lock:
            if connection_id in synchronized_connections:
                return
            synchronized_connections.add(connection_id)
        initial_reads.wait(timeout=10)

    event.listen(
        database_engine,
        "after_cursor_execute",
        synchronize_initial_idempotency_reads,
    )
    request.addfinalizer(
        lambda: event.remove(
            database_engine,
            "after_cursor_execute",
            synchronize_initial_idempotency_reads,
        )
    )
    dispatcher = _ConcurrentDispatcher()

    def retry():
        try:
            with _concurrent_client(
                database_engine, workspace_access_key, dispatcher
            ) as client:
                response = client.post(
                    f"/api/v1/matches/{task_id}/retry",
                    headers={"Idempotency-Key": idempotency_key},
                )
                return response.status_code, response.json()
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _value: retry(), range(2)))

    assert all(not isinstance(result, Exception) for result in results)
    responses = [result for result in results if not isinstance(result, Exception)]
    assert [status for status, _body in responses] == [202, 202]
    assert responses[0][1] == responses[1][1]
    assert responses[0][1]["id"] == str(task_id)
    assert responses[0][1]["status"] == "running"
    assert dispatcher.calls == [(START_MATCH_TASK_NAME, task_id)]
    with Session(database_engine) as verify:
        assert (
            verify.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.key == idempotency_key)
            )
            == 1
        )
        assert (
            verify.scalar(
                select(func.count())
                .select_from(MatchTask)
                .where(MatchTask.game_id == game_id)
            )
            == 1
        )


def test_concurrent_same_key_creation_commits_one_task_and_dispatch(
    database_engine: Engine, workspace_access_key: str, request
) -> None:
    with Session(database_engine) as setup:
        game, creator = _profiles(setup)
        setup.commit()
        game_id, creator_id = game.id, creator.id

    def cleanup() -> None:
        with Session(database_engine) as value, value.begin():
            value.query(MatchTask).filter_by(game_id=game_id).delete()
            value.query(CreatorProfile).filter_by(id=creator_id).delete()
            value.query(GameProfile).filter_by(id=game_id).delete()

    request.addfinalizer(cleanup)
    dispatcher = _ConcurrentDispatcher()
    key = f"match-concurrent-{game_id}"

    def create() -> tuple[int, str]:
        with _concurrent_client(
            database_engine, workspace_access_key, dispatcher
        ) as client:
            response = client.post(
                "/api/v1/matches",
                headers={"Idempotency-Key": key},
                json={"game_id": str(game_id)},
            )
            return response.status_code, response.json()["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _value: create(), range(2)))
    assert {status for status, _task_id in results} == {202}
    assert len({_task_id for _status, _task_id in results}) == 1
    assert len(dispatcher.calls) == 1
    with Session(database_engine) as verify:
        assert (
            verify.scalar(
                select(func.count())
                .select_from(MatchTask)
                .where(MatchTask.game_id == game_id)
            )
            == 1
        )


def test_concurrent_expired_retry_keys_converge_on_one_successor(
    database_engine: Engine, workspace_access_key: str, request
) -> None:
    with Session(database_engine) as setup:
        game, creator = _profiles(setup)
        old = _task(
            setup,
            game,
            status=MatchStatus.FAILED,
            expires_at=NOW,
        )
        setup.commit()
        old_id, game_id, creator_id = old.id, game.id, creator.id

    def cleanup() -> None:
        with Session(database_engine) as value, value.begin():
            value.query(MatchTask).filter_by(game_id=game_id).delete()
            value.query(CreatorProfile).filter_by(id=creator_id).delete()
            value.query(GameProfile).filter_by(id=game_id).delete()

    request.addfinalizer(cleanup)
    dispatcher = _ConcurrentDispatcher()
    keys = (f"retry-race-one-{old_id}", f"retry-race-two-{old_id}")

    def retry(key: str) -> tuple[int, str]:
        with _concurrent_client(
            database_engine, workspace_access_key, dispatcher
        ) as client:
            response = client.post(
                f"/api/v1/matches/{old_id}/retry",
                headers={"Idempotency-Key": key},
            )
            return response.status_code, response.json()["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(retry, keys))
    assert {status for status, _task_id in results} == {202}
    assert len({_task_id for _status, _task_id in results}) == 1
    assert len(dispatcher.calls) == 1
    with Session(database_engine) as verify:
        assert (
            verify.scalar(
                select(func.count())
                .select_from(MatchTask)
                .where(MatchTask.supersedes_id == old_id)
            )
            == 1
        )


def test_retry_missing_or_ineligible_is_safe_conflict(
    auth_client: TestClient, session: Session
) -> None:
    missing = auth_client.post(
        f"/api/v1/matches/{uuid4()}/retry",
        headers={"Idempotency-Key": "retry-missing"},
    )
    assert missing.status_code == 404
    game, _ = _profiles(session)
    succeeded = _task(session, game, status=MatchStatus.SUCCEEDED)
    conflict = auth_client.post(
        f"/api/v1/matches/{succeeded.id}/retry",
        headers={"Idempotency-Key": "retry-succeeded"},
    )
    assert conflict.status_code == 409


def test_unified_jobs_feed_orders_equal_timestamps_by_kind_and_id_and_scopes_status(
    auth_client: TestClient, session: Session
) -> None:
    from app.db.models.enums import JobMode, JobStatus, TargetType
    from app.db.models.jobs import AnalysisJob

    game, _ = _profiles(session)
    analysis = AnalysisJob(
        target_type=TargetType.GAME,
        canonical_target_id=game.steam_app_id,
        canonical_url=game.canonical_url,
        mode=JobMode.CREATE,
        status=JobStatus.QUEUED,
        created_at=NOW,
        updated_at=NOW,
    )
    match = _task(session, game, created_at=NOW)
    session.add(analysis)
    session.flush()
    session.execute(
        update(AnalysisJob).where(AnalysisJob.id == analysis.id).values(updated_at=NOW)
    )
    session.execute(
        update(MatchTask).where(MatchTask.id == match.id).values(updated_at=NOW)
    )
    session.flush()
    response = auth_client.get("/api/v1/jobs", params={"limit": 1})
    assert response.status_code == 200
    first = response.json()
    assert first["items"][0]["kind"] == "analysis"
    assert first["items"][0]["resource_id"] == str(analysis.id)
    second = auth_client.get(
        "/api/v1/jobs", params={"limit": 1, "changed_after": first["cursor"]}
    )
    assert second.json()["items"][0]["kind"] == "match"
    assert second.json()["items"][0]["resource_id"] == str(match.id)
    mismatch = auth_client.get(
        "/api/v1/jobs", params={"changed_after": first["cursor"], "status": "queued"}
    )
    assert mismatch.status_code == 400
    superseded = auth_client.get("/api/v1/jobs", params={"status": "superseded"})
    assert superseded.status_code == 200
    decoded = json.loads(
        base64.urlsafe_b64decode(first["cursor"] + "=" * (-len(first["cursor"]) % 4))
    )
    assert decoded["key"][1] == "analysis"


def test_match_response_models_reject_unknown_fields_and_unknown_failure_is_generic(
    auth_client: TestClient, session: Session
) -> None:
    game, _ = _profiles(session)
    task = _task(session, game, status=MatchStatus.FAILED)
    task.error_code = "private_database_text"
    task.error_message = "postgres password secret"
    body = auth_client.get(f"/api/v1/matches/{task.id}").json()
    assert body["error"] == {
        "code": "match_internal_error",
        "message": "Match failed unexpectedly. Please retry.",
    }
    assert "postgres" not in json.dumps(body)
    assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) >= 0
