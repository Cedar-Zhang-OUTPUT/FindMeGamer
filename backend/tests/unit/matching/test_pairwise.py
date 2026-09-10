from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from celery.exceptions import Retry

from app.analysis.prompts.common import parse_prompt_payload
from app.integrations.deepseek import DeepSeekGateway
from app.integrations.errors import InvalidModelOutput, TransientIntegrationError
from app.matching.pairwise import (
    InvalidPairwiseOutput,
    LockedPairwiseInput,
    PAIRWISE_MODEL,
    PairwiseCheckpointError,
    PairwiseService,
)
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import PairwiseMatchBrief
from app.workers.celery_app import celery_app
from app.workers.match_tasks import (
    ADVANCE_MATCH_TASK_NAME,
    FINALIZE_MATCH_TASK_NAME,
    RUN_PAIRWISE_TASK_NAME,
    START_MATCH_TASK_NAME,
    MatchTaskExecutor,
    PairwiseTerminalFailure,
    advance_match_task,
    advisory_lock_key,
    run_pairwise_match,
    start_match_task,
)


NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)
TASK_ID = UUID("10000000-0000-4000-8000-000000000001")
CREATOR_ID = UUID("20000000-0000-4000-8000-000000000001")
OTHER_CREATOR_ID = UUID("20000000-0000-4000-8000-000000000002")
BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _unavailable(reason: str) -> dict[str, str]:
    return {"status": "unavailable", "reason": reason}


def _game_brief(reason: str = "LOCKED-GAME-CANARY") -> GameBrief:
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


