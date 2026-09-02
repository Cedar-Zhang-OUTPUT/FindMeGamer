from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
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
from app.db.models.profiles import CreatorProfile, GameProfile
from app.matching.pairwise import PairwiseCheckpointError, PairwiseService
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import PairwiseMatchBrief
from app.workers.match_tasks import MatchTaskStore, PairwiseTerminalFailure


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _unavailable(reason: str) -> dict[str, str]:
    return {"status": "unavailable", "reason": reason}


def _game_brief(reason: str = "Locked game.") -> dict[str, object]:
    claim = _unavailable(reason)
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


def _creator_brief(reason: str) -> dict[str, object]:
    claim = _unavailable(reason)
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


def _brief(
    creator_id: UUID, reason: str = "The fit is supported."
) -> PairwiseMatchBrief:
    dimension = {"analysis": reason, "evidence": ["Locked evidence."]}
    return PairwiseMatchBrief.model_validate(
        {
            "english_language_check": True,
            "creator_id": creator_id,
            "content_fit": dimension,
            "audience_fit": dimension,
            "performance_fit": dimension,
            "promotion_fit": dimension,
            "brand_safety": dimension,
            "strengths": ["Content is aligned."],
            "risks": ["Audience is inferred."],
            "evidence": ["Locked evidence."],
            "match_reasons": [reason],
        }
    )


class FakeAI:
    def __init__(self, output: object, before_return=None) -> None:
        self.output = output
        self.before_return = before_return or (lambda: None)
        self.calls = 0

    def complete_structured(self, _model: str, _messages: list, _schema: type):
        self.calls += 1
        self.before_return()
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


def _creator(number: int) -> CreatorProfile:
    channel = f"UC{number:04d}{uuid4().hex[:18]}"
    return CreatorProfile(
        youtube_channel_id=channel,
        canonical_url=f"https://www.youtube.com/channel/{channel}",
        sort_name=f"Creator {number}",
        current_facts={"title": f"Creator {number}", "subscriber_count": 1000},
        analysis={"content_summary": _unavailable(f"Creator {number} analysis")},
        brief=_creator_brief(f"Creator {number} brief"),
        source_status={"youtube": "available", "freshness": "current"},
        last_analyzed_at=NOW,
        next_analysis_at=NOW + timedelta(days=14),
    )


