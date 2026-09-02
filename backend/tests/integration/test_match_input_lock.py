from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.prompts.common import parse_prompt_payload
from app.db.models.match import (
    MatchCandidateInput,
    MatchScreeningRecord,
    MatchStage,
    MatchStatus,
    MatchTask,
)
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.repositories.match import MatchInputError, MatchRepository
from app.matching.screening import InvalidScreeningOutput, ScreeningService
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import ScreeningOutput, ScreeningSelection


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
THRESHOLD = Decimal("0.7000")


def _unavailable(reason: str) -> dict[str, str]:
    return {"status": "unavailable", "reason": reason}


def _game_brief(reason: str = "Original locked game brief.") -> dict[str, object]:
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


def _game(*, brief: dict[str, object] | None = None) -> GameProfile:
    return GameProfile(
        steam_app_id=str(uuid4().int % 10**20),
        canonical_url="https://store.steampowered.com/app/10",
        sort_name="Locked Game",
        current_facts={"name": "Locked Game"},
        analysis={"summary": "Game analysis"},
        brief=brief if brief is not None else _game_brief(),
        source_status={"steam": "available"},
        model_metadata={"synthesis_model": "game-model-original"},
        prompt_metadata={"synthesis_prompt_version": "game-prompt-original"},
        last_analyzed_at=NOW - timedelta(days=2),
        next_analysis_at=NOW + timedelta(days=28),
    )


def _creator(
    number: int,
    *,
    analyzed_at: datetime | None = None,
    source_status: dict[str, object] | None = None,
    brief: dict[str, object] | None = None,
    favorite: bool = False,
) -> CreatorProfile:
    channel_id = f"UC{number:022d}"
    return CreatorProfile(
        youtube_channel_id=channel_id,
        canonical_url=f"https://www.youtube.com/channel/{channel_id}",
        sort_name=f"Creator {number:03d}",
        current_facts={
            "title": f"Creator {number:03d}",
            "subscriber_count": number * 100,
        },
        analysis={"content_summary": {"status": "unavailable", "reason": "n/a"}},
        brief=(
            brief if brief is not None else _creator_brief(f"Creator {number} brief.")
        ),
        source_status=(
            source_status
            if source_status is not None
            else {"youtube": "available", "freshness": "current"}
        ),
        model_metadata={"synthesis_model": f"creator-model-{number}"},
        prompt_metadata={"synthesis_prompt_version": f"creator-prompt-{number}"},
        favorite=favorite,
        manual_notes=f"manual-note-{number}",
        last_analyzed_at=(
            analyzed_at if analyzed_at is not None else NOW - timedelta(days=1)
        ),
        next_analysis_at=NOW + timedelta(days=13),
    )


@contextmanager
def _session_factory_for(test_session: Session):
    nested = Session(
        bind=test_session.get_bind(), join_transaction_mode="create_savepoint"
    )
    try:
        yield nested
    finally:
        nested.close()


class FakeAI:
    def __init__(self, output: object, *, before_return=None) -> None:
        self.output = output
        self.before_return = before_return or (lambda: None)
        self.calls: list[tuple[str, list, type]] = []

    def complete_structured(self, model: str, messages: list, schema: type) -> object:
        self.calls.append((model, messages, schema))
        self.before_return()
        return self.output


def _selection(creator_id: UUID, reason: str = "Plausible fit.") -> dict[str, object]:
    return {
        "creator_id": creator_id,
        "screening_reason": reason,
        "evidence": ["The immutable compact brief supports selection."],
    }


def _output(*creator_ids: UUID) -> ScreeningOutput:
    return ScreeningOutput.model_validate(
        {
            "english_language_check": True,
            "selected": [_selection(value) for value in creator_ids],
        }
    )


def _create_task(
    session: Session,
    game_id: UUID,
    *,
    seed: int = 42,
) -> MatchTask:
    repository = MatchRepository(session, clock=lambda: NOW)
    task = repository.create_locked_task(game_id, seed, THRESHOLD)
    session.flush()
    return task


def _service(session: Session, ai: FakeAI) -> ScreeningService:
    return ScreeningService(
        session_factory=lambda: _session_factory_for(session),
        ai=ai,
        clock=lambda: NOW,
    )


