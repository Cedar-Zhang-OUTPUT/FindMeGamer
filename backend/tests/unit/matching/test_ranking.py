from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest
from celery.exceptions import Retry
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.analysis.prompts.common import parse_prompt_payload
from app.integrations.errors import InvalidModelOutput, TransientIntegrationError
from app.matching.ranking import (
    RANKING_MODEL,
    InvalidRankingOutput,
    LockedRankingInput,
    RankingService,
)
from app.schemas.ai_match import FinalRankingOutput, PairwiseMatchBrief
from app.schemas.match import MatchResultItem
from app.workers.match_tasks import FINALIZE_MATCH_TASK_NAME, finalize_match_ranking


NOW = datetime(2026, 9, 2, 16, 0, tzinfo=UTC)
TASK_ID = UUID("10000000-0000-4000-8000-000000000001")
CREATOR_A = UUID("20000000-0000-4000-8000-000000000001")
CREATOR_B = UUID("20000000-0000-4000-8000-000000000002")
BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _brief(creator_id: UUID, marker: str) -> PairwiseMatchBrief:
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
            "match_reasons": [f"{marker} reason"],
        }
    )


def _ranking(
    *,
    a_score: float = 0.7,
    a_group: str = "recommended",
    creator_ids: tuple[UUID, ...] = (CREATOR_A, CREATOR_B),
) -> FinalRankingOutput:
    items = []
    for order, creator_id in enumerate(creator_ids):
        score = a_score if creator_id == CREATOR_A else 0.69994
        group = a_group if creator_id == CREATOR_A else "other"
        items.append(
            {
                "creator_id": creator_id,
                "total_score": score,
                "dimension_scores": {
                    "content_fit": score,
                    "audience_fit": score,
                    "performance_fit": score,
                    "promotion_fit": score,
                    "brand_safety": score,
                },
                "backend_order": order,
                "result_group": group,
                "qualitative_label": "Good Match",
                "dimension_outcomes": {
                    "content_fit": "Aligned content.",
                    "audience_fit": "Likely audience overlap.",
                    "performance_fit": "Suitable performance context.",
                    "promotion_fit": "Suitable promotion format.",
                    "brand_safety": "No concern in supplied evidence.",
                },
                "match_reasons": [f"Reason for {creator_id}."],
            }
        )
    return FinalRankingOutput.model_validate(
        {"english_language_check": True, "items": items}
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
    def __init__(self, locked: LockedRankingInput) -> None:
        self.locked = locked
        self.publications: list[object] = []

    def load(self, match_task_id: UUID) -> LockedRankingInput:
        assert match_task_id == TASK_ID
        return self.locked

    def publish(self, match_task_id: UUID, publication: object) -> int:
        assert match_task_id == TASK_ID
        self.publications.append(publication)
        return len(publication.items)


class FakeSession:
    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _service(repository: FakeRepository, ai: FakeAI) -> RankingService:
    return RankingService(
        session_factory=lambda: FakeSession(),
        ai=ai,
        repository_factory=lambda _session: repository,
        clock=lambda: NOW,
    )


def _locked(
    *,
    published_count: int | None = None,
    threshold: Decimal = Decimal("0.7000"),
    match_briefs: tuple[PairwiseMatchBrief, ...] | None = None,
) -> LockedRankingInput:
    return LockedRankingInput(
        match_task_id=TASK_ID,
        threshold=threshold,
        match_briefs=(
            ()
            if published_count is not None
            else match_briefs or (_brief(CREATOR_A, "A"), _brief(CREATOR_B, "B"))
        ),
        published_count=published_count,
    )


def test_ranking_calls_pro_once_with_only_screening_ordered_successful_briefs() -> None:
    repository = FakeRepository(_locked())
    ai = FakeAI(_ranking())

    assert _service(repository, ai).run(TASK_ID) == 2
    assert len(ai.calls) == 1
    model, messages, schema = ai.calls[0]
    assert model == RANKING_MODEL == "deepseek-v4-pro"
    assert schema is FinalRankingOutput
    payload = parse_prompt_payload(messages)
    assert set(payload) == {"match_briefs", "recommended_match_threshold"}
    assert payload["recommended_match_threshold"] == "0.7000"
    assert [item["creator_id"] for item in payload["match_briefs"]] == [
        str(CREATOR_A),
        str(CREATOR_B),
    ]
    assert "contact" not in str(payload).casefold()
    publication = repository.publications[0]
    assert [item.total_score for item in publication.items] == [
        Decimal("0.7000"),
        Decimal("0.6999"),
    ]


def test_ranking_passes_nondefault_frozen_threshold_to_the_model_contract() -> None:
    repository = FakeRepository(
        _locked(
            threshold=Decimal("0.6500"),
            match_briefs=(_brief(CREATOR_A, "A"),),
        )
    )
    ai = FakeAI(_ranking(creator_ids=(CREATOR_A,)))

    assert _service(repository, ai).run(TASK_ID) == 1
    payload = parse_prompt_payload(ai.calls[0][1])
    assert payload["recommended_match_threshold"] == "0.6500"
    assert "0.7000" not in str(ai.calls[0][1])


@pytest.mark.parametrize(
    "output",
    [
        SimpleNamespace(items=()),
        _ranking(creator_ids=(CREATOR_A,)),
        _ranking(creator_ids=(CREATOR_A, UUID("30000000-0000-4000-8000-000000000003"))),
        _ranking().model_copy(update={"items": (_ranking().items[0],)}),
    ],
    ids=["wrong-type", "missing", "unknown", "mutated-malformed"],
)
def test_ranking_rejects_malformed_or_nonexact_creator_results(output: object) -> None:
    repository = FakeRepository(_locked())
    with pytest.raises(InvalidRankingOutput):
        _service(repository, FakeAI(output)).run(TASK_ID)
    assert repository.publications == []


@pytest.mark.parametrize(
    ("score", "model_group", "accepted"),
    [
        (0.7, "recommended", True),
        (0.69994, "other", True),
        (0.69996, "recommended", True),
        (0.69994, "recommended", False),
        (0.7, "other", False),
    ],
)
def test_group_is_verified_from_four_decimal_score_and_frozen_threshold(
    score: float, model_group: str, accepted: bool
) -> None:
    repository = FakeRepository(
        LockedRankingInput(
            match_task_id=TASK_ID,
            threshold=Decimal("0.7000"),
            match_briefs=(_brief(CREATOR_A, "A"),),
            published_count=None,
        )
    )
    output = _ranking(a_score=score, a_group=model_group, creator_ids=(CREATOR_A,))
    if accepted:
        assert _service(repository, FakeAI(output)).run(TASK_ID) == 1
    else:
        with pytest.raises(InvalidRankingOutput):
            _service(repository, FakeAI(output)).run(TASK_ID)
        assert repository.publications == []


def test_valid_existing_publication_is_authoritative_and_skips_ai() -> None:
    repository = FakeRepository(_locked(published_count=2))
    ai = FakeAI(AssertionError("AI must not run after successful publication"))
    assert _service(repository, ai).run(TASK_ID) == 2
    assert ai.calls == []
    assert repository.publications == []


@pytest.mark.parametrize(
    ("target", "canary"),
    [
        ("outcome", "total_score=0.8000"),
        ("reason", "This Creator is rank #1 for the Match."),
    ],
)
def test_final_public_text_rejects_internal_match_score_or_rank(
    target: str, canary: str
) -> None:
    output = _ranking(creator_ids=(CREATOR_A,))
    item = output.items[0]
    if target == "outcome":
        outcomes = item.dimension_outcomes.model_copy(update={"content_fit": canary})
        item = item.model_copy(update={"dimension_outcomes": outcomes})
    else:
        item = item.model_copy(update={"match_reasons": (canary,)})
    output = output.model_copy(update={"items": (item,)})
    repository = FakeRepository(_locked(match_briefs=(_brief(CREATOR_A, "A"),)))

    with pytest.raises(InvalidRankingOutput):
        _service(repository, FakeAI(output)).run(TASK_ID)
    assert repository.publications == []


@pytest.mark.parametrize(
    "canary",
    [
        "This is the top-ranked Creator with a fit rating of 0.82.",
        "The ranking places this Creator first.",
        "The Match percentage is 82%.",
        "The fit percent is 82 percent.",
    ],
)
def test_final_public_text_rejects_equivalent_rank_and_fit_rating_claims(
    canary: str,
) -> None:
    output = _ranking(creator_ids=(CREATOR_A,))
    item = output.items[0].model_copy(update={"match_reasons": (canary,)})
    output = output.model_copy(update={"items": (item,)})
    repository = FakeRepository(_locked(match_briefs=(_brief(CREATOR_A, "A"),)))

    with pytest.raises(InvalidRankingOutput):
        _service(repository, FakeAI(output)).run(TASK_ID)
    assert repository.publications == []


def test_public_pairwise_brief_rejects_internal_fit_score_language() -> None:
    dirty_brief = _brief(CREATOR_A, "A").model_copy(
        update={"match_reasons": ("The internal fit score is 0.82.",)}
    )
    repository = FakeRepository(_locked(match_briefs=(dirty_brief,)))

    with pytest.raises(InvalidRankingOutput):
        _service(repository, FakeAI(_ranking(creator_ids=(CREATOR_A,)))).run(TASK_ID)
    assert repository.publications == []


def test_public_match_text_allows_supplied_channel_and_game_fact_numbers() -> None:
    factual_brief = _brief(CREATOR_A, "A").model_copy(
        update={
            "match_reasons": (
                "The supplied channel evidence reports 120,000 subscribers.",
                "The supplied video evidence reports a duration of 12 minutes.",
            )
        }
    )
    output = _ranking(creator_ids=(CREATOR_A,))
    item = output.items[0]
    outcomes = item.dimension_outcomes.model_copy(
        update={
            "content_fit": "The supplied game facts describe a 4-player campaign.",
            "performance_fit": "The supplied recent median is 45,000 views.",
        }
    )
    output = output.model_copy(
        update={"items": (item.model_copy(update={"dimension_outcomes": outcomes}),)}
    )
    repository = FakeRepository(_locked(match_briefs=(factual_brief,)))

    assert _service(repository, FakeAI(output)).run(TASK_ID) == 1
    assert len(repository.publications) == 1


def _creator_card() -> dict[str, object]:
    return {
        "id": CREATOR_A,
        "name": "Current Creator",
        "youtube_channel_id": "UC0000000000000000000000",
        "canonical_url": "https://www.youtube.com/channel/UC0000000000000000000000",
        "avatar_url": "https://images.example.invalid/current-creator.jpg",
        "favorite": True,
        "subscriber_count": 1234,
        "recent_average_views": 456,
        "recent_median_views": 321,
        "performance_summary": "Current public performance context.",
        "contact_available": True,
        "contact": {
            "email": "creator@example.com",
            "purpose": None,
            "source": "manual",
            "source_url": None,
            "validation_state": "verified",
        },
        "contacts": [
            {
                "email": "creator@example.com",
                "purpose": None,
                "source": "manual",
                "source_url": None,
                "validation_state": "verified",
            }
        ],
    }


def _public_payload() -> dict[str, object]:
    brief = _brief(CREATOR_A, "PUBLIC").model_dump(mode="json")
    brief.pop("english_language_check")
    brief.pop("creator_id")
    return {
        "creator": _creator_card(),
        "result_group": "recommended",
        "qualitative_label": "Good Match",
        "dimension_outcomes": _ranking(creator_ids=(CREATOR_A,))
        .items[0]
        .dimension_outcomes.model_dump(),
        "match_reasons": ["Public qualitative reason."],
        "match_brief": brief,
        "outreach": {
            "send_state": "not_sent",
            "response_state": "no_response",
            "delivery_id": None,
        },
    }


def _schema_property_names(value: object) -> set[str]:
    if isinstance(value, dict):
        names = (
            set(value.get("properties", {}))
            if isinstance(value.get("properties"), dict)
            else set()
        )
        return names | set().union(
            *(_schema_property_names(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(_schema_property_names(item) for item in value))
    return set()


def test_public_match_item_is_closed_and_contains_no_hidden_numeric_or_model_fields() -> (
    None
):
    item = MatchResultItem.model_validate(_public_payload())
    dumped = item.model_dump(mode="json")
    forbidden = {
        "rank",
        "score",
        "total_score",
        "dimension_scores",
        "backend_order",
        "english_language_check",
        "creator_id",
        "current_facts",
        "brief",
        "source_status",
        "model_metadata",
        "prompt_metadata",
    }
    assert forbidden.isdisjoint(
        _schema_property_names(MatchResultItem.model_json_schema())
    )
    creator_properties = MatchResultItem.model_json_schema()["$defs"][
        "MatchCreatorCard"
    ]["properties"]
    assert {
        "current_facts",
        "brief",
        "source_status",
        "analysis",
        "model_metadata",
        "prompt_metadata",
    }.isdisjoint(creator_properties)
    assert not any(
        key in str(dumped)
        for key in ("total_score", "dimension_scores", "backend_order")
    )
    assert dumped["creator"]["contact"]["email"] == "creator@example.com"
    assert set(dumped["match_brief"]) == {
        "content_fit",
        "audience_fit",
        "performance_fit",
        "promotion_fit",
        "brand_safety",
        "strengths",
        "risks",
        "evidence",
        "match_reasons",
    }
    assert "0.987654321-secret-score" not in repr(item)


def test_creator_projection_rejects_open_json_canaries_without_echoing_values() -> None:
    payload = _public_payload()
    creator = payload["creator"]
    assert isinstance(creator, dict)
    creator["current_facts"] = {
        "rank": "rank-value-must-not-escape",
        "score": "score-value-must-not-escape",
        "total_score": "total-value-must-not-escape",
        "dimension_scores": "dimension-value-must-not-escape",
        "backend_order": "order-value-must-not-escape",
    }
    with pytest.raises(ValidationError) as raised:
        MatchResultItem.model_validate(payload)
    rendered = str(raised.value)
    assert "current_facts" in rendered
    assert "must-not-escape" not in rendered


def test_nested_creator_and_contact_extras_are_rejected_without_input_values() -> None:
    for path in ("creator", "contact"):
        payload = _public_payload()
        creator = payload["creator"]
        assert isinstance(creator, dict)
        target = creator if path == "creator" else creator["contact"]
        assert isinstance(target, dict)
        target["backend_order"] = "nested-value-must-not-escape"
        with pytest.raises(ValidationError) as raised:
            MatchResultItem.model_validate(payload)
        assert "backend_order" in str(raised.value)
        assert "nested-value-must-not-escape" not in str(raised.value)


def test_fastapi_match_response_contains_only_explicit_closed_fields() -> None:
    application = FastAPI()

    @application.get("/result", response_model=MatchResultItem)
    def result() -> MatchResultItem:
        return MatchResultItem.model_validate(_public_payload())

    response = TestClient(application).get("/result")
    assert response.status_code == 200
    body = response.json()
    assert set(body["creator"]) == {
        "id",
        "name",
        "youtube_channel_id",
        "canonical_url",
        "avatar_url",
        "favorite",
        "subscriber_count",
        "recent_average_views",
        "recent_median_views",
        "performance_summary",
        "contact_available",
        "contact",
        "contacts",
    }
    rendered = response.text
    assert all(
        forbidden not in rendered
        for forbidden in (
            "rank-value-must-not-escape",
            "score-value-must-not-escape",
            "order-value-must-not-escape",
            "current_facts",
            "source_status",
            "model_metadata",
        )
    )


@pytest.mark.parametrize(
    "hidden", ["rank", "score", "total_score", "dimension_scores", "backend_order"]
)
def test_public_match_validation_rejects_hidden_fields_without_echoing_values(
    hidden: str,
) -> None:
    payload = _public_payload()
    payload[hidden] = "0.987654321-secret-score"
    with pytest.raises(ValidationError) as raised:
        MatchResultItem.model_validate(payload)
    assert hidden in str(raised.value)
    assert "0.987654321-secret-score" not in str(raised.value)


def test_finalize_worker_is_registered_late_acked_and_retries_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert finalize_match_ranking.name == FINALIZE_MATCH_TASK_NAME
    assert finalize_match_ranking.acks_late is True
    assert finalize_match_ranking.reject_on_worker_lost is True

    class Executor:
        def __init__(self) -> None:
            self.store = SimpleNamespace(fail_task=lambda *_args: True)

        def finalize(self, task_id: UUID) -> int:
            assert task_id == TASK_ID
            raise TransientIntegrationError("deepseek_unavailable")

    monkeypatch.setattr("app.workers.match_tasks.get_match_executor", Executor)
    monkeypatch.setattr("app.workers.match_tasks.random_jitter", lambda _ceiling: 1)
    with pytest.raises(Retry) as raised:
        finalize_match_ranking.apply(args=[str(TASK_ID)], throw=True)
    assert raised.value.when == 3


def test_finalize_invalid_uuid_is_noop_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.workers.match_tasks.get_match_executor",
        lambda: (_ for _ in ()).throw(AssertionError("runtime must not be built")),
    )
    assert finalize_match_ranking.apply(args=["NOT-A-UUID"], throw=True).get() is None


def test_ranking_imports_make_no_network_connection() -> None:
    script = r"""
import socket
def blocked(*args, **kwargs):
    raise AssertionError("network access during import")
socket.socket.connect = blocked
socket.create_connection = blocked
import app.matching.ranking
import app.schemas.match
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