def _task_with_selected(
    session: Session,
    count: int = 2,
) -> tuple[MatchTask, list[CreatorProfile]]:
    game = GameProfile(
        steam_app_id=str(uuid4().int % 10**18),
        canonical_url="https://store.steampowered.com/app/10",
        sort_name="Game",
        current_facts={"name": "Game"},
        analysis={"summary": "Current profile must never be read"},
        brief=_game_brief("Current profile brief must never be read"),
        source_status={"steam": "available"},
        last_analyzed_at=NOW,
        next_analysis_at=NOW + timedelta(days=30),
    )
    creators = [_creator(number + 1) for number in range(count)]
    session.add_all([game, *creators])
    session.flush()
    task = MatchTask(
        game_id=game.id,
        locked_game_brief=_game_brief("TASK-LOCKED-GAME"),
        shuffle_seed=42,
        recommended_match_threshold=Decimal("0.7000"),
        status=MatchStatus.RUNNING,
        stage=MatchStage.PAIRWISE,
        completed_units=1,
        total_units=count + 2,
        result_count=0,
        retryable=False,
        input_expires_at=NOW + timedelta(days=30),
        started_at=NOW,
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
                locked_creator_profile={
                    "id": str(creator.id),
                    "youtube_channel_id": creator.youtube_channel_id,
                    "canonical_url": creator.canonical_url,
                    "current_facts": {
                        "title": creator.sort_name,
                        "subscriber_count": 777,
                    },
                    "analysis": {
                        "content_summary": _unavailable("TASK-LOCKED-CREATOR")
                    },
                    "brief": creator.brief,
                },
                input_model_metadata={},
                input_prompt_metadata={},
                expires_at=task.input_expires_at,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    session.flush()
    return task, creators


@contextmanager
def _session_factory_for(test_session: Session):
    nested = Session(
        bind=test_session.get_bind(), join_transaction_mode="create_savepoint"
    )
    try:
        yield nested
    finally:
        nested.close()


def _store(session: Session) -> MatchTaskStore:
    return MatchTaskStore(
        session_factory=lambda: _session_factory_for(session), clock=lambda: NOW
    )


def _service(session: Session, ai: FakeAI) -> PairwiseService:
    return PairwiseService(
        session_factory=lambda: _session_factory_for(session),
        ai=ai,
        clock=lambda: NOW,
    )


def test_prepare_is_selected_only_unique_and_resumes_only_incomplete_pairs(
    session: Session,
) -> None:
    task, creators = _task_with_selected(session, 3)
    unselected = _creator(99)
    session.add(unselected)
    session.flush()
    session.add(
        MatchScreeningRecord(
            match_task_id=task.id,
            creator_id=unselected.id,
            screening_order=9,
            locked_creator_brief=unselected.brief,
            selected=False,
            expires_at=task.input_expires_at,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()

    incomplete = _store(session).prepare(task.id, [item.id for item in creators])
    assert incomplete == [item.id for item in creators]
    rows = session.scalars(
        select(MatchPairwiseRecord)
        .where(MatchPairwiseRecord.match_task_id == task.id)
        .order_by(MatchPairwiseRecord.creator_id)
    ).all()
    assert {row.creator_id for row in rows} == {item.id for item in creators}
    assert all(row.state is PairwiseState.QUEUED for row in rows)

    by_creator = {row.creator_id: row for row in rows}
    by_creator[creators[0].id].state = PairwiseState.RUNNING
    by_creator[creators[0].id].attempt_count = 1
    by_creator[creators[0].id].started_at = NOW
    by_creator[creators[1].id].state = PairwiseState.SUCCEEDED
    by_creator[creators[1].id].attempt_count = 1
    by_creator[creators[1].id].started_at = NOW
    by_creator[creators[1].id].completed_at = NOW
    by_creator[creators[1].id].match_brief = _brief(creators[1].id).model_dump(
        mode="json"
    )
    by_creator[creators[2].id].state = PairwiseState.FAILED
    by_creator[creators[2].id].attempt_count = 1
    by_creator[creators[2].id].started_at = NOW
    by_creator[creators[2].id].completed_at = NOW
    by_creator[creators[2].id].error_code = "deepseek_unavailable"
    by_creator[creators[2].id].error_message = (
        "Match is temporarily unavailable. Please retry."
    )
    by_creator[creators[2].id].retryable = True
    session.flush()
    resumed = _store(session).prepare(task.id, [item.id for item in creators])
    assert resumed == [creators[0].id, creators[2].id]

    with pytest.raises(PairwiseCheckpointError):
        _store(session).prepare(task.id, [creators[0].id, unselected.id])
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatchPairwiseRecord)
            .where(MatchPairwiseRecord.match_task_id == task.id)
        )
        == 3
    )