def test_creation_atomically_locks_all_100_eligible_inputs_with_exact_expiry_and_neutrality(
    session: Session,
) -> None:
    game = _game()
    eligible = [
        _creator(
            number,
            analyzed_at=(NOW - timedelta(days=30) if number == 0 else None),
            favorite=number % 2 == 0,
        )
        for number in range(100)
    ]
    never_analyzed = _creator(204)
    never_analyzed.last_analyzed_at = None
    excluded = [
        _creator(
            200,
            analyzed_at=NOW - timedelta(days=30, microseconds=1),
        ),
        _creator(
            201,
            source_status={"youtube": "stale", "freshness": "stale"},
        ),
        _creator(
            202,
            analyzed_at=None,
            source_status={"seed": "incomplete"},
            brief={},
        ),
        _creator(203, brief={"invalid": "brief"}),
        never_analyzed,
        _creator(
            205,
            source_status={"youtube": "current", "freshness": "stale"},
        ),
    ]
    eligible[0].current_facts["private_context"] = {
        "contact_email": "nested-contact@example.invalid",
        "next_analysis_at": "SCHEDULE-CANARY",
        "subscriber_count": 999,
    }
    eligible[0].analysis["internal_context"] = {
        "prior_outreach": "OUTREACH-CANARY",
        "response_state": "RESPONSE-CANARY",
        "api_secret": "SECRET-CANARY",
    }
    eligible[0].model_metadata["api_secret"] = "MODEL-SECRET-CANARY"
    eligible[0].prompt_metadata["scheduling_hint"] = "PROMPT-SCHEDULE-CANARY"
    session.add_all([game, *eligible, *excluded])
    session.flush()
    session.add(
        CreatorContact(
            creator_id=eligible[0].id,
            email="private-contact@example.invalid",
            source_type="manual",
            is_manual=True,
            validation_state="valid",
            priority=100,
            is_active=True,
        )
    )
    session.flush()

    first = _create_task(session, game.id, seed=111)
    second = _create_task(session, game.id, seed=111)
    third = _create_task(session, game.id, seed=222)

    first_records = session.scalars(
        select(MatchScreeningRecord)
        .where(MatchScreeningRecord.match_task_id == first.id)
        .order_by(MatchScreeningRecord.screening_order)
    ).all()
    second_records = session.scalars(
        select(MatchScreeningRecord)
        .where(MatchScreeningRecord.match_task_id == second.id)
        .order_by(MatchScreeningRecord.screening_order)
    ).all()
    third_records = session.scalars(
        select(MatchScreeningRecord)
        .where(MatchScreeningRecord.match_task_id == third.id)
        .order_by(MatchScreeningRecord.screening_order)
    ).all()
    candidates = session.scalars(
        select(MatchCandidateInput).where(MatchCandidateInput.match_task_id == first.id)
    ).all()

    assert len(first_records) == len(candidates) == 100
    assert {row.creator_id for row in first_records} == {row.id for row in eligible}
    assert {row.creator_id for row in first_records}.isdisjoint(
        {row.id for row in excluded}
    )
    assert [row.creator_id for row in first_records] == [
        row.creator_id for row in second_records
    ]
    assert [row.creator_id for row in first_records] != [
        row.creator_id for row in third_records
    ]
    assert [row.screening_order for row in first_records] == list(range(100))
    assert first.created_at == NOW
    assert first.input_expires_at == NOW + timedelta(days=30)
    assert first.recommended_match_threshold == THRESHOLD
    assert first.locked_game_brief == _game_brief()
    assert all(row.expires_at == NOW + timedelta(days=30) for row in first_records)
    assert all(row.expires_at == NOW + timedelta(days=30) for row in candidates)

    by_creator = {row.creator_id: row for row in candidates}
    snapshot = by_creator[eligible[0].id].locked_creator_profile
    assert snapshot["id"] == str(eligible[0].id)
    assert snapshot["youtube_channel_id"] == eligible[0].youtube_channel_id
    assert snapshot["canonical_url"] == eligible[0].canonical_url
    assert snapshot["brief"] == eligible[0].brief
    assert snapshot["current_facts"]["title"] == "Creator 000"
    assert snapshot["current_facts"]["private_context"] == {"subscriber_count": 999}
    assert snapshot["analysis"]["content_summary"] == {
        "status": "unavailable",
        "reason": "n/a",
    }
    assert snapshot["analysis"]["internal_context"] == {}
    serialized = json.dumps(
        {
            "snapshot": snapshot,
            "model_metadata": by_creator[eligible[0].id].input_model_metadata,
            "prompt_metadata": by_creator[eligible[0].id].input_prompt_metadata,
        },
        sort_keys=True,
    )
    assert "private-contact@example.invalid" not in serialized
    assert "manual-note" not in serialized
    assert "favorite" not in snapshot
    assert "next_analysis_at" not in snapshot
    assert "CANARY" not in serialized
    assert by_creator[eligible[0].id].input_model_metadata == {
        "synthesis_model": "creator-model-0"
    }
    assert by_creator[eligible[0].id].input_prompt_metadata == {
        "synthesis_prompt_version": "creator-prompt-0"
    }


