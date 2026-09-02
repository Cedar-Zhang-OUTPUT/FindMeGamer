from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models.match import (
    MatchCandidateInput,
    MatchPairwiseRecord,
    MatchResultItem,
    MatchScreeningRecord,
    MatchStage,
    MatchStatus,
    MatchTask,
    PairwiseState,
)
from app.db.models.outreach import OutreachCampaign
from app.db.models.profiles import CreatorProfile, GameProfile
from app.integrations.errors import InvalidModelOutput
from app.matching.ranking import RankingService, SQLRankingRepository
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import FinalRankingOutput, PairwiseMatchBrief


NOW = datetime(2026, 9, 2, 18, 0, tzinfo=UTC)


def _unavailable(reason: str) -> dict[str, str]:
    return {"status": "unavailable", "reason": reason}


def _game_brief() -> dict[str, object]:
    claim = _unavailable("TASK-GAME")
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


def _creator_brief(marker: str) -> dict[str, object]:
    claim = _unavailable(marker)
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


def _pairwise(creator_id: UUID, marker: str) -> PairwiseMatchBrief:
    dimension = {"analysis": f"{marker} analysis", "evidence": [f"{marker} evidence"]}
    return PairwiseMatchBrief.model_validate(
        {
            "english_language_check": True,
            "creator_id": creator_id,
            "content_fit": dimension,
            "audience_fit": dimension,
            "performance_fit": dimension,
            "promotion_fit": dimension,
            "brand_safety": dimension,
            "strengths": [f"{marker} strength"],
            "risks": [f"{marker} risk"],
            "evidence": [f"{marker} evidence"],
            "match_reasons": [f"{marker} pair reason"],
        }
    )


def _ranking(
    creator_ids: list[UUID], *, reversed_order: bool = False
) -> FinalRankingOutput:
    ids = list(reversed(creator_ids)) if reversed_order else creator_ids
    return FinalRankingOutput.model_validate(
        {
            "english_language_check": True,
            "items": [
                {
                    "creator_id": creator_id,
                    "total_score": 0.80004 if index == 0 else 0.69994,
                    "dimension_scores": {
                        "content_fit": 0.8,
                        "audience_fit": 0.7,
                        "performance_fit": 0.6,
                        "promotion_fit": 0.5,
                        "brand_safety": 0.9,
                    },
                    "backend_order": index,
                    "result_group": "recommended" if index == 0 else "other",
                    "qualitative_label": "Good Match",
                    "dimension_outcomes": {
                        "content_fit": "Content outcome.",
                        "audience_fit": "Audience outcome.",
                        "performance_fit": "Performance outcome.",
                        "promotion_fit": "Promotion outcome.",
                        "brand_safety": "Safety outcome.",
                    },
                    "match_reasons": [f"Final reason {creator_id}."],
                }
                for index, creator_id in enumerate(ids)
            ],
        }
    )


class FakeAI:
    def __init__(self, output: object, before_return=None) -> None:
        self.output = output
        self.before_return = before_return or (lambda: None)
        self.calls = 0
        self.messages: list[list] = []

    def complete_structured(self, _model: str, messages: list, _schema: type):
        self.calls += 1
        self.messages.append(messages)
        self.before_return()
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


