"""Transactional persistence for immutable Match screening inputs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import random
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.match import (
    MatchCandidateInput,
    MatchScreeningRecord,
    MatchScreeningCheckpoint,
    MatchStage,
    MatchStatus,
    MatchTask,
)
from app.db.models.profiles import CreatorProfile, GameProfile
from app.db.models.outreach import OutreachCampaign
from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import ScreeningSelection
from app.schemas.profiles import public_json_object
from app.services.profile_editing import manual_context


if TYPE_CHECKING:
    from app.matching.screening import LockedScreeningInput


MATCH_INPUT_RETENTION = timedelta(days=30)
MIN_SIGNED_BIGINT = -(2**63)
MAX_SIGNED_BIGINT = 2**63 - 1


class MatchInputError(ValueError):
    """A Match cannot safely use the requested persisted input."""


def stable_shuffled_creator_ids(
    creator_ids: Iterable[UUID],
    *,
    seed: int,
) -> list[UUID]:
    """Shuffle a UUID set from a stable baseline without global RNG state."""

    if type(seed) is not int or not MIN_SIGNED_BIGINT <= seed <= MAX_SIGNED_BIGINT:
        raise ValueError("shuffle seed must be a signed 64-bit integer")
    values = list(creator_ids)
    if any(type(creator_id) is not UUID for creator_id in values):
        raise TypeError("creator IDs must be UUID values")
    if len(values) != len(set(values)):
        raise ValueError("creator IDs must be unique")
    values.sort(key=lambda creator_id: creator_id.int)
    random.Random(seed).shuffle(values)
    return values


class MatchRepository:
    """Own short Match transactions while callers own commit boundaries."""

    def __init__(
        self,
        database_session: Session,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = database_session
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_locked_task(
        self,
        game_id: UUID,
        seed: int,
        threshold: Decimal,
    ) -> MatchTask:
        """Freeze the Game and all eligible Creator inputs in one transaction."""

        if type(game_id) is not UUID:
            raise TypeError("game id must be a UUID")
        if type(seed) is not int or not MIN_SIGNED_BIGINT <= seed <= MAX_SIGNED_BIGINT:
            raise ValueError("shuffle seed must be a signed 64-bit integer")
        if not isinstance(threshold, Decimal) or not Decimal(
            "0"
        ) <= threshold <= Decimal("1"):
            raise ValueError("recommended threshold must be a Decimal from zero to one")

        now = self._aware_now()
        expires_at = now + MATCH_INPUT_RETENTION
        game = self._session.scalar(
            select(GameProfile)
            .where(GameProfile.id == game_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if game is None:
            raise MatchInputError("game_profile_not_found")
        try:
            game_brief = GameBrief.model_validate(game.brief)
        except Exception:
            raise MatchInputError("game_brief_invalid") from None

        creators = self._session.scalars(
            select(CreatorProfile)
            .order_by(CreatorProfile.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        eligible: dict[UUID, tuple[CreatorProfile, CreatorBrief]] = {}
        cutoff = now - MATCH_INPUT_RETENTION
        for creator in creators:
            brief = self._eligible_creator_brief(creator, cutoff=cutoff)
            if brief is not None:
                eligible[creator.id] = (creator, brief)

        task = MatchTask(
            game_id=game.id,
            locked_game_brief=deepcopy(game_brief.model_dump(mode="json")),
            locked_game_context=manual_context(game),
            shuffle_seed=seed,
            recommended_match_threshold=threshold,
            status=MatchStatus.QUEUED,
            stage=MatchStage.SCREENING,
            completed_units=0,
            total_units=0,
            result_count=0,
            retryable=False,
            input_expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        self._session.add(task)
        self._session.flush()

        ordered_creator_ids = stable_shuffled_creator_ids(eligible, seed=seed)
        for screening_order, creator_id in enumerate(ordered_creator_ids):
            creator, creator_brief = eligible[creator_id]
            serialized_brief = deepcopy(creator_brief.model_dump(mode="json"))
            self._session.add(
                MatchScreeningRecord(
                    match_task_id=task.id,
                    creator_id=creator.id,
                    screening_order=screening_order,
                    locked_creator_brief=serialized_brief,
                    locked_manual_context=manual_context(creator),
                    selected=False,
                    expires_at=expires_at,
                    created_at=now,
                    updated_at=now,
                )
            )
        self._session.flush()
        for creator_id in ordered_creator_ids:
            creator, creator_brief = eligible[creator_id]
            self._session.add(
                MatchCandidateInput(
                    match_task_id=task.id,
                    creator_id=creator.id,
                    locked_creator_profile=self._creator_snapshot(
                        creator,
                        creator_brief=creator_brief,
                    ),
                    input_model_metadata=self._match_relevant_json(
                        creator.model_metadata
                    ),
                    input_prompt_metadata=self._match_relevant_json(
                        creator.prompt_metadata
                    ),
                    expires_at=expires_at,
                    created_at=now,
                    updated_at=now,
                )
            )
        self._session.flush()
        return task

    def load_locked_screening_input(self, match_task_id: UUID) -> LockedScreeningInput:
        """Lock briefly, start screening if needed, and return frozen inputs."""

        from app.matching.screening import (  # local import avoids a module cycle
            LockedScreeningCreator,
            LockedScreeningInput,
        )

        if type(match_task_id) is not UUID:
            raise TypeError("match task id must be a UUID")
        task = self._session.scalar(
            select(MatchTask).where(MatchTask.id == match_task_id).with_for_update()
        )
        if task is None:
            raise MatchInputError("match_task_not_found")
        if task.status in (MatchStatus.FAILED, MatchStatus.SUPERSEDED):
            raise MatchInputError("match_task_not_screenable")

        records = self._session.scalars(
            select(MatchScreeningRecord)
            .where(MatchScreeningRecord.match_task_id == task.id)
            .order_by(MatchScreeningRecord.screening_order)
            .with_for_update()
        ).all()
        selected_ids = tuple(record.creator_id for record in records if record.selected)
        already_applied = (
            task.stage is not MatchStage.SCREENING
            or task.status is MatchStatus.SUCCEEDED
        )
        if already_applied:
            return LockedScreeningInput(
                task_id=task.id,
                game_brief=self._validated_game_brief(task.locked_game_brief),
                creators=(),
                applied_creator_ids=selected_ids,
            )
        if task.status not in (MatchStatus.QUEUED, MatchStatus.RUNNING):
            raise MatchInputError("match_task_not_screenable")

        candidate_ids = set(
            self._session.scalars(
                select(MatchCandidateInput.creator_id)
                .where(MatchCandidateInput.match_task_id == task.id)
                .with_for_update()
            )
        )
        record_ids = {record.creator_id for record in records}
        if candidate_ids != record_ids:
            raise MatchInputError("match_candidate_snapshot_invalid")
        creators = tuple(
            LockedScreeningCreator(
                creator_id=record.creator_id,
                brief=self._validated_creator_brief(record.locked_creator_brief),
                manual_context=deepcopy(record.locked_manual_context),
            )
            for record in records
        )
        if task.status is MatchStatus.QUEUED:
            now = self._aware_now()
            task.status = MatchStatus.RUNNING
            task.started_at = now
            task.updated_at = now
            self._session.flush()
        return LockedScreeningInput(
            task_id=task.id,
            game_brief=self._validated_game_brief(task.locked_game_brief),
            creators=creators,
            applied_creator_ids=None,
            game_manual_context=deepcopy(task.locked_game_context),
            checkpoints={
                row.request_hash: tuple(
                    ScreeningSelection.model_validate_json(json.dumps(value))
                    for value in row.selections
                )
                for row in self._session.scalars(
                    select(MatchScreeningCheckpoint).where(
                        MatchScreeningCheckpoint.match_task_id == task.id
                    )
                )
            },
        )

    def save_screening_checkpoint(self, match_task_id, key, selections):
        task = self._session.scalar(
            select(MatchTask).where(MatchTask.id == match_task_id).with_for_update()
        )
        if (
            task is None
            or task.stage != MatchStage.SCREENING
            or task.status != MatchStatus.RUNNING
        ):
            raise MatchInputError("match_task_not_screenable")
        existing = self._session.get(MatchScreeningCheckpoint, (match_task_id, key))
        if existing is not None:
            return tuple(
                ScreeningSelection.model_validate_json(json.dumps(value))
                for value in existing.selections
            )
        self._session.add(
            MatchScreeningCheckpoint(
                match_task_id=match_task_id,
                request_hash=key,
                selections=[
                    selection.model_dump(mode="json") for selection in selections
                ],
            )
        )
        self._session.flush()
        return tuple(selections)

    def apply_screening_output(
        self,
        match_task_id: UUID,
        selections: Sequence[ScreeningSelection],
    ) -> list[UUID]:
        """Atomically apply one complete screening result and prune snapshots."""

        if type(match_task_id) is not UUID:
            raise TypeError("match task id must be a UUID")
        selection_tuple = tuple(selections)
        if len(selection_tuple) > 30 or any(
            not isinstance(item, ScreeningSelection) for item in selection_tuple
        ):
            raise MatchInputError("screening_output_invalid")
        selection_ids = [item.creator_id for item in selection_tuple]
        if len(selection_ids) != len(set(selection_ids)):
            raise MatchInputError("screening_output_invalid")

        task = self._session.scalar(
            select(MatchTask).where(MatchTask.id == match_task_id).with_for_update()
        )
        if task is None:
            raise MatchInputError("match_task_not_found")
        records = self._session.scalars(
            select(MatchScreeningRecord)
            .where(MatchScreeningRecord.match_task_id == task.id)
            .order_by(MatchScreeningRecord.screening_order)
            .with_for_update()
        ).all()
        persisted_selection = [
            record.creator_id for record in records if record.selected
        ]
        if (
            task.stage is not MatchStage.SCREENING
            or task.status is MatchStatus.SUCCEEDED
        ):
            return persisted_selection
        if task.status not in (MatchStatus.QUEUED, MatchStatus.RUNNING):
            raise MatchInputError("match_task_not_screenable")

        records_by_creator = {record.creator_id: record for record in records}
        if not set(selection_ids) <= records_by_creator.keys():
            raise MatchInputError("screening_output_unknown_creator")
        candidate_ids = set(
            self._session.scalars(
                select(MatchCandidateInput.creator_id)
                .where(MatchCandidateInput.match_task_id == task.id)
                .with_for_update()
            )
        )
        if not set(selection_ids) <= candidate_ids:
            raise MatchInputError("selected_candidate_snapshot_missing")

        decisions = {item.creator_id: item for item in selection_tuple}
        for record in records:
            selection = decisions.get(record.creator_id)
            if selection is None:
                continue
            record.selected = True
            record.screening_reason = json.dumps(
                {
                    "reason": selection.screening_reason,
                    "evidence": list(selection.evidence),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )

        keep_ids = set(selection_ids)
        delete_statement = delete(MatchCandidateInput).where(
            MatchCandidateInput.match_task_id == task.id
        )
        if keep_ids:
            delete_statement = delete_statement.where(
                MatchCandidateInput.creator_id.not_in(keep_ids)
            )
        self._session.execute(delete_statement)

        now = self._aware_now()
        task.started_at = task.started_at or now
        task.updated_at = now
        task.result_count = 0
        if keep_ids:
            task.status = MatchStatus.RUNNING
            task.stage = MatchStage.PAIRWISE
            task.completed_units = 1
            task.total_units = len(keep_ids) + 2
            task.completed_at = None
        else:
            task.status = MatchStatus.SUCCEEDED
            task.stage = MatchStage.SCREENING
            task.completed_units = 1
            task.total_units = 1
            task.completed_at = now
            campaign = self._session.scalar(
                select(OutreachCampaign).where(
                    OutreachCampaign.match_task_id == task.id
                )
            )
            if campaign is None:
                self._session.add(OutreachCampaign(match_task_id=task.id))
        self._session.flush()
        return [
            record.creator_id for record in records if record.creator_id in keep_ids
        ]

    def _eligible_creator_brief(
        self,
        creator: CreatorProfile,
        *,
        cutoff: datetime,
    ) -> CreatorBrief | None:
        if creator.last_analyzed_at is None or creator.last_analyzed_at < cutoff:
            return None
        if creator.platform in {"twitch", "instagram"}:
            from app.schemas.creator_import import CreatorImportRecord

            provenance = creator.source_status.get("curated_import", {})
            if provenance != {
                "status": "available",
                "schema_version": 1,
                "platform": creator.platform,
                "platform_account_id": creator.platform_account_id,
            }:
                return None
            if creator.source_status.get("freshness") != "current":
                return None
            try:
                material = CreatorImportRecord.model_validate(
                    {
                        **creator.current_facts["curated_collection"],
                        "analysis": {
                            "analyzed_at": creator.last_analyzed_at,
                            "synthesis": creator.analysis,
                        },
                    }
                )
                if (
                    material.platform != creator.platform
                    or material.platform_account_id != creator.platform_account_id
                    or material.profile_url != creator.canonical_url
                    or material.analysis.synthesis.creator_brief.model_dump(mode="json")
                    != creator.brief
                ):
                    return None
                return material.analysis.synthesis.creator_brief
            except Exception:
                return None
        if not self._youtube_source_is_current(
            creator.source_status, platform=creator.platform
        ):
            return None
        try:
            return CreatorBrief.model_validate(creator.brief)
        except Exception:
            return None

    @staticmethod
    def _youtube_source_is_current(
        source_status: object, *, platform: str = "youtube"
    ) -> bool:
        if (
            not isinstance(source_status, dict)
            or source_status.get("seed") == "incomplete"
        ):
            return False

        def status(value: object) -> str | None:
            if isinstance(value, str):
                return value.casefold()
            if isinstance(value, dict) and isinstance(value.get("status"), str):
                return value["status"].casefold()
            return None

        youtube = (
            status(source_status.get(platform))
            if platform in {"youtube", "x"}
            else None
        )
        freshness = status(source_status.get("freshness"))
        if freshness is not None and freshness != "current":
            return False
        return youtube == "current" or (
            youtube == "available" and freshness == "current"
        )

    @staticmethod
    def _creator_snapshot(
        creator: CreatorProfile,
        *,
        creator_brief: CreatorBrief,
    ) -> dict[str, object]:
        return deepcopy(
            {
                "id": str(creator.id),
                "youtube_channel_id": creator.youtube_channel_id,
                "platform": creator.platform,
                "platform_account_id": creator.platform_account_id,
                "canonical_url": creator.canonical_url,
                "current_facts": MatchRepository._match_relevant_json(
                    creator.current_facts
                ),
                "analysis": MatchRepository._match_relevant_json(creator.analysis),
                "brief": creator_brief.model_dump(mode="json"),
                "manual_context": manual_context(creator),
            }
        )

    @staticmethod
    def _match_relevant_json(value: object) -> object:
        """Deep-copy JSON while dropping non-fit and secret-bearing subtrees."""

        forbidden_key_parts = (
            "contact",
            "credential",
            "email",
            "favorite",
            "manualnote",
            "nextanalysis",
            "outreach",
            "password",
            "response",
            "schedule",
            "scheduling",
            "secret",
            "token",
        )
        if isinstance(value, dict):
            value = public_json_object(value)
            projected: dict[str, object] = {}
            for key, item in value.items():
                normalized_key = "".join(
                    character.casefold() for character in key if character.isalnum()
                )
                if any(part in normalized_key for part in forbidden_key_parts):
                    continue
                projected[key] = MatchRepository._match_relevant_json(item)
            return projected
        if isinstance(value, list):
            return [MatchRepository._match_relevant_json(item) for item in value]
        return deepcopy(value)

    @staticmethod
    def _validated_game_brief(value: object) -> GameBrief:
        try:
            return GameBrief.model_validate(value)
        except Exception:
            raise MatchInputError("locked_game_brief_invalid") from None

    @staticmethod
    def _validated_creator_brief(value: object) -> CreatorBrief:
        try:
            return CreatorBrief.model_validate(value)
        except Exception:
            raise MatchInputError("locked_creator_brief_invalid") from None

    def _aware_now(self) -> datetime:
        now = self._clock()
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ValueError("Match clock must return an aware datetime")
        return now.astimezone(UTC)


__all__ = [
    "MATCH_INPUT_RETENTION",
    "MatchInputError",
    "MatchRepository",
    "stable_shuffled_creator_ids",
]