@pytest.mark.parametrize("invalid_kind", ["missing", "invalid-brief"])
def test_missing_or_invalid_game_rolls_back_without_partial_task(
    session: Session,
    invalid_kind: str,
) -> None:
    game_id = uuid4()
    if invalid_kind == "invalid-brief":
        game = _game(brief={"invalid": "brief"})
        session.add(game)
        session.flush()
        game_id = game.id
    before = session.scalar(select(func.count()).select_from(MatchTask))

    with pytest.raises(MatchInputError):
        with session.begin_nested():
            _create_task(session, game_id)

    assert session.scalar(select(func.count()).select_from(MatchTask)) == before


def test_reanalysis_after_creation_cannot_change_prompt_or_selected_snapshot(
    session: Session,
) -> None:
    game = _game()
    creators = [_creator(301), _creator(302)]
    session.add_all([game, *creators])
    session.flush()
    task = _create_task(session, game.id, seed=5)
    original_game_brief = task.locked_game_brief
    original_by_id = {
        row.creator_id: (
            row.locked_creator_profile,
            row.input_model_metadata,
            row.input_prompt_metadata,
        )
        for row in session.scalars(
            select(MatchCandidateInput).where(
                MatchCandidateInput.match_task_id == task.id
            )
        )
    }
    ordered_ids = list(
        session.scalars(
            select(MatchScreeningRecord.creator_id)
            .where(MatchScreeningRecord.match_task_id == task.id)
            .order_by(MatchScreeningRecord.screening_order)
        )
    )
    selected_id = ordered_ids[-1]

    game.brief = _game_brief("New game brief must not leak.")
    for creator in creators:
        creator.current_facts = {"title": "Concurrent replacement"}
        creator.analysis = {"replacement": True}
        creator.brief = _creator_brief("New creator brief must not leak.")
        creator.model_metadata = {"synthesis_model": "new-model"}
        creator.prompt_metadata = {"synthesis_prompt_version": "new-prompt"}
    session.flush()
    ai = FakeAI(_output(selected_id))

    assert _service(session, ai).run(task.id) == [selected_id]

    payload = parse_prompt_payload(ai.calls[0][1])
    assert payload["game_brief"] == original_game_brief
    assert [item["creator_id"] for item in payload["creators"]] == [
        str(value) for value in ordered_ids
    ]
    assert [item["creator_brief"] for item in payload["creators"]] == [
        original_by_id[value][0]["brief"] for value in ordered_ids
    ]
    retained = session.scalar(
        select(MatchCandidateInput).where(
            MatchCandidateInput.match_task_id == task.id,
            MatchCandidateInput.creator_id == selected_id,
        )
    )
    assert retained is not None
    assert retained.locked_creator_profile == original_by_id[selected_id][0]
    assert retained.input_model_metadata == original_by_id[selected_id][1]
    assert retained.input_prompt_metadata == original_by_id[selected_id][2]
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatchCandidateInput)
            .where(MatchCandidateInput.match_task_id == task.id)
        )
        == 1
    )


@pytest.mark.parametrize("case", ["unknown", "duplicate", "over-thirty"])
def test_invalid_bypassed_output_is_all_or_nothing(
    session: Session,
    case: str,
) -> None:
    game = _game()
    creators = [_creator(400 + number) for number in range(31)]
    session.add_all([game, *creators])
    session.flush()
    task = _create_task(session, game.id)
    if case == "unknown":
        selections = (ScreeningSelection.model_construct(**_selection(uuid4())),)
    elif case == "duplicate":
        selections = (
            ScreeningSelection.model_construct(**_selection(creators[0].id)),
            ScreeningSelection.model_construct(**_selection(creators[0].id)),
        )
    else:
        selections = tuple(
            ScreeningSelection.model_construct(**_selection(creator.id))
            for creator in creators
        )
    output = ScreeningOutput.model_construct(
        english_language_check=True,
        selected=selections,
    )

    with pytest.raises(InvalidScreeningOutput):
        _service(session, FakeAI(output)).run(task.id)

    session.expire_all()
    records = session.scalars(
        select(MatchScreeningRecord).where(
            MatchScreeningRecord.match_task_id == task.id
        )
    ).all()
    saved_task = session.get(MatchTask, task.id)
    assert saved_task is not None
    assert saved_task.status is MatchStatus.RUNNING
    assert saved_task.stage is MatchStage.SCREENING
    assert all(not row.selected and row.screening_reason is None for row in records)
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatchCandidateInput)
            .where(MatchCandidateInput.match_task_id == task.id)
        )
        == 31
    )


