"""One bounded empty-screening recheck, with real persistence and API retry."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.match import (
    MatchCandidateInput,
    MatchPairwiseRecord,
    MatchResultItem,
    MatchScreeningRecord,
    MatchStage,
    MatchStatus,
    MatchTask,
)
from app.db.models.outreach import OutreachCampaign
from app.db.models.profiles import CreatorProfile
from app.schemas.ai_match import ScreeningOutput
from app.workers.match_tasks import (
    START_MATCH_TASK_NAME,
    get_retry_policy,
    start_match_task,
)
from tests.integration.test_match_capacity import (
    CapacityAI,
    LocalGraphDispatcher,
    _executor,
    _seed_library,
)


def _selection(*creator_ids: UUID) -> ScreeningOutput:
    return ScreeningOutput.model_validate(
        {
            "english_language_check": True,
            "selected": [
                {
                    "creator_id": creator_id,
                    "screening_reason": "The supplied cooperative coverage supports a fit.",
                    "evidence": ["The creator discusses cooperative games."],
                }
                for creator_id in creator_ids
            ],
        }
    )


def _snapshot(session: Session, task_id: UUID) -> dict:
    """Exclude task lifecycle fields; decisions and frozen evidence must not change."""
    session.expire_all()
    records = session.scalars(
        select(MatchScreeningRecord).where(
            MatchScreeningRecord.match_task_id == task_id
        )
    ).all()
    candidates = session.scalars(
        select(MatchCandidateInput).where(MatchCandidateInput.match_task_id == task_id)
    ).all()
    return deepcopy(
        {
            "screening": {
                row.creator_id: (
                    row.selected,
                    row.screening_reason,
                    row.locked_creator_brief,
                )
                for row in records
            },
            "candidates": {
                row.creator_id: row.locked_creator_profile for row in candidates
            },
            "pairwise": list(
                session.scalars(
                    select(MatchPairwiseRecord.creator_id).where(
                        MatchPairwiseRecord.match_task_id == task_id
                    )
                )
            ),
            "results": list(
                session.scalars(
                    select(MatchResultItem.creator_id).where(
                        MatchResultItem.match_task_id == task_id
                    )
                )
            ),
            "campaigns": list(
                session.scalars(
                    select(OutreachCampaign.id).where(
                        OutreachCampaign.match_task_id == task_id
                    )
                )
            ),
            "profiles": {
                row.id: (row.current_facts, row.analysis, row.brief)
                for row in session.scalars(select(CreatorProfile))
            },
        }
    )


class RecheckAI(CapacityAI):
    def __init__(self, creator_ids, outputs, before_screening):
        super().__init__(creator_ids, selected_count=1)
        self.outputs = list(outputs)
        self.before_screening = before_screening

    def complete_structured(self, model, messages, schema):
        if schema is not ScreeningOutput:
            return super().complete_structured(model, messages, schema)
        assert model == "deepseek-flash"
        assert self.outputs, "Screening exceeded its one additional recheck."
        self.before_screening()
        self.calls.append((model, schema, messages))
        payload = "\n".join(message.content for message in messages)
        assert all(str(creator_id) in payload for creator_id in self.creator_ids)
        return self.outputs.pop(0)


def _create(auth_client, session):
    game, creator_ids = _seed_library(session, 2)
    response = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": f"recheck-{uuid4()}"},
        json={"game_id": str(game.id)},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"]), creator_ids


def _finish(executor, dispatcher):
    while dispatcher.pairs:
        executor.run_pair(*dispatcher.pairs.pop(0))
    while dispatcher.advances:
        executor.advance(dispatcher.advances.pop(0))
    while dispatcher.rankings:
        executor.finalize(dispatcher.rankings.pop(0))


@pytest.mark.parametrize("supported", [True, False], ids=["supported", "still-empty"])
def test_empty_first_screening_only_applies_valid_recheck(
    auth_client,
    session: Session,
    supported: bool,
):
    task_id, creator_ids = _create(auth_client, session)
    before = _snapshot(session, task_id)

    def assert_unapplied():
        assert _snapshot(session, task_id) == before

    expected_ids = creator_ids[:1] if supported else []
    ai = RecheckAI(
        creator_ids, [_selection(), _selection(*expected_ids)], assert_unapplied
    )
    dispatcher = LocalGraphDispatcher()
    executor = _executor(session, ai, dispatcher)
    executor.start(task_id)

    assert ai.count(ScreeningOutput) == 2
    assert ai.outputs == []
    assert dispatcher.pairs == ([(task_id, expected_ids[0])] if supported else [])
    assert executor.screening.run(task_id) == expected_ids
    assert ai.count(ScreeningOutput) == 2
    applied = _snapshot(session, task_id)
    assert {
        creator_id
        for creator_id, (selected, _, _) in applied["screening"].items()
        if selected
    } == set(expected_ids)
    assert set(applied["candidates"]) == set(expected_ids)
    assert applied["profiles"] == before["profiles"]
    _finish(executor, dispatcher)

    detail = auth_client.get(f"/api/v1/matches/{task_id}").json()
    assert detail["status"] == "succeeded"
    if supported:
        published = detail["recommended_matches"] + detail["other_matches"]
        assert [UUID(item["creator"]["id"]) for item in published] == expected_ids
    else:
        assert detail["result_state"] == "no_suitable_creators"
        assert detail["recommended_matches"] == detail["other_matches"] == []
    assert executor.screening.run(task_id) == expected_ids
    assert ai.count(ScreeningOutput) == 2


@pytest.mark.parametrize("invalid_kind", ["unknown-id", "malformed"])
def test_invalid_empty_recheck_keeps_inputs_and_can_retry_normally(
    auth_client,
    session: Session,
    match_dispatcher,
    monkeypatch,
    invalid_kind: str,
):
    task_id, creator_ids = _create(auth_client, session)
    before = _snapshot(session, task_id)

    def assert_unapplied():
        assert _snapshot(session, task_id) == before

    invalid = (
        _selection(uuid4()) if invalid_kind == "unknown-id" else {"selected": "invalid"}
    )
    ai = RecheckAI(
        creator_ids,
        [_selection(), invalid, _selection(creator_ids[0])],
        assert_unapplied,
    )
    dispatcher = LocalGraphDispatcher()
    executor = _executor(session, ai, dispatcher)
    monkeypatch.setattr("app.workers.match_tasks.get_match_executor", lambda: executor)
    start_match_task.apply(
        args=[str(task_id)],
        retries=get_retry_policy().max_retries,
        throw=True,
    ).get()

    assert ai.count(ScreeningOutput) == 2
    assert _snapshot(session, task_id) == before
    task = session.get(MatchTask, task_id)
    assert task.status is MatchStatus.FAILED
    assert task.stage is MatchStage.SCREENING
    assert task.retryable is True
    assert dispatcher.pairs == dispatcher.advances == dispatcher.rankings == []
    failed = auth_client.get(f"/api/v1/matches/{task_id}").json()
    assert failed["recommended_matches"] == failed["other_matches"] == []

    retried = auth_client.post(
        f"/api/v1/matches/{task_id}/retry",
        headers={"Idempotency-Key": f"recheck-retry-{uuid4()}"},
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["id"] == str(task_id)
    assert match_dispatcher.calls == [
        (START_MATCH_TASK_NAME, task_id),
        (START_MATCH_TASK_NAME, task_id),
    ]
    start_match_task.apply(args=[str(task_id)], throw=True).get()
    assert ai.count(ScreeningOutput) == 3
    assert ai.outputs == []
    assert executor.screening.run(task_id) == [creator_ids[0]]
    assert ai.count(ScreeningOutput) == 3
    _finish(executor, dispatcher)

    detail = auth_client.get(f"/api/v1/matches/{task_id}").json()
    assert detail["status"] == "succeeded"
    published = detail["recommended_matches"] + detail["other_matches"]
    assert [UUID(item["creator"]["id"]) for item in published] == [creator_ids[0]]
    assert _snapshot(session, task_id)["profiles"] == before["profiles"]