def _creator_brief(reason: str = "LOCKED-CREATOR-CANARY") -> dict[str, object]:
    claim = _unavailable(reason)
    return {
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


def _profile(creator_id: UUID = CREATOR_ID) -> dict[str, object]:
    return {
        "id": str(creator_id),
        "youtube_channel_id": "UC0000000000000000000000",
        "canonical_url": "https://www.youtube.com/channel/UC0000000000000000000000",
        "current_facts": {
            "title": "Locked Creator",
            "subscriber_count": 10_000,
            "private_contact_email": "must-not-enter-prompt@example.invalid",
        },
        "analysis": {
            "content_summary": _unavailable("LOCKED-ANALYSIS-CANARY"),
            "prior_outreach": _unavailable("MUST-NOT-ENTER-PROMPT"),
        },
        "brief": _creator_brief(),
    }


def _brief(creator_id: UUID = CREATOR_ID) -> PairwiseMatchBrief:
    dimension = {
        "analysis": "The locked evidence supports a cautious comparison.",
        "evidence": ["Locked task evidence."],
    }
    return PairwiseMatchBrief.model_validate(
        {
            "english_language_check": True,
            "creator_id": creator_id,
            "content_fit": dimension,
            "audience_fit": dimension,
            "performance_fit": dimension,
            "promotion_fit": dimension,
            "brand_safety": dimension,
            "strengths": ["Clear content fit."],
            "risks": ["Audience overlap is inferred."],
            "evidence": ["Locked task evidence."],
            "match_reasons": ["The content format fits the game."],
        }
    )


class FakeAI:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[tuple[str, list, type]] = []

    def complete_structured(self, model: str, messages: list, schema: type) -> object:
        self.calls.append((model, messages, schema))
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


class FakeRepository:
    def __init__(self, locked: LockedPairwiseInput) -> None:
        self.locked = locked
        self.applied: list[PairwiseMatchBrief] = []

    def claim(self, match_task_id: UUID, creator_id: UUID) -> LockedPairwiseInput:
        assert (match_task_id, creator_id) == (TASK_ID, CREATOR_ID)
        return self.locked

    def apply_success(
        self,
        match_task_id: UUID,
        creator_id: UUID,
        brief: PairwiseMatchBrief,
    ) -> PairwiseMatchBrief:
        assert (match_task_id, creator_id) == (TASK_ID, CREATOR_ID)
        self.applied.append(brief)
        return brief


class FakeSession:
    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _service(repository: FakeRepository, ai: FakeAI) -> PairwiseService:
    return PairwiseService(
        session_factory=lambda: FakeSession(),
        ai=ai,
        repository_factory=lambda _session: repository,
        clock=lambda: NOW,
    )


def test_successful_pair_is_authoritative_and_never_calls_ai_again() -> None:
    completed = _brief()
    repository = FakeRepository(
        LockedPairwiseInput(
            match_task_id=TASK_ID,
            creator_id=CREATOR_ID,
            game_brief=None,
            creator_profile=None,
            completed_brief=completed,
        )
    )
    ai = FakeAI(AssertionError("AI must not run for a valid checkpoint"))

    assert _service(repository, ai).run(TASK_ID, CREATOR_ID) == completed
    assert ai.calls == []
    assert repository.applied == []


def test_pairwise_uses_only_locked_inputs_and_exact_creator_identity() -> None:
    repository = FakeRepository(
        LockedPairwiseInput(
            match_task_id=TASK_ID,
            creator_id=CREATOR_ID,
            game_brief=_game_brief(),
            creator_profile=_profile(),
            completed_brief=None,
        )
    )
    ai = FakeAI(_brief())

    assert _service(repository, ai).run(TASK_ID, CREATOR_ID) == _brief()
    model, messages, schema = ai.calls[0]
    payload = parse_prompt_payload(messages)
    assert model == PAIRWISE_MODEL == "deepseek-flash"
    assert schema is PairwiseMatchBrief
    assert "LOCKED-GAME-CANARY" in str(payload["game_brief"])
    assert payload["creator_profile"]["creator_id"] == str(CREATOR_ID)
    assert "LOCKED-ANALYSIS-CANARY" in str(payload["creator_profile"])
    assert "must-not-enter-prompt" not in str(payload)
    assert "MUST-NOT-ENTER-PROMPT" not in str(payload)
    assert repository.applied == [_brief()]


@pytest.mark.parametrize(
    "invalid",
    [
        _brief(OTHER_CREATOR_ID),
        SimpleNamespace(creator_id=CREATOR_ID),
        _brief().model_copy(update={"strengths": ()}),
    ],
    ids=["wrong-creator", "wrong-type", "malformed"],
)
def test_invalid_provider_output_never_writes_a_checkpoint(invalid: object) -> None:
    repository = FakeRepository(
        LockedPairwiseInput(
            match_task_id=TASK_ID,
            creator_id=CREATOR_ID,
            game_brief=_game_brief(),
            creator_profile=_profile(),
            completed_brief=None,
        )
    )

    with pytest.raises(InvalidPairwiseOutput):
        _service(repository, FakeAI(invalid)).run(TASK_ID, CREATOR_ID)
    assert repository.applied == []


class FakeScreening:
    def __init__(self, selected: list[UUID]) -> None:
        self.selected = selected
        self.calls: list[UUID] = []

    def run(self, match_task_id: UUID) -> list[UUID]:
        self.calls.append(match_task_id)
        return self.selected


class FakePairwise:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[UUID, UUID]] = []

    def run(self, match_task_id: UUID, creator_id: UUID) -> PairwiseMatchBrief:
        self.calls.append((match_task_id, creator_id))
        if isinstance(self.result, BaseException):
            raise self.result
        assert isinstance(self.result, PairwiseMatchBrief)
        return self.result


class FakeDispatcher:
    def __init__(self) -> None:
        self.pairwise: list[tuple[str, str]] = []
        self.advances: list[str] = []
        self.rankings: list[str] = []
        self.error: BaseException | None = None

    def dispatch_pairwise(self, task_id: UUID, creator_id: UUID) -> None:
        self.pairwise.append((str(task_id), str(creator_id)))
        if self.error:
            raise self.error

    def dispatch_advance(self, task_id: UUID) -> None:
        self.advances.append(str(task_id))
        if self.error:
            raise self.error

    def dispatch_ranking(self, task_id: UUID) -> None:
        self.rankings.append(str(task_id))
        if self.error:
            raise self.error