def test_selection_application_is_selected_only_atomic_and_idempotent(
    session: Session,
) -> None:
    game = _game()
    creators = [_creator(501), _creator(502), _creator(503)]
    session.add_all([game, *creators])
    session.flush()
    task = _create_task(session, game.id, seed=17)
    ordered_ids = list(
        session.scalars(
            select(MatchScreeningRecord.creator_id)
            .where(MatchScreeningRecord.match_task_id == task.id)
            .order_by(MatchScreeningRecord.screening_order)
        )
    )
    output = ScreeningOutput.model_validate(
        {
            "english_language_check": True,
            "selected": [
                _selection(ordered_ids[2], "Third in locked order."),
                _selection(ordered_ids[0], "First in locked order."),
            ],
        }
    )
    first_ai = FakeAI(output)

    assert _service(session, first_ai).run(task.id) == [ordered_ids[0], ordered_ids[2]]
    second_ai = FakeAI(AssertionError("AI must not run after atomic application"))
    assert _service(session, second_ai).run(task.id) == [
        ordered_ids[0],
        ordered_ids[2],
    ]

    session.expire_all()
    saved = session.get(MatchTask, task.id)
    assert saved is not None
    assert saved.status is MatchStatus.RUNNING
    assert saved.stage is MatchStage.PAIRWISE
    assert saved.started_at == NOW
    assert saved.completed_units == 1
    assert saved.total_units == 4
    assert saved.completed_at is None
    records = session.scalars(
        select(MatchScreeningRecord)
        .where(MatchScreeningRecord.match_task_id == task.id)
        .order_by(MatchScreeningRecord.screening_order)
    ).all()
    selected_records = [row for row in records if row.selected]
    assert [row.creator_id for row in selected_records] == [
        ordered_ids[0],
        ordered_ids[2],
    ]
    persisted_decisions = {
        row.creator_id: json.loads(row.screening_reason) for row in selected_records
    }
    assert persisted_decisions[ordered_ids[0]]["reason"] == "First in locked order."
    assert persisted_decisions[ordered_ids[2]]["evidence"] == [
        "The immutable compact brief supports selection."
    ]
    assert set(
        session.scalars(
            select(MatchCandidateInput.creator_id).where(
                MatchCandidateInput.match_task_id == task.id
            )
        )
    ) == {ordered_ids[0], ordered_ids[2]}
    assert len(first_ai.calls) == 1
    assert second_ai.calls == []


def test_zero_selected_and_zero_eligible_complete_atomically_without_ai_or_candidates(
    session: Session,
) -> None:
    game_with_creator = _game()
    game_without_creator = _game()
    creator = _creator(601)
    session.add_all([game_with_creator, creator])
    session.flush()
    selected_zero_task = _create_task(session, game_with_creator.id)
    zero_ai = FakeAI(_output())

    assert _service(session, zero_ai).run(selected_zero_task.id) == []
    assert (
        _service(session, FakeAI(AssertionError("must be idempotent"))).run(
            selected_zero_task.id
        )
        == []
    )

    creator.source_status = {"youtube": "stale", "freshness": "stale"}
    session.add(game_without_creator)
    session.flush()
    eligible_zero_task = _create_task(session, game_without_creator.id)
    no_ai = FakeAI(AssertionError("zero eligible must skip AI"))
    assert _service(session, no_ai).run(eligible_zero_task.id) == []

    session.expire_all()
    for task_id in (selected_zero_task.id, eligible_zero_task.id):
        saved = session.get(MatchTask, task_id)
        assert saved is not None
        assert saved.status is MatchStatus.SUCCEEDED
        assert saved.stage is MatchStage.SCREENING
        assert saved.completed_units == saved.total_units == 1
        assert saved.result_count == 0
        assert saved.started_at == saved.completed_at == NOW
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatchCandidateInput)
                .where(MatchCandidateInput.match_task_id == task_id)
            )
            == 0
        )
    assert len(zero_ai.calls) == 1
    assert no_ai.calls == []
