"""Isolated Match capacity checks with real persistence and synthetic AI output."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.contracts import Message
from app.db.models.match import (
    MatchPairwiseRecord,
    MatchResultItem,
    MatchScreeningRecord,
    PairwiseState,
)
from app.db.models.profiles import CreatorProfile, GameProfile
from app.integrations.errors import TransientIntegrationError
from app.matching.pairwise import PairwiseService
from app.matching.prompts import build_ranking_prompt
from app.matching.ranking import RankingService
from app.matching.screening import ScreeningService
from app.schemas.ai_match import FinalRankingOutput, PairwiseMatchBrief, ScreeningOutput
from app.workers.match_tasks import (
    FINALIZE_MATCH_TASK_NAME,
    START_MATCH_TASK_NAME,
    MatchTaskExecutor,
    MatchTaskStore,
    finalize_match_ranking,
    get_retry_policy,
)
from tests.helpers.match_capacity import (
    synthetic_creator_brief,
    synthetic_game_brief,
    synthetic_pairwise_brief,
)


@pytest.mark.parametrize("selected_count", [14, 30])
def test_realistic_match_briefs_fit_one_global_ranking_request(
    selected_count: int,
) -> None:
    briefs = [
        synthetic_pairwise_brief(UUID(int=index + 1)) for index in range(selected_count)
    ]
    assert 2_700 <= len(synthetic_creator_brief().model_dump_json()) <= 3_300
    assert all(6_700 <= len(brief.model_dump_json()) <= 7_000 for brief in briefs)

    messages = build_ranking_prompt(briefs, threshold=Decimal("0.7000"))

    assert sum(len(message.content.encode("utf-8")) for message in messages) <= 512_000
    assert all(len(message.content.encode("utf-8")) <= 120_000 for message in messages)
    combined = "\n".join(message.content for message in messages)
    for brief in briefs:
        assert combined.count(str(brief.creator_id)) == 1


def _seed_library(session: Session, count: int) -> tuple[GameProfile, list[UUID]]:
    now = datetime.now(UTC)
    game = GameProfile(
        steam_app_id=str(uuid4().int % 10**16),
        canonical_url="https://store.steampowered.com/app/12345",
        sort_name="Synthetic Cooperative Campaign",
        current_facts={"name": "Synthetic Cooperative Campaign"},
        analysis={},
        brief=synthetic_game_brief().model_dump(mode="json"),
        source_status={"steam": "current"},
        last_analyzed_at=now,
        next_analysis_at=now + timedelta(days=30),
    )
    creators = []
    for index in range(count):
        channel_id = f"UC{uuid4().hex[:22]}"
        creators.append(
            CreatorProfile(
                youtube_channel_id=channel_id,
                canonical_url=f"https://www.youtube.com/channel/{channel_id}",
                sort_name=f"Synthetic Creator {index}",
                current_facts={
                    "title": f"Synthetic Creator {index}",
                    "channel_id": channel_id,
                    "subscriber_count": 12345,
                },
                analysis={
                    "content_summary": {
                        "status": "unavailable",
                        "reason": "Use supplied synthetic brief.",
                    }
                },
                brief=synthetic_creator_brief().model_dump(mode="json"),
                source_status={"youtube": "current", "freshness": "current"},
                last_analyzed_at=now,
                next_analysis_at=now + timedelta(days=14),
            )
        )
    session.add_all([game, *creators])
    session.flush()
    return game, [creator.id for creator in creators]


def _ranking_output(creator_ids: list[UUID]) -> FinalRankingOutput:
    dimensions = {
        "content_fit": "The content supports a cooperative campaign.",
        "audience_fit": "The likely audience has relevant interests.",
        "performance_fit": "Recent activity supports a practical collaboration.",
        "promotion_fit": "The format supports an informative demonstration.",
        "brand_safety": "No concern appears in the supplied evidence.",
    }
    return FinalRankingOutput.model_validate(
        {
            "english_language_check": True,
            "items": [
                {
                    "creator_id": creator_id,
                    "total_score": 0.8 if index % 2 == 0 else 0.4,
                    "dimension_scores": {dimension: 0.6 for dimension in dimensions},
                    "backend_order": index,
                    "result_group": "recommended" if index % 2 == 0 else "other",
                    "qualitative_label": (
                        "Good Match" if index % 2 == 0 else "Limited Match"
                    ),
                    "dimension_outcomes": dimensions,
                    "match_reasons": [
                        "The creator explains cooperative mechanics clearly."
                    ],
                }
                for index, creator_id in enumerate(reversed(creator_ids))
            ],
        }
    )


class CapacityAI:
    """Assert complete inputs at the provider boundary; never use a live model."""

    def __init__(self, creator_ids: list[UUID], selected_count: int) -> None:
        self.creator_ids = creator_ids
        self.selected_ids = creator_ids[:selected_count]
        self.calls: list[tuple[str, type, list[Message]]] = []
        self.fail_ranking = False

    def complete_structured(self, model: str, messages: list[Message], schema: type):
        self.calls.append((model, schema, messages))
        payload = "\n".join(message.content for message in messages)
        if schema is ScreeningOutput:
            assert model == "deepseek-flash"
            assert len(messages) > 2  # All Library candidates span multiple messages.
            for creator_id in self.creator_ids:
                assert payload.count(str(creator_id)) == 1
            return ScreeningOutput.model_validate(
                {
                    "english_language_check": True,
                    "selected": [
                        {
                            "creator_id": creator_id,
                            "screening_reason": "Cooperative coverage fits the campaign.",
                            "evidence": [
                                "The supplied profile discusses cooperative play."
                            ],
                        }
                        for creator_id in self.selected_ids
                    ],
                }
            )
        assert model == "deepseek-flash"
        if schema is PairwiseMatchBrief:
            represented = [item for item in self.creator_ids if str(item) in payload]
            assert len(represented) == 1
            assert represented[0] in self.selected_ids
            return synthetic_pairwise_brief(represented[0])
        assert schema is FinalRankingOutput
        for creator_id in self.selected_ids:
            assert payload.count(str(creator_id)) == 1
        if self.fail_ranking:
            raise TransientIntegrationError("deepseek_unavailable")
        return _ranking_output(self.selected_ids)

    def count(self, schema: type) -> int:
        return sum(call_schema is schema for _, call_schema, _ in self.calls)


class LocalGraphDispatcher:
    def __init__(self) -> None:
        self.pairs: list[tuple[UUID, UUID]] = []
        self.advances: list[UUID] = []
        self.rankings: list[UUID] = []

    def dispatch_pairwise(self, task_id: UUID, creator_id: UUID) -> None:
        self.pairs.append((task_id, creator_id))

    def dispatch_advance(self, task_id: UUID) -> None:
        self.advances.append(task_id)

    def dispatch_ranking(self, task_id: UUID) -> None:
        self.rankings.append(task_id)


def _executor(session: Session, ai: CapacityAI, dispatcher: LocalGraphDispatcher):
    @contextmanager
    def session_factory() -> Iterator[Session]:
        with Session(
            bind=session.get_bind(), join_transaction_mode="create_savepoint"
        ) as nested:
            yield nested

    @contextmanager
    def pairwise_factory() -> Iterator[PairwiseService]:
        yield PairwiseService(session_factory=session_factory, ai=ai)

    @contextmanager
    def ranking_factory() -> Iterator[RankingService]:
        yield RankingService(session_factory=session_factory, ai=ai)

    return MatchTaskExecutor(
        screening=ScreeningService(session_factory=session_factory, ai=ai),
        pairwise_factory=pairwise_factory,
        ranking_factory=ranking_factory,
        store=MatchTaskStore(session_factory=session_factory),
        dispatcher=dispatcher,
    )


def _pair_checkpoints(session: Session, task_id: UUID) -> dict[UUID, tuple]:
    session.expire_all()
    rows = session.scalars(
        select(MatchPairwiseRecord).where(MatchPairwiseRecord.match_task_id == task_id)
    ).all()
    return {
        row.creator_id: (row.state, row.attempt_count, row.match_brief) for row in rows
    }


@pytest.mark.parametrize(
    ("library_count", "selected_count", "fail_ranking_once"),
    [(50, 14, False), (100, 30, False), (100, 30, True)],
    ids=["fifty-to-fourteen", "hundred-to-thirty", "hundred-ranking-retry"],
)
def test_library_to_complete_match_at_capacity(
    auth_client,
    session: Session,
    match_dispatcher,
    monkeypatch,
    library_count: int,
    selected_count: int,
    fail_ranking_once: bool,
) -> None:
    game, creator_ids = _seed_library(session, library_count)
    created = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": f"capacity-create-{uuid4()}"},
        json={"game_id": str(game.id)},
    )
    assert created.status_code == 202, created.text
    task_id = UUID(created.json()["id"])
    assert match_dispatcher.calls == [(START_MATCH_TASK_NAME, task_id)]
    frozen_ids = session.scalars(
        select(MatchScreeningRecord.creator_id).where(
            MatchScreeningRecord.match_task_id == task_id
        )
    ).all()
    assert len(frozen_ids) == library_count
    assert set(frozen_ids) == set(creator_ids)

    ai = CapacityAI(creator_ids, selected_count)
    dispatcher = LocalGraphDispatcher()
    executor = _executor(session, ai, dispatcher)
    monkeypatch.setattr("app.workers.match_tasks.get_match_executor", lambda: executor)
    executor.start(task_id)
    assert len(dispatcher.pairs) == selected_count
    assert {creator_id for _, creator_id in dispatcher.pairs} == set(ai.selected_ids)
    while dispatcher.pairs:
        executor.run_pair(*dispatcher.pairs.pop(0))
    while dispatcher.advances:
        executor.advance(dispatcher.advances.pop(0))
    assert dispatcher.rankings == [task_id]
    before_ranking = _pair_checkpoints(session, task_id)
    assert set(before_ranking) == set(ai.selected_ids)
    assert all(
        state is PairwiseState.SUCCEEDED and attempts == 1
        for state, attempts, _ in before_ranking.values()
    )

    ai.fail_ranking = fail_ranking_once
    finalize_match_ranking.apply(
        args=[str(task_id)], retries=get_retry_policy().max_retries, throw=True
    ).get()
    if fail_ranking_once:
        failed = auth_client.get(f"/api/v1/matches/{task_id}").json()
        assert failed["status"] == "failed"
        assert failed["retryable"] is True
        assert failed["recommended_matches"] == failed["other_matches"] == []
        assert _pair_checkpoints(session, task_id) == before_ranking
        retried = auth_client.post(
            f"/api/v1/matches/{task_id}/retry",
            headers={"Idempotency-Key": f"capacity-retry-{uuid4()}"},
        )
        assert retried.status_code == 202, retried.text
        assert retried.json()["id"] == str(task_id)
        assert match_dispatcher.calls == [
            (START_MATCH_TASK_NAME, task_id),
            (FINALIZE_MATCH_TASK_NAME, task_id),
        ]
        ai.fail_ranking = False
        finalize_match_ranking.apply(args=[str(task_id)], throw=True).get()

    response = auth_client.get(f"/api/v1/matches/{task_id}")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["status"] == "succeeded"
    assert detail["result_state"] == "available"
    published = detail["recommended_matches"] + detail["other_matches"]
    assert len(published) == selected_count
    assert {UUID(item["creator"]["id"]) for item in published} == set(ai.selected_ids)
    assert _pair_checkpoints(session, task_id) == before_ranking
    assert ai.count(ScreeningOutput) == 1
    assert ai.count(PairwiseMatchBrief) == selected_count
    assert ai.count(FinalRankingOutput) == (2 if fail_ranking_once else 1)

    # A duplicate finalizer delivery reuses publication, without another model call.
    call_count = len(ai.calls)
    finalize_match_ranking.apply(args=[str(task_id)], throw=True).get()
    assert len(ai.calls) == call_count
    result_ids = session.scalars(
        select(MatchResultItem.creator_id).where(
            MatchResultItem.match_task_id == task_id
        )
    ).all()
    assert len(result_ids) == selected_count
    assert set(result_ids) == set(ai.selected_ids)