class FakeStore:
    def __init__(self, incomplete: list[UUID] | None = None) -> None:
        self.incomplete = incomplete or []
        self.prepared: list[tuple[UUID, tuple[UUID, ...]]] = []
        self.failures: list[tuple[UUID, UUID, PairwiseTerminalFailure]] = []
        self.advance_ready = False
        self.compensations: list[UUID] = []

    def prepare(self, task_id: UUID, creators: list[UUID]) -> list[UUID]:
        self.prepared.append((task_id, tuple(creators)))
        return list(self.incomplete)

    def fail_pair(
        self,
        task_id: UUID,
        creator_id: UUID,
        failure: PairwiseTerminalFailure,
    ) -> bool:
        self.failures.append((task_id, creator_id, failure))
        return True

    def mark_ranking_enqueued(self, task_id: UUID) -> bool:
        if not self.advance_ready:
            return False
        self.advance_ready = False
        return True

    def compensate_ranking_enqueue(self, task_id: UUID) -> bool:
        self.compensations.append(task_id)
        self.advance_ready = True
        return True


def _executor(
    *,
    screening: FakeScreening | None = None,
    pairwise: FakePairwise | None = None,
    store: FakeStore | None = None,
    dispatcher: FakeDispatcher | None = None,
) -> MatchTaskExecutor:
    return MatchTaskExecutor(
        screening=screening or FakeScreening([]),
        pairwise_factory=lambda: _managed(pairwise or FakePairwise(_brief())),
        store=store or FakeStore(),
        dispatcher=dispatcher or FakeDispatcher(),
    )


@contextmanager
def _managed(value):
    yield value


def test_start_prepares_unique_selected_pairs_and_zero_dispatches_nothing() -> None:
    selected = [CREATOR_ID, OTHER_CREATOR_ID]
    store = FakeStore(incomplete=selected)
    dispatcher = FakeDispatcher()
    executor = _executor(
        screening=FakeScreening(selected), store=store, dispatcher=dispatcher
    )

    executor.start(TASK_ID)
    assert store.prepared == [(TASK_ID, tuple(selected))]
    assert dispatcher.pairwise == [
        (str(TASK_ID), str(CREATOR_ID)),
        (str(TASK_ID), str(OTHER_CREATOR_ID)),
    ]

    empty_store = FakeStore()
    empty_dispatcher = FakeDispatcher()
    _executor(
        screening=FakeScreening([]),
        store=empty_store,
        dispatcher=empty_dispatcher,
    ).start(TASK_ID)
    assert empty_store.prepared == []
    assert empty_dispatcher.pairwise == []


def test_advance_publishes_ranking_once_and_compensates_sync_broker_failure() -> None:
    store = FakeStore()
    store.advance_ready = True
    dispatcher = FakeDispatcher()
    executor = _executor(store=store, dispatcher=dispatcher)

    assert executor.advance(TASK_ID) is True
    assert executor.advance(TASK_ID) is False
    assert dispatcher.rankings == [str(TASK_ID)]

    retry_store = FakeStore()
    retry_store.advance_ready = True
    failing_dispatcher = FakeDispatcher()
    failing_dispatcher.error = ConnectionError("broker detail must stay private")
    retry_executor = _executor(
        store=retry_store,
        dispatcher=failing_dispatcher,
    )
    with pytest.raises(TransientIntegrationError) as raised:
        retry_executor.advance(TASK_ID)
    assert raised.value.code == "match_queue_unavailable"
    assert retry_store.compensations == [TASK_ID]
    failing_dispatcher.error = None
    assert retry_executor.advance(TASK_ID) is True
    assert failing_dispatcher.rankings == [str(TASK_ID), str(TASK_ID)]


def test_worker_tasks_use_safe_json_ids_stable_names_and_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert start_match_task.name == START_MATCH_TASK_NAME
    assert run_pairwise_match.name == RUN_PAIRWISE_TASK_NAME
    assert advance_match_task.name == ADVANCE_MATCH_TASK_NAME
    assert FINALIZE_MATCH_TASK_NAME == "find_me_gamer.match.finalize_ranking"
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.worker_concurrency == 5
    assert "app.workers.match_tasks" in celery_app.conf.include
    for task in (start_match_task, run_pairwise_match, advance_match_task):
        assert task.acks_late is True
        assert task.reject_on_worker_lost is True

    executor = _executor(
        pairwise=FakePairwise(TransientIntegrationError("deepseek_unavailable"))
    )
    monkeypatch.setattr("app.workers.match_tasks.get_match_executor", lambda: executor)
    monkeypatch.setattr("app.workers.match_tasks.random_jitter", lambda ceiling: 1)
    with pytest.raises(Retry) as raised:
        run_pairwise_match.apply(args=[str(TASK_ID), str(CREATOR_ID)], throw=True)
    assert raised.value.when == 3
    assert "deepseek_unavailable" in str(raised.value)
    assert executor.store.failures == []