def _ready_task(
    session: Session, count: int = 2
) -> tuple[MatchTask, list[CreatorProfile]]:
    game = GameProfile(
        steam_app_id=str(uuid4().int % 10**18),
        canonical_url="https://store.steampowered.com/app/10",
        sort_name="Game",
        current_facts={"name": "Game"},
        analysis={},
        brief=_game_brief(),
        source_status={"steam": "current"},
        last_analyzed_at=NOW,
        next_analysis_at=NOW + timedelta(days=30),
    )
    creators = []
    for index in range(count):
        channel = f"UC{index:04d}{uuid4().hex[:18]}"
        creators.append(
            CreatorProfile(
                youtube_channel_id=channel,
                canonical_url=f"https://www.youtube.com/channel/{channel}",
                sort_name=f"Creator {index}",
                current_facts={"title": f"Current {index}"},
                analysis={},
                brief=_creator_brief(f"CURRENT-{index}"),
                source_status={"youtube": "current"},
                last_analyzed_at=NOW,
                next_analysis_at=NOW + timedelta(days=14),
            )
        )
    session.add_all([game, *creators])
    session.flush()
    task = MatchTask(
        game_id=game.id,
        locked_game_brief=_game_brief(),
        shuffle_seed=42,
        recommended_match_threshold=Decimal("0.7000"),
        status=MatchStatus.RUNNING,
        stage=MatchStage.RANKING,
        completed_units=count + 1,
        total_units=count + 2,
        result_count=0,
        retryable=False,
        input_expires_at=NOW + timedelta(days=30),
        ranking_enqueued_at=NOW,
        started_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(task)
    session.flush()
    for order, creator in enumerate(creators):
        brief = _pairwise(creator.id, f"LOCKED-{order}")
        session.add(
            MatchScreeningRecord(
                match_task_id=task.id,
                creator_id=creator.id,
                screening_order=order,
                locked_creator_brief=creator.brief,
                selected=True,
                screening_reason='{"reason":"selected"}',
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
                match_brief=brief.model_dump(mode="json"),
                retryable=False,
                started_at=NOW,
                completed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    session.flush()
    return task, creators


@contextmanager
def _nested_factory(outer: Session):
    nested = Session(bind=outer.get_bind(), join_transaction_mode="create_savepoint")
    try:
        yield nested
    finally:
        nested.close()


def _service(session: Session, ai: FakeAI, **kwargs) -> RankingService:
    return RankingService(
        session_factory=lambda: _nested_factory(session),
        ai=ai,
        clock=lambda: NOW + timedelta(minutes=1),
        **kwargs,
    )


def test_complete_publication_is_one_transaction_with_exact_persisted_fields(
    session: Session,
) -> None:
    task, creators = _ready_task(session)
    ai = FakeAI(_ranking([creator.id for creator in creators]))
    assert _service(session, ai).run(task.id) == 2
    session.expire_all()
    saved = session.get(MatchTask, task.id)
    rows = session.scalars(
        select(MatchResultItem)
        .where(MatchResultItem.match_task_id == task.id)
        .order_by(MatchResultItem.backend_order)
    ).all()
    campaigns = session.scalars(
        select(OutreachCampaign).where(OutreachCampaign.match_task_id == task.id)
    ).all()
    assert saved is not None
    assert (saved.status, saved.stage, saved.result_count) == (
        MatchStatus.SUCCEEDED,
        MatchStage.RANKING,
        2,
    )
    assert saved.completed_units == saved.total_units == 4
    assert saved.completed_at == NOW + timedelta(minutes=1)
    assert saved.error_code is saved.error_message is None
    assert saved.retryable is False
    assert len(campaigns) == 1
    assert [row.creator_id for row in rows] == [creator.id for creator in creators]
    assert [row.total_score for row in rows] == [Decimal("0.8000"), Decimal("0.6999")]
    assert [row.result_group.value for row in rows] == ["recommended", "other"]
    assert rows[0].match_brief == _pairwise(creators[0].id, "LOCKED-0").model_dump(
        mode="json"
    )
    assert rows[0].match_reasons == [f"Final reason {creators[0].id}."]


def test_invalid_ranking_and_injected_flush_failure_publish_nothing(
    session: Session,
) -> None:
    task, creators = _ready_task(session)
    invalid = _ranking([creator.id for creator in creators]).model_copy(
        update={"items": (_ranking([creator.id for creator in creators]).items[0],)}
    )
    with pytest.raises(InvalidModelOutput):
        _service(session, FakeAI(invalid)).run(task.id)
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatchResultItem)
            .where(MatchResultItem.match_task_id == task.id)
        )
        == 0
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(OutreachCampaign)
            .where(OutreachCampaign.match_task_id == task.id)
        )
        == 0
    )
    assert session.get(MatchTask, task.id).status is MatchStatus.RUNNING

    class ExplodingRepository(SQLRankingRepository):
        def _before_final_flush(self) -> None:
            raise RuntimeError("injected publication failure")

    with pytest.raises(RuntimeError, match="injected publication failure"):
        _service(
            session,
            FakeAI(_ranking([creator.id for creator in creators])),
            repository_factory=lambda value: ExplodingRepository(
                value, clock=lambda: NOW + timedelta(minutes=1)
            ),
        ).run(task.id)
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatchResultItem)
            .where(MatchResultItem.match_task_id == task.id)
        )
        == 0
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(OutreachCampaign)
            .where(OutreachCampaign.match_task_id == task.id)
        )
        == 0
    )
    assert session.get(MatchTask, task.id).status is MatchStatus.RUNNING


