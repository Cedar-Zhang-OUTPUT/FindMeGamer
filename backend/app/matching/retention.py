"""Transactional retention cleanup for terminal Match input snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.database import session_scope
from app.db.models.match import (
    MatchCandidateInput,
    MatchScreeningRecord,
    MatchScreeningCheckpoint,
    MatchStatus,
    MatchTask,
)
from app.workers.celery_app import celery_app


MATCH_RETENTION_TASK_NAME = "find_me_gamer.match.purge_expired_inputs"


def _aware_utc(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Match retention requires an aware datetime")
    return now.astimezone(UTC)


def _purge(session: Session, now: datetime) -> int:
    tasks = session.scalars(
        select(MatchTask)
        .where(
            MatchTask.status.in_(
                (MatchStatus.SUCCEEDED, MatchStatus.FAILED, MatchStatus.SUPERSEDED)
            ),
            MatchTask.input_expires_at <= now,
        )
        .with_for_update()
    ).all()
    changed = 0
    for task in tasks:
        task_changed = task.locked_game_brief is not None
        task.locked_game_brief = None
        removed = session.execute(
            delete(MatchScreeningCheckpoint).where(
                MatchScreeningCheckpoint.match_task_id == task.id
            )
        )
        task_changed = bool(removed.rowcount) or task_changed
        screenings = session.scalars(
            select(MatchScreeningRecord)
            .where(MatchScreeningRecord.match_task_id == task.id)
            .with_for_update()
        ).all()
        for row in screenings:
            task_changed = task_changed or row.locked_creator_brief is not None
            row.locked_creator_brief = None
        candidates = session.scalars(
            select(MatchCandidateInput)
            .where(MatchCandidateInput.match_task_id == task.id)
            .with_for_update()
        ).all()
        for row in candidates:
            task_changed = task_changed or any(
                value is not None
                for value in (
                    row.locked_creator_profile,
                    row.input_model_metadata,
                    row.input_prompt_metadata,
                )
            )
            row.locked_creator_profile = None
            row.input_model_metadata = None
            row.input_prompt_metadata = None
        changed += int(task_changed)
    session.flush()
    return changed


def purge_expired_match_inputs(
    now: datetime, *, database_session: Session | None = None
) -> int:
    normalized = _aware_utc(now)
    if database_session is not None:
        return _purge(database_session, normalized)
    with session_scope() as session:
        try:
            changed = _purge(session, normalized)
            session.commit()
            return changed
        except Exception:
            session.rollback()
            raise


@celery_app.task(name=MATCH_RETENTION_TASK_NAME, ignore_result=True)
def purge_expired_match_inputs_task() -> int:
    return purge_expired_match_inputs(datetime.now(UTC))


__all__ = [
    "MATCH_RETENTION_TASK_NAME",
    "purge_expired_match_inputs",
    "purge_expired_match_inputs_task",
]