def test_terminal_invalid_model_failure_is_safe_and_preserves_no_raw_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "secret-key=must-never-persist"
    store = FakeStore()
    executor = _executor(
        pairwise=FakePairwise(InvalidModelOutput("deepseek_model_output_invalid")),
        store=store,
    )
    monkeypatch.setattr("app.workers.match_tasks.get_match_executor", lambda: executor)

    run_pairwise_match.apply(
        args=[str(TASK_ID), str(CREATOR_ID)], retries=3, throw=True
    ).get()
    assert len(store.failures) == 1
    failure = store.failures[0][2]
    assert failure.code == "deepseek_model_output_invalid"
    assert failure.retryable is True
    assert raw not in failure.message
    assert "secret" not in failure.message.casefold()


def test_terminal_pair_redelivery_is_an_explicit_worker_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    dispatcher = FakeDispatcher()
    executor = _executor(
        pairwise=FakePairwise(PairwiseCheckpointError("match_pair_terminal")),
        store=store,
        dispatcher=dispatcher,
    )
    monkeypatch.setattr("app.workers.match_tasks.get_match_executor", lambda: executor)

    run_pairwise_match.apply(
        args=[str(TASK_ID), str(CREATOR_ID)], retries=3, throw=True
    ).get()

    assert store.failures == []
    assert dispatcher.advances == []


def test_invalid_uuid_arguments_are_noops_before_runtime_or_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.workers.match_tasks.get_match_executor",
        lambda: (_ for _ in ()).throw(AssertionError("must not construct runtime")),
    )
    for task, arguments in (
        (start_match_task, ["AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"]),
        (run_pairwise_match, [str(TASK_ID), "not-a-uuid"]),
        (advance_match_task, [str(UUID(int=0))]),
    ):
        assert task.apply(args=arguments, throw=True).get() is None


def test_advisory_key_is_stable_signed_64_and_uses_every_uuid_bit() -> None:
    keys = {
        advisory_lock_key(UUID("00000000-0000-4000-8000-000000000001")),
        advisory_lock_key(UUID("00000000-0000-4000-8000-000000000002")),
        advisory_lock_key(UUID("ffffffff-ffff-4fff-bfff-ffffffffffff")),
    }
    assert len(keys) == 3
    assert all(-(2**63) <= key < 2**63 for key in keys)
    assert advisory_lock_key(TASK_ID) == advisory_lock_key(UUID(str(TASK_ID)))


def test_imports_open_no_socket_or_external_resource() -> None:
    script = r"""
import socket
def blocked(*args, **kwargs):
    raise AssertionError("network access during import")
socket.socket.connect = blocked
socket.create_connection = blocked
import app.matching.pairwise
import app.workers.match_tasks
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_production_gateway_loads_only_encrypted_deepseek_secret_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.workers.match_tasks as workers

    loaded = {"deepseek": "test-deepseek-secret"}
    requested: list[tuple[str, ...]] = []
    gateways: list[DeepSeekGateway] = []

    class FakeProvider:
        def load(self, services):
            requested.append(tuple(services))
            return loaded

    class FakeGateway:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            assert api_key == "test-deepseek-secret"
            assert base_url == "https://api.deepseek.com"
            self.closed = False
            gateways.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

    monkeypatch.setattr(
        workers, "build_secret_provider", lambda **_kwargs: FakeProvider()
    )
    monkeypatch.setattr(workers, "DeepSeekGateway", FakeGateway)
    with workers._production_gateway() as gateway:
        assert gateway is gateways[0]
        assert loaded == {"deepseek": "test-deepseek-secret"}
    assert requested == [("deepseek",)]
    assert gateways[0].closed is True
    assert loaded == {}
