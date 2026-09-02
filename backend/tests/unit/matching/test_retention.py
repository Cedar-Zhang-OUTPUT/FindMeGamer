from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
    PairwiseState,
)
from app.db.models.outreach import OutreachCampaign
from app.matching.retention import purge_expired_match_inputs
from tests.integration.test_match_publication import _pairwise, _ready_task


NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def test_purge_requires_aware_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        purge_expired_match_inputs(datetime(2026, 10, 3))


def test_purge_clears_only_terminal_expired_payloads_and_is_idempotent(
    session: Session,
) -> None:
    task, creators = _ready_task(session, count=1)
    task.status = MatchStatus.SUCCEEDED
    task.completed_units = task.total_units
    task.result_count = 1
    task.completed_at = NOW - timedelta(days=1)
    task.input_expires_at = NOW
    screening = session.scalar(
        select(MatchScreeningRecord).where(
            MatchScreeningRecord.match_task_id == task.id
        )
    )
    candidate = session.scalar(
        select(MatchCandidateInput).where(MatchCandidateInput.match_task_id == task.id)
    )
    pair = session.scalar(
        select(MatchPairwiseRecord).where(MatchPairwiseRecord.match_task_id == task.id)
    )
    assert screening is not None and candidate is not None and pair is not None
    screening.expires_at = NOW
    candidate.expires_at = NOW
    session.add(
        MatchResultItem(
            match_task_id=task.id,
            creator_id=creators[0].id,
            backend_order=0,
            match_brief=_pairwise(creators[0].id, "PRESERVED").model_dump(mode="json"),
            total_score=Decimal("0.8000"),
            dimension_scores={"hidden": 0.8},
            dimension_outcomes={
                key: "Outcome."
                for key in (
                    "content_fit",
                    "audience_fit",
                    "performance_fit",
                    "promotion_fit",
                    "brand_safety",
                )
            },
            match_reasons=["Reason."],
            result_group="recommended",
            qualitative_label="Good Match",
        )
    )
    session.add(OutreachCampaign(match_task_id=task.id))
    session.flush()

    assert purge_expired_match_inputs(NOW, database_session=session) == 1
    session.expire_all()
    task = session.get(MatchTask, task.id)
    screening = session.get(MatchScreeningRecord, screening.id)
    candidate = session.get(MatchCandidateInput, candidate.id)
    pair = session.get(MatchPairwiseRecord, pair.id)
    assert task is not None and task.locked_game_brief is None
    assert screening is not None and screening.locked_creator_brief is None
    assert candidate is not None
    assert candidate.locked_creator_profile is None
    assert candidate.input_model_metadata is None
    assert candidate.input_prompt_metadata is None
    assert pair is not None and pair.match_brief is not None
    assert (
        session.scalar(
            select(MatchResultItem).where(MatchResultItem.match_task_id == task.id)
        )
        is not None
    )
    assert (
        session.scalar(
            select(OutreachCampaign).where(OutreachCampaign.match_task_id == task.id)
        )
        is not None
    )
    assert purge_expired_match_inputs(NOW, database_session=session) == 0


def test_purge_never_clears_expired_active_or_unexpired_terminal_task(
    session: Session,
) -> None:
    expired_active, _ = _ready_task(session, count=1)
    expired_active.input_expires_at = NOW
    expired_active.stage = MatchStage.PAIRWISE
    expired_active.status = MatchStatus.RUNNING
    unexpired_terminal, _ = _ready_task(session, count=1)
    unexpired_terminal.input_expires_at = NOW + timedelta(seconds=1)
    unexpired_terminal.status = MatchStatus.FAILED
    unexpired_terminal.error_code = "deepseek_unavailable"
    unexpired_terminal.error_message = "Match is temporarily unavailable. Please retry."
    unexpired_terminal.retryable = True
    unexpired_terminal.completed_at = NOW
    session.flush()
    assert purge_expired_match_inputs(NOW, database_session=session) == 0
    assert session.get(MatchTask, expired_active.id).locked_game_brief is not None
    assert session.get(MatchTask, unexpired_terminal.id).locked_game_brief is not None
