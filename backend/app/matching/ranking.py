"""Atomic, immutable publication of complete Match ranking results."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import re
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.contracts import Message
from app.db.models.match import (
    MatchCandidateInput,
    MatchPairwiseRecord,
    MatchResultGroup,
    MatchResultItem,
    MatchScreeningRecord,
    MatchStage,
    MatchStatus,
    MatchTask,
    PairwiseState,
)
from app.db.models.outreach import OutreachCampaign
from app.integrations.errors import InvalidModelOutput, PermanentIntegrationError
from app.matching.prompts import build_ranking_prompt
from app.schemas.ai_match import FinalRankingOutput, PairwiseMatchBrief, RankingItem


RANKING_MODEL = "deepseek-v4-pro"
SCORE_QUANTUM = Decimal("0.0001")
_PUBLIC_INTERNAL_MECHANIC_PATTERNS = (
    re.compile(r"\b(?:total|dimension)[\s_-]*scores?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:match|fit)(?:[\s_-]+\w+){0,2}[\s_-]+"
        r"(?:score|rating|percentage|percent)s?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bbackend[\s_-]*order\b", re.IGNORECASE),
    re.compile(r"\b(?:recommendation[\s_-]*)?threshold\b", re.IGNORECASE),
    re.compile(r"\bresult[\s_-]*group\b", re.IGNORECASE),
    re.compile(r"\b(?:recommended|other)[\s_-]*(?:group|bucket)\b", re.IGNORECASE),
    re.compile(r"\b(?:rank|ranked|ranking)\b", re.IGNORECASE),
)


class RankingCheckpointError(PermanentIntegrationError):
    def __init__(self, code: str = "match_ranking_checkpoint_invalid") -> None:
        super().__init__(code)


class InvalidRankingOutput(InvalidModelOutput):
    def __init__(self) -> None:
        super().__init__("deepseek_model_output_invalid")


@dataclass(frozen=True, slots=True)
class LockedRankingInput:
    match_task_id: UUID
    threshold: Decimal
    match_briefs: tuple[PairwiseMatchBrief, ...]
    published_count: int | None

    def __post_init__(self) -> None:
        _require_uuid(self.match_task_id)
        if not isinstance(self.threshold, Decimal) or not Decimal(
            "0"
        ) <= self.threshold <= Decimal("1"):
            raise ValueError("ranking threshold must be a Decimal from zero to one")
        ids = [brief.creator_id for brief in self.match_briefs]
        if any(
            not isinstance(brief, PairwiseMatchBrief) for brief in self.match_briefs
        ):
            raise TypeError("ranking briefs must be validated")
        if len(ids) != len(set(ids)):
            raise ValueError("ranking brief IDs must be unique")
        if self.published_count is not None:
            if self.published_count < 0 or self.match_briefs:
                raise ValueError("published ranking input is invalid")
        elif not self.match_briefs:
            raise ValueError("ranking requires non-empty briefs")


@dataclass(frozen=True, slots=True)
class PublicationItem:
    ranking: RankingItem
    total_score: Decimal


@dataclass(frozen=True, slots=True)
class RankingPublication:
    items: tuple[PublicationItem, ...]


class StructuredRankingAI(Protocol):
    def complete_structured(
        self, model: str, messages: list[Message], schema: type[FinalRankingOutput]
    ) -> object: ...


class RankingRepository(Protocol):
    def load(self, match_task_id: UUID) -> LockedRankingInput: ...
    def publish(self, match_task_id: UUID, publication: RankingPublication) -> int: ...


class SQLRankingRepository:
    def __init__(
        self, session: Session, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self._session = session
        self._clock = clock or (lambda: datetime.now(UTC))

    def load(self, match_task_id: UUID) -> LockedRankingInput:
        _require_uuid(match_task_id)
        task = self._session.scalar(
            select(MatchTask).where(MatchTask.id == match_task_id).with_for_update()
        )
        if task is None:
            raise RankingCheckpointError("match_task_not_found")
        selected, briefs = self._validated_inputs(task)
        if task.status == MatchStatus.SUCCEEDED:
            count = self._validated_publication(task, selected)
            return LockedRankingInput(
                task.id, task.recommended_match_threshold, (), count
            )
        if (
            task.status != MatchStatus.RUNNING
            or task.stage != MatchStage.RANKING
            or task.ranking_enqueued_at is None
        ):
            raise RankingCheckpointError("match_task_not_rankable")
        return LockedRankingInput(
            task.id, task.recommended_match_threshold, tuple(briefs), None
        )

    def publish(self, match_task_id: UUID, publication: RankingPublication) -> int:
        _require_uuid(match_task_id)
        if not isinstance(publication, RankingPublication):
            raise TypeError("publication must be validated")
        task = self._session.scalar(
            select(MatchTask).where(MatchTask.id == match_task_id).with_for_update()
        )
        if task is None:
            raise RankingCheckpointError("match_task_not_found")
        selected, briefs = self._validated_inputs(task)
        if task.status == MatchStatus.SUCCEEDED:
            return self._validated_publication(task, selected)
        if (
            task.status not in (MatchStatus.RUNNING, MatchStatus.FAILED)
            or task.stage != MatchStage.RANKING
            or task.ranking_enqueued_at is None
        ):
            raise RankingCheckpointError("match_task_not_rankable")
        by_creator = {brief.creator_id: brief for brief in briefs}
        if {item.ranking.creator_id for item in publication.items} != set(selected):
            raise RankingCheckpointError()
        now = _aware_utc(self._clock)
        for item in publication.items:
            ranking = item.ranking
            self._session.add(
                MatchResultItem(
                    match_task_id=task.id,
                    creator_id=ranking.creator_id,
                    backend_order=ranking.backend_order,
                    match_brief=by_creator[ranking.creator_id].model_dump(mode="json"),
                    total_score=item.total_score,
                    dimension_scores={
                        key: float(_quantize_score(value))
                        for key, value in ranking.dimension_scores.model_dump().items()
                    },
                    dimension_outcomes=ranking.dimension_outcomes.model_dump(
                        mode="json"
                    ),
                    match_reasons=list(ranking.match_reasons),
                    result_group=MatchResultGroup(ranking.result_group),
                    qualitative_label=ranking.qualitative_label,
                    created_at=now,
                    updated_at=now,
                )
            )
        self._session.add(
            OutreachCampaign(match_task_id=task.id, created_at=now, updated_at=now)
        )
        task.status = MatchStatus.SUCCEEDED
        task.result_count = len(publication.items)
        task.completed_units = task.total_units
        task.error_code = None
        task.error_message = None
        task.retryable = False
        task.completed_at = now
        task.updated_at = now
        self._before_final_flush()
        self._session.flush()
        return len(publication.items)

    def _validated_inputs(
        self, task: MatchTask
    ) -> tuple[list[UUID], list[PairwiseMatchBrief]]:
        screening = self._session.scalars(
            select(MatchScreeningRecord)
            .where(
                MatchScreeningRecord.match_task_id == task.id,
                MatchScreeningRecord.selected.is_(True),
            )
            .order_by(MatchScreeningRecord.screening_order)
            .with_for_update()
        ).all()
        selected = [row.creator_id for row in screening]
        candidates = set(
            self._session.scalars(
                select(MatchCandidateInput.creator_id)
                .where(MatchCandidateInput.match_task_id == task.id)
                .with_for_update()
            )
        )
        pair_rows = self._session.scalars(
            select(MatchPairwiseRecord)
            .where(MatchPairwiseRecord.match_task_id == task.id)
            .with_for_update()
        ).all()
        pair_by_id = {row.creator_id: row for row in pair_rows}
        if (
            not selected
            or len(selected) != len(set(selected))
            or candidates != set(selected)
            or set(pair_by_id) != set(selected)
            or task.total_units != len(selected) + 2
        ):
            raise RankingCheckpointError()
        briefs: list[PairwiseMatchBrief] = []
        for creator_id in selected:
            row = pair_by_id[creator_id]
            if row.state != PairwiseState.SUCCEEDED:
                raise RankingCheckpointError()
            briefs.append(_validated_brief(row.match_brief, creator_id))
        return selected, briefs

    def _validated_publication(self, task: MatchTask, selected: list[UUID]) -> int:
        rows = self._session.scalars(
            select(MatchResultItem)
            .where(MatchResultItem.match_task_id == task.id)
            .with_for_update()
        ).all()
        campaign_count = int(
            self._session.scalar(
                select(func.count())
                .select_from(OutreachCampaign)
                .where(OutreachCampaign.match_task_id == task.id)
            )
            or 0
        )
        if (
            task.result_count != len(selected)
            or len(rows) != len(selected)
            or {row.creator_id for row in rows} != set(selected)
            or len({row.backend_order for row in rows}) != len(rows)
            or campaign_count != 1
            or task.completed_at is None
            or task.completed_units != task.total_units
        ):
            raise RankingCheckpointError("match_publication_invalid")
        return len(rows)

    def _before_final_flush(self) -> None:
        """Narrow test seam immediately before the atomic publication flush."""


class RankingService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]],
        ai: StructuredRankingAI,
        clock: Callable[[], datetime] | None = None,
        repository_factory: Callable[[Session], RankingRepository] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._ai = ai
        self._clock = clock or (lambda: datetime.now(UTC))
        self._repository_factory = repository_factory or (
            lambda session: SQLRankingRepository(session, clock=self._clock)
        )

    def run(self, match_task_id: UUID) -> int:
        _require_uuid(match_task_id)
        with self._session_factory() as session, session.begin():
            locked = self._repository_factory(session).load(match_task_id)
        if locked.published_count is not None:
            return locked.published_count
        _validate_pairwise_public_text(locked.match_briefs)
        raw = self._ai.complete_structured(
            RANKING_MODEL,
            build_ranking_prompt(locked.match_briefs, threshold=locked.threshold),
            FinalRankingOutput,
        )
        publication = _validated_output(
            raw,
            expected_ids=tuple(brief.creator_id for brief in locked.match_briefs),
            threshold=locked.threshold,
        )
        with self._session_factory() as session, session.begin():
            return self._repository_factory(session).publish(match_task_id, publication)


def _validated_output(
    value: object, *, expected_ids: tuple[UUID, ...], threshold: Decimal
) -> RankingPublication:
    if not isinstance(value, FinalRankingOutput):
        raise InvalidRankingOutput()
    try:
        validated = FinalRankingOutput.model_validate(value.model_dump())
        validated.validate_expected_creator_ids(expected_ids)
        _validate_final_public_text(validated)
    except (ValidationError, TypeError, ValueError):
        raise InvalidRankingOutput() from None
    items: list[PublicationItem] = []
    for ranking in validated.items:
        score = _quantize_score(ranking.total_score)
        expected_group = "recommended" if score >= threshold else "other"
        if ranking.result_group != expected_group:
            raise InvalidRankingOutput()
        items.append(PublicationItem(ranking=ranking, total_score=score))
    return RankingPublication(tuple(items))


def _validate_pairwise_public_text(
    match_briefs: tuple[PairwiseMatchBrief, ...],
) -> None:
    for brief in match_briefs:
        dimensions = (
            brief.content_fit,
            brief.audience_fit,
            brief.performance_fit,
            brief.promotion_fit,
            brief.brand_safety,
        )
        for dimension in dimensions:
            _reject_internal_public_text((dimension.analysis, *dimension.evidence))
        _reject_internal_public_text(
            (*brief.strengths, *brief.risks, *brief.evidence, *brief.match_reasons)
        )


def _validate_final_public_text(output: FinalRankingOutput) -> None:
    for item in output.items:
        _reject_internal_public_text(
            (*item.dimension_outcomes.model_dump().values(), *item.match_reasons)
        )


def _reject_internal_public_text(values: tuple[str, ...]) -> None:
    if any(
        pattern.search(value)
        for value in values
        for pattern in _PUBLIC_INTERNAL_MECHANIC_PATTERNS
    ):
        raise InvalidRankingOutput()


def _quantize_score(value: object) -> Decimal:
    try:
        score = Decimal(str(value)).quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)
    except Exception:
        raise InvalidRankingOutput() from None
    if not score.is_finite() or not Decimal("0") <= score <= Decimal("1"):
        raise InvalidRankingOutput()
    return score


def _validated_brief(value: object, creator_id: UUID) -> PairwiseMatchBrief:
    try:
        brief = PairwiseMatchBrief.model_validate_json(
            json.dumps(
                value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )
        )
    except Exception:
        raise RankingCheckpointError() from None
    if brief.creator_id != creator_id:
        raise RankingCheckpointError()
    return brief


def _require_uuid(value: object) -> UUID:
    if type(value) is not UUID or value.int == 0:
        raise TypeError("match task id must be a nonzero UUID")
    return value


def _aware_utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise RankingCheckpointError("match_clock_invalid")
    return value.astimezone(UTC)


__all__ = [
    "InvalidRankingOutput",
    "LockedRankingInput",
    "RANKING_MODEL",
    "RankingCheckpointError",
    "RankingService",
    "SQLRankingRepository",
]