def test_repeated_success_skips_ai_and_does_not_duplicate_or_replace(
    session: Session,
) -> None:
    task, creators = _ready_task(session)
    first = FakeAI(_ranking([creator.id for creator in creators]))
    service = _service(session, first)
    assert service.run(task.id) == 2
    original = [
        (row.creator_id, row.backend_order, row.match_brief, row.total_score)
        for row in session.scalars(
            select(MatchResultItem)
            .where(MatchResultItem.match_task_id == task.id)
            .order_by(MatchResultItem.backend_order)
        )
    ]
    second = FakeAI(AssertionError("AI must not run"))
    assert _service(session, second).run(task.id) == 2
    assert second.calls == 0
    assert original == [
        (row.creator_id, row.backend_order, row.match_brief, row.total_score)
        for row in session.scalars(
            select(MatchResultItem)
            .where(MatchResultItem.match_task_id == task.id)
            .order_by(MatchResultItem.backend_order)
        )
    ]
    assert (
        session.scalar(
            select(func.count())
            .select_from(OutreachCampaign)
            .where(OutreachCampaign.match_task_id == task.id)
        )
        == 1
    )


def test_current_profile_mutation_during_ai_does_not_change_prompt_or_publication(
    session: Session,
) -> None:
    task, creators = _ready_task(session)

    def mutate() -> None:
        creators[0].current_facts = {
            "contact_email": "drift@example.invalid",
            "score": 999,
        }
        creators[0].brief = _creator_brief("CURRENT-DRIFT")
        session.flush()

    ai = FakeAI(_ranking([creator.id for creator in creators]), before_return=mutate)
    assert _service(session, ai).run(task.id) == 2
    assert "CURRENT-DRIFT" not in str(ai.messages)
    assert "drift@example.invalid" not in str(ai.messages)
    rows = session.scalars(
        select(MatchResultItem)
        .where(MatchResultItem.match_task_id == task.id)
        .order_by(MatchResultItem.backend_order)
    ).all()
    assert "LOCKED-0" in str(rows[0].match_brief)


def _committing_factory(engine: Engine):
    @contextmanager
    def factory():
        with Session(engine) as value:
            try:
                yield value
                value.commit()
            except Exception:
                value.rollback()
                raise

    return factory


def test_two_publishers_keep_first_committed_result_byte_for_byte(
    database_engine: Engine, request: pytest.FixtureRequest
) -> None:
    with Session(database_engine) as setup:
        task, creators = _ready_task(setup)
        setup.commit()
        task_id, game_id = task.id, task.game_id
        creator_ids = [creator.id for creator in creators]

    def cleanup() -> None:
        with Session(database_engine) as cleanup_session:
            cleanup_session.execute(delete(MatchTask).where(MatchTask.id == task_id))
            cleanup_session.execute(
                delete(CreatorProfile).where(CreatorProfile.id.in_(creator_ids))
            )
            cleanup_session.execute(
                delete(GameProfile).where(GameProfile.id == game_id)
            )
            cleanup_session.commit()

    request.addfinalizer(cleanup)

    barrier = threading.Barrier(2)
    first_output = _ranking(creator_ids)
    second_output = _ranking(creator_ids, reversed_order=True)
    factory = _committing_factory(database_engine)

    def run(output: FinalRankingOutput) -> int:
        return RankingService(
            session_factory=factory,
            ai=FakeAI(output, before_return=barrier.wait),
            clock=lambda: NOW + timedelta(minutes=1),
        ).run(task_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(run, (first_output, second_output)))
    assert counts == [2, 2]
    with Session(database_engine) as verify:
        rows = verify.scalars(
            select(MatchResultItem)
            .where(MatchResultItem.match_task_id == task_id)
            .order_by(MatchResultItem.backend_order)
        ).all()
        actual = [
            (row.creator_id, row.backend_order, row.total_score, row.match_reasons)
            for row in rows
        ]
        valid_first = [
            (creator_ids[0], 0, Decimal("0.8000"), [f"Final reason {creator_ids[0]}."]),
            (creator_ids[1], 1, Decimal("0.6999"), [f"Final reason {creator_ids[1]}."]),
        ]
        valid_second = [
            (creator_ids[1], 0, Decimal("0.8000"), [f"Final reason {creator_ids[1]}."]),
            (creator_ids[0], 1, Decimal("0.6999"), [f"Final reason {creator_ids[0]}."]),
        ]
        assert actual in (valid_first, valid_second)
        assert (
            verify.scalar(
                select(func.count())
                .select_from(OutreachCampaign)
                .where(OutreachCampaign.match_task_id == task_id)
            )
            == 1
        )