def test_claim_and_apply_use_short_transactions_and_locked_snapshot_only(
    session: Session,
) -> None:
    task, creators = _task_with_selected(session, 1)
    creator = creators[0]
    _store(session).prepare(task.id, [creator.id])
    opened_sessions: list[Session] = []

    @contextmanager
    def tracked_session_factory():
        nested = Session(
            bind=session.get_bind(), join_transaction_mode="create_savepoint"
        )
        opened_sessions.append(nested)
        try:
            yield nested
        finally:
            nested.close()

    checked_no_transaction: list[bool] = []
    ai = FakeAI(
        _brief(creator.id),
        before_return=lambda: checked_no_transaction.append(
            all(not item.in_transaction() for item in opened_sessions)
        ),
    )

    service = PairwiseService(
        session_factory=tracked_session_factory,
        ai=ai,
        clock=lambda: NOW,
    )
    assert service.run(task.id, creator.id) == _brief(creator.id)
    assert checked_no_transaction == [True]
    session.expire_all()
    row = session.scalar(
        select(MatchPairwiseRecord).where(
            MatchPairwiseRecord.match_task_id == task.id,
            MatchPairwiseRecord.creator_id == creator.id,
        )
    )
    assert row is not None
    assert row.state is PairwiseState.SUCCEEDED
    assert row.attempt_count == 1
    assert row.started_at == row.completed_at == NOW
    assert row.match_brief == _brief(creator.id).model_dump(mode="json")
    saved_task = session.get(MatchTask, task.id)
    assert saved_task is not None
    assert saved_task.completed_units == 2
    assert saved_task.stage is MatchStage.PAIRWISE

    creator.analysis = {"content_summary": _unavailable("CURRENT-DRIFT")}
    creator.current_facts = {"subscriber_count": 999999}
    session.flush()
    second_ai = FakeAI(AssertionError("completed checkpoint must skip AI"))
    assert _service(session, second_ai).run(task.id, creator.id) == _brief(creator.id)
    assert second_ai.calls == 0


def test_failure_never_overwrites_success_and_preserves_successful_sibling(
    session: Session,
) -> None:
    task, creators = _task_with_selected(session, 2)
    _store(session).prepare(task.id, [item.id for item in creators])
    assert _service(session, FakeAI(_brief(creators[0].id))).run(
        task.id, creators[0].id
    ) == _brief(creators[0].id)

    failure = PairwiseTerminalFailure(
        code="deepseek_unavailable",
        message="Match is temporarily unavailable. Please retry.",
        retryable=True,
    )
    assert _store(session).fail_pair(task.id, creators[1].id, failure) is True
    assert _store(session).fail_pair(task.id, creators[0].id, failure) is False

    session.expire_all()
    rows = {
        row.creator_id: row
        for row in session.scalars(
            select(MatchPairwiseRecord).where(
                MatchPairwiseRecord.match_task_id == task.id
            )
        )
    }
    assert rows[creators[0].id].state is PairwiseState.SUCCEEDED
    assert rows[creators[0].id].match_brief == _brief(creators[0].id).model_dump(
        mode="json"
    )
    assert rows[creators[1].id].state is PairwiseState.FAILED
    assert rows[creators[1].id].match_brief is None
    saved_task = session.get(MatchTask, task.id)
    assert saved_task is not None
    assert saved_task.status is MatchStatus.FAILED
    assert saved_task.completed_at == NOW
    assert saved_task.result_count == 0
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatchResultItem)
            .where(MatchResultItem.match_task_id == task.id)
        )
        == 0
    )


@pytest.mark.parametrize(
    "state", [PairwiseState.QUEUED, PairwiseState.RUNNING, PairwiseState.FAILED]
)
def test_advance_requires_exact_complete_success_set(
    session: Session, state: PairwiseState
) -> None:
    task, creators = _task_with_selected(session, 2)
    _store(session).prepare(task.id, [item.id for item in creators])
    rows = session.scalars(
        select(MatchPairwiseRecord).where(MatchPairwiseRecord.match_task_id == task.id)
    ).all()
    for row in rows:
        row.state = PairwiseState.SUCCEEDED
        row.attempt_count = 1
        row.started_at = NOW
        row.completed_at = NOW
        row.match_brief = _brief(row.creator_id).model_dump(mode="json")
    target = rows[-1]
    target.state = state
    target.match_brief = None
    target.completed_at = NOW if state is PairwiseState.FAILED else None
    if state is PairwiseState.QUEUED:
        target.attempt_count = 0
        target.started_at = None
    if state is PairwiseState.FAILED:
        target.error_code = "deepseek_unavailable"
        target.error_message = "Match is temporarily unavailable. Please retry."
        target.retryable = True
    session.flush()

    assert _store(session).mark_ranking_enqueued(task.id) is False
    session.expire_all()
    saved = session.get(MatchTask, task.id)
    assert saved is not None
    assert saved.ranking_enqueued_at is None
    assert saved.stage is MatchStage.PAIRWISE


