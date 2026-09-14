"""Large libraries must use independent bounded calls, with durable replay."""

from dataclasses import replace
import json
from uuid import UUID

import pytest

from app.matching.screening import LockedScreeningCreator, LockedScreeningInput
from app.schemas.ai_match import ScreeningOutput
from tests.helpers.match_capacity import synthetic_creator_brief, synthetic_game_brief
from tests.unit.matching.test_screening import (
    FakeRepository,
    TASK_ID,
    _output,
    _service,
)


def payload(messages):
    result = {}
    for message in messages[1:]:
        if "```json\n" not in message.content:
            continue
        part = json.loads(
            message.content.split("```json\n", 1)[1].removesuffix("\n```")
        )
        for key, value in part.items():
            if isinstance(value, list):
                result.setdefault(key, []).extend(value)
            else:
                result[key] = value
    return result


class CheckpointRepository(FakeRepository):
    def __init__(self, locked):
        super().__init__(locked)
        self.checkpoints = {}

    def load_locked_screening_input(self, task_id):
        locked = super().load_locked_screening_input(task_id)
        if self.checkpoints:
            return replace(locked, checkpoints=self.checkpoints.copy())
        return locked

    def save_screening_checkpoint(self, task_id, key, selections):
        self.checkpoints.setdefault(key, tuple(selections))
        return self.checkpoints[key]


def repository(count):
    return CheckpointRepository(
        LockedScreeningInput(
            TASK_ID,
            synthetic_game_brief(),
            tuple(
                LockedScreeningCreator(UUID(int=i + 1), synthetic_creator_brief())
                for i in range(count)
            ),
            None,
        )
    )


class BoundedAI:
    def __init__(self, fail_call=None):
        self.requests = []
        self.fail_call = fail_call

    def complete_structured(self, model, messages, schema):
        assert model == "deepseek-flash" and schema is ScreeningOutput
        assert sum(len(m.content.encode()) for m in messages) <= 400_000
        data = payload(messages)
        entries = data.get("creators", data.get("screening_summaries", []))
        assert 1 <= len(entries) <= 100
        ids = [UUID(item["creator_id"]) for item in entries]
        self.requests.append(("creators" in data, ids))
        if len(self.requests) == self.fail_call:
            raise RuntimeError("synthetic provider unavailable")
        limit = data.get("selection_limit", 30)
        return _output(*ids[-limit:])


def test_1200_creators_all_reach_independent_calls_then_reduce_to_thirty():
    repo, ai = repository(1200), BoundedAI()
    selected = _service(repo, ai).run(TASK_ID)
    leaf_ids = [identifier for leaf, ids in ai.requests if leaf for identifier in ids]
    assert leaf_ids == [UUID(int=i + 1) for i in range(1200)]
    assert len([1 for leaf, _ in ai.requests if leaf]) == 12
    assert any(not leaf for leaf, _ in ai.requests)
    assert len(selected) <= 30
    assert UUID(int=1200) in selected  # End of Library was not silently dropped.


def test_retry_reuses_successful_batches_after_service_recreation():
    repo, ai = repository(250), BoundedAI(fail_call=2)
    with pytest.raises(RuntimeError, match="synthetic provider"):
        _service(repo, ai).run(TASK_ID)
    assert len(repo.checkpoints) == 1
    assert repo.applied is None
    resumed = BoundedAI()
    selected = _service(repo, resumed).run(TASK_ID)
    assert resumed.requests[0][1][0] == UUID(int=101)
    assert not any(leaf and UUID(int=1) in ids for leaf, ids in resumed.requests)
    assert selected


def test_byte_limit_splits_large_manual_context_before_count_limit():
    repo = repository(100)
    repo.locked_input = replace(
        repo.locked_input,
        creators=tuple(
            replace(
                c,
                manual_context={"overrides": {"analysis.content_summary": "a" * 8000}},
            )
            for c in repo.locked_input.creators
        ),
    )
    ai = BoundedAI()
    _service(repo, ai).run(TASK_ID)
    assert len([1 for leaf, _ in ai.requests if leaf]) > 1
    assert sum(len(ids) for leaf, ids in ai.requests if leaf) == 100


def test_reduction_retry_does_not_repeat_leaf_or_completed_reduction_calls():
    repo, ai = repository(1200), BoundedAI(fail_call=14)
    with pytest.raises(RuntimeError, match="synthetic provider"):
        _service(repo, ai).run(TASK_ID)
    assert len(repo.checkpoints) == 13
    resumed = BoundedAI()
    assert _service(repo, resumed).run(TASK_ID)
    assert all(not leaf for leaf, _ in resumed.requests)
    assert resumed.requests[0] == ai.requests[-1]
    assert ai.requests[12] not in resumed.requests
