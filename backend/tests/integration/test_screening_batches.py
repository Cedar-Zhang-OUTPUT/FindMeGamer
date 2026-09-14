"""Real API/database/worker graph for large-library screening and retry."""

from uuid import UUID, uuid4
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models.match import (
    MatchCandidateInput,
    MatchScreeningCheckpoint,
    MatchScreeningRecord,
)
from app.integrations.errors import TransientIntegrationError
from app.schemas.ai_match import ScreeningOutput
from app.workers.match_tasks import get_retry_policy, start_match_task
from tests.integration.test_match_capacity import (
    CapacityAI,
    LocalGraphDispatcher,
    _executor,
    _seed_library,
)
from tests.unit.matching.test_screening_batch_calls import BoundedAI


class LargeLibraryAI(CapacityAI):
    def __init__(self, ids, fail_call=None):
        super().__init__(ids, selected_count=0)
        self.screen = BoundedAI(fail_call)

    def complete_structured(self, model, messages, schema):
        if schema is ScreeningOutput:
            try:
                return self.screen.complete_structured(model, messages, schema)
            except RuntimeError:
                raise TransientIntegrationError("deepseek_unavailable") from None
        return super().complete_structured(model, messages, schema)


def test_1200_library_api_retry_preserves_batches_and_finishes_existing_graph(
    auth_client,
    session,
    monkeypatch,
):
    game, ids = _seed_library(session, 1200)
    response = auth_client.post(
        "/api/v1/matches",
        json={"game_id": str(game.id)},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    task_id = UUID(response.json()["id"])
    first = LargeLibraryAI(ids, fail_call=2)
    first_executor = _executor(session, first, LocalGraphDispatcher())
    monkeypatch.setattr(
        "app.workers.match_tasks.get_match_executor", lambda: first_executor
    )
    start_match_task.apply(
        args=[str(task_id)], retries=get_retry_policy().max_retries, throw=True
    ).get()
    detail = auth_client.get(f"/api/v1/matches/{task_id}").json()
    assert detail["status"] == "failed" and detail["retryable"]
    checkpoints = list(
        session.scalars(
            select(MatchScreeningCheckpoint).where(
                MatchScreeningCheckpoint.match_task_id == task_id
            )
        )
    )
    assert len(checkpoints) == 1
    saved = checkpoints[0].selections.copy()
    assert (
        len(
            list(
                session.scalars(
                    select(MatchCandidateInput).where(
                        MatchCandidateInput.match_task_id == task_id
                    )
                )
            )
        )
        == 1200
    )
    assert not any(
        session.scalars(
            select(MatchScreeningRecord.selected).where(
                MatchScreeningRecord.match_task_id == task_id
            )
        )
    )

    response = auth_client.post(
        f"/api/v1/matches/{task_id}/retry", headers={"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 202 and response.json()["id"] == str(task_id)
    resumed, dispatcher = LargeLibraryAI(ids), LocalGraphDispatcher()
    executor = _executor(session, resumed, dispatcher)
    executor.start(task_id)
    successful_leaf_ids = first.screen.requests[0][1] + [
        identifier
        for leaf, batch in resumed.screen.requests
        if leaf
        for identifier in batch
    ]
    assert len(successful_leaf_ids) == len(set(successful_leaf_ids)) == 1200
    assert set(successful_leaf_ids) == set(ids)
    assert 0 < len(dispatcher.pairs) <= 30
    session.expire_all()
    assert (
        session.get(
            MatchScreeningCheckpoint, (task_id, checkpoints[0].request_hash)
        ).selections
        == saved
    )

    resumed.selected_ids = [creator_id for _, creator_id in dispatcher.pairs]
    while dispatcher.pairs:
        executor.run_pair(*dispatcher.pairs.pop(0))
    while dispatcher.advances:
        executor.advance(dispatcher.advances.pop(0))
    assert dispatcher.rankings == [task_id]
    executor.finalize(task_id)
    detail = auth_client.get(f"/api/v1/matches/{task_id}").json()
    assert detail["status"] == "succeeded"
    published = detail["recommended_matches"] + detail["other_matches"]
    assert {UUID(item["creator"]["id"]) for item in published} == set(
        resumed.selected_ids
    )
    calls = len(resumed.screen.requests)
    executor.start(task_id)
    assert len(resumed.screen.requests) == calls
    from app.matching.retention import purge_expired_match_inputs

    purge_expired_match_inputs(
        datetime.now(UTC) + timedelta(days=31), database_session=session
    )
    assert (
        list(
            session.scalars(
                select(MatchScreeningCheckpoint).where(
                    MatchScreeningCheckpoint.match_task_id == task_id
                )
            )
        )
        == []
    )