def test_missing_or_extra_checkpoint_never_advances(session: Session) -> None:
    task, creators = _task_with_selected(session, 2)
    _store(session).prepare(task.id, [item.id for item in creators])
    rows = session.scalars(
        select(MatchPairwiseRecord).where(MatchPairwiseRecord.match_task_id == task.id)
    ).all()
    session.delete(rows[-1])
    session.flush()
    assert _store(session).mark_ranking_enqueued(task.id) is False


def test_two_sessions_advance_once_with_transaction_scoped_advisory_lock(
    database_engine: Engine,
    request: pytest.FixtureRequest,
) -> None:
    with Session(database_engine) as setup:
        task, creators = _task_with_selected(setup, 2)
        setup.commit()
        task_id = task.id
        game_id = task.game_id
        creator_ids = [creator.id for creator in creators]

    def cleanup() -> None:
        with Session(database_engine) as cleanup_session:
            saved = cleanup_session.get(MatchTask, task_id)
            if saved is not None:
                cleanup_session.delete(saved)
                cleanup_session.flush()
            cleanup_session.execute(
                delete(CreatorProfile).where(CreatorProfile.id.in_(creator_ids))
            )
            cleanup_session.execute(
                delete(GameProfile).where(GameProfile.id == game_id)
            )
            cleanup_session.commit()

    request.addfinalizer(cleanup)
    session_factory = sessionmaker_for(database_engine)
    store = MatchTaskStore(session_factory=session_factory, clock=lambda: NOW)
    store.prepare(task_id, creator_ids)
    for creator_id in creator_ids:
        PairwiseService(
            session_factory=session_factory,
            ai=FakeAI(_brief(creator_id)),
            clock=lambda: NOW,
        ).run(task_id, creator_id)
    barrier = threading.Barrier(2)

    def advance() -> bool:
        store = MatchTaskStore(
            session_factory=session_factory,
            clock=lambda: NOW,
            before_readiness_check=barrier.wait,
        )
        return store.mark_ranking_enqueued(task_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _value: advance(), range(2)))
    assert sorted(results) == [False, True]

    with session_factory() as first:
        first.begin()
        key = MatchTaskStore.advisory_key(task_id)
        first.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        with session_factory() as second:
            assert (
                second.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}
                )
                is False
            )
        first.commit()
    with session_factory() as second:
        assert (
            second.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
            is True
        )
        second.commit()

    with session_factory() as verify:
        saved = verify.get(MatchTask, task_id)
        assert saved is not None
        assert saved.stage is MatchStage.RANKING
        assert saved.completed_units == saved.total_units - 1 == len(creator_ids) + 1
        assert saved.ranking_enqueued_at == NOW


def test_synchronous_broker_failure_compensates_marker_for_retry(
    session: Session,
) -> None:
    task, creators = _task_with_selected(session, 1)
    _store(session).prepare(task.id, [creators[0].id])
    _service(session, FakeAI(_brief(creators[0].id))).run(task.id, creators[0].id)
    store = _store(session)
    assert store.mark_ranking_enqueued(task.id) is True
    assert store.compensate_ranking_enqueue(task.id) is True
    session.expire_all()
    saved = session.get(MatchTask, task.id)
    assert saved is not None
    assert saved.stage is MatchStage.PAIRWISE
    assert saved.ranking_enqueued_at is None
    assert store.mark_ranking_enqueued(task.id) is True


def sessionmaker_for(bind):

    @contextmanager
    def factory():
        value = Session(bind=bind)
        try:
            yield value
            value.commit()
        except Exception:
            value.rollback()
            raise
        finally:
            value.close()

    return factory
