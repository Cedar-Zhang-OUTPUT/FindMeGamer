import random
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.analysis.prompts.common import parse_prompt_payload
from app.matching.screening import (
    InvalidScreeningOutput,
    LockedScreeningInput,
    LockedScreeningCreator,
    ScreeningService,
)
from app.repositories.match import stable_shuffled_creator_ids
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import ScreeningOutput, ScreeningSelection


TASK_ID = UUID("10000000-0000-4000-8000-000000000001")
CREATOR_A = UUID("20000000-0000-4000-8000-000000000001")
CREATOR_B = UUID("20000000-0000-4000-8000-000000000002")
UNKNOWN_CREATOR = UUID("20000000-0000-4000-8000-000000000099")


def _unavailable(reason: str = "No supplied evidence.") -> dict[str, str]:
    return {"status": "unavailable", "reason": reason}


def _game_brief(reason: str = "Locked game evidence.") -> GameBrief:
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
    )


def _creator_brief(reason: str) -> CreatorBrief:
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
    )


def _selection(creator_id: UUID, reason: str = "Plausible fit.") -> ScreeningSelection:
    return ScreeningSelection.model_validate(
        {
            "creator_id": creator_id,
            "screening_reason": reason,
            "evidence": ["The locked compact brief supports this decision."],
        }
    )


def _output(*creator_ids: UUID) -> ScreeningOutput:
    return ScreeningOutput.model_validate(
        {
            "english_language_check": True,
            "selected": [_selection(value).model_dump() for value in creator_ids],
        }
    )


class FakeAI:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[tuple[str, list, type]] = []

    def complete_structured(self, model: str, messages: list, schema: type) -> object:
        self.calls.append((model, messages, schema))
        return self.output


class FakeRepository:
    def __init__(self, locked_input: LockedScreeningInput) -> None:
        self.locked_input = locked_input
        self.applied: list[ScreeningSelection] | None = None

    def load_locked_screening_input(self, match_task_id: UUID) -> LockedScreeningInput:
        assert match_task_id == TASK_ID
        return self.locked_input

    def apply_screening_output(
        self,
        match_task_id: UUID,
        selections: tuple[ScreeningSelection, ...],
    ) -> list[UUID]:
        assert match_task_id == TASK_ID
        self.applied = list(selections)
        order = {
            item.creator_id: index
            for index, item in enumerate(self.locked_input.creators)
        }
        return sorted((item.creator_id for item in selections), key=order.__getitem__)


class FakeSession:
    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _locked_input(
    *, applied_creator_ids: tuple[UUID, ...] | None = None
) -> LockedScreeningInput:
    return LockedScreeningInput(
        task_id=TASK_ID,
        game_brief=_game_brief(),
        creators=(
            LockedScreeningCreator(CREATOR_B, _creator_brief("Creator B locked.")),
            LockedScreeningCreator(CREATOR_A, _creator_brief("Creator A locked.")),
        ),
        applied_creator_ids=applied_creator_ids,
    )


def _service(repository: FakeRepository, ai: FakeAI) -> ScreeningService:
    return ScreeningService(
        session_factory=lambda: FakeSession(),
        ai=ai,
        repository_factory=lambda _session: repository,
    )


def test_stable_shuffle_is_repeatable_seeded_and_does_not_touch_global_rng() -> None:
    creator_ids = [UUID(f"30000000-0000-4000-8000-{value:012d}") for value in range(12)]
    expected_global_state = random.getstate()

    first = stable_shuffled_creator_ids(creator_ids, seed=42)
    second = stable_shuffled_creator_ids(reversed(creator_ids), seed=42)
    different = stable_shuffled_creator_ids(creator_ids, seed=43)

    assert first == second
    assert first != different
    assert set(first) == set(creator_ids)
    assert random.getstate() == expected_global_state


def test_screening_prompts_every_locked_creator_once_in_locked_order() -> None:
    creators = tuple(
        LockedScreeningCreator(
            UUID(f"50000000-0000-4000-8000-{value:012d}"),
            _creator_brief(f"Creator {value} locked."),
        )
        for value in range(100)
    )
    repository = FakeRepository(
        LockedScreeningInput(
            task_id=TASK_ID,
            game_brief=_game_brief(),
            creators=creators,
            applied_creator_ids=None,
        )
    )
    ai = FakeAI(_output(creators[-1].creator_id))

    assert _service(repository, ai).run(TASK_ID) == [creators[-1].creator_id]

    assert len(ai.calls) == 1
    model, messages, schema = ai.calls[0]
    payload = parse_prompt_payload(messages)
    assert model == "deepseek-v4-flash"
    assert schema is ScreeningOutput
    assert [item["creator_id"] for item in payload["creators"]] == [
        str(item.creator_id) for item in creators
    ]
    assert len({item["creator_id"] for item in payload["creators"]}) == 100
    assert payload["game_brief"] == _game_brief().model_dump(mode="json")
    assert repository.applied is not None


@pytest.mark.parametrize(
    "invalid_output",
    [
        ScreeningOutput.model_construct(
            english_language_check=True,
            selected=(_selection(UNKNOWN_CREATOR),),
        ),
        ScreeningOutput.model_construct(
            english_language_check=True,
            selected=(_selection(CREATOR_A), _selection(CREATOR_A)),
        ),
        ScreeningOutput.model_construct(
            english_language_check=True,
            selected=tuple(
                ScreeningSelection.model_construct(
                    creator_id=UUID(f"40000000-0000-4000-8000-{value:012d}"),
                    screening_reason="Plausible fit.",
                    evidence=("Locked evidence.",),
                )
                for value in range(31)
            ),
        ),
        SimpleNamespace(selected=()),
    ],
    ids=["unknown", "duplicate", "over-thirty", "wrong-output-type"],
)
def test_untrusted_provider_output_is_rejected_before_any_application(
    invalid_output: object,
) -> None:
    repository = FakeRepository(_locked_input())
    ai = FakeAI(invalid_output)

    with pytest.raises(InvalidScreeningOutput):
        _service(repository, ai).run(TASK_ID)

    assert repository.applied is None


def test_already_applied_screening_returns_persisted_order_without_calling_ai() -> None:
    repository = FakeRepository(
        _locked_input(applied_creator_ids=(CREATOR_B, CREATOR_A))
    )
    ai = FakeAI(AssertionError("AI must not run twice"))

    assert _service(repository, ai).run(TASK_ID) == [CREATOR_B, CREATOR_A]
    assert ai.calls == []
    assert repository.applied is None


def test_zero_eligible_creators_is_applied_without_calling_ai() -> None:
    repository = FakeRepository(
        LockedScreeningInput(
            task_id=TASK_ID,
            game_brief=_game_brief(),
            creators=(),
            applied_creator_ids=None,
        )
    )
    ai = FakeAI(AssertionError("empty screening must not call AI"))

    assert _service(repository, ai).run(TASK_ID) == []
    assert ai.calls == []
    assert repository.applied == []
