"""Short transactional persistence boundary for the Game Analyze pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.contracts import SteamGameSource
from app.analysis.prompts.game import (
    GAME_EXTRACTION_PROMPT_VERSION,
    GAME_SYNTHESIS_PROMPT_VERSION,
    GAME_VISUAL_PROMPT_VERSION,
)
from app.db.models.enums import AnalysisStage, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import GameProfile
from app.db.models.settings import SharedSettings
from app.integrations.errors import PermanentIntegrationError
from app.schemas.ai_game import GameSynthesis, GameVisualAnalysis
from app.schemas.profiles import public_json_object


TOTAL_GAME_ANALYSIS_UNITS = 5


class SessionFactory(Protocol):
    def __call__(self) -> Session: ...


@dataclass(frozen=True, slots=True)
class GameJobLease:
    job_id: UUID
    app_id: str
    canonical_url: str
    completed_profile_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class GameAnalysisPublication:
    source: SteamGameSource
    synthesis: GameSynthesis
    visual: GameVisualAnalysis

    def __post_init__(self) -> None:
        if not isinstance(self.source, SteamGameSource):
            raise TypeError("publication source must be a SteamGameSource")
        if not isinstance(self.synthesis, GameSynthesis):
            raise TypeError("publication synthesis must be a GameSynthesis")
        if not isinstance(self.visual, GameVisualAnalysis):
            raise TypeError("publication visual must be a GameVisualAnalysis")


class GameAnalysisService:
    """Persist Game Job progress without spanning any external operation."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def start(self, job_id: UUID) -> GameJobLease:
        with self._session_factory() as session, session.begin():
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job is None:
                raise PermanentIntegrationError("analysis_job_not_found")
            self._require_game_job(job)
            if job.status is JobStatus.SUCCEEDED:
                profile_id = self._valid_succeeded_profile_id(session, job)
                if profile_id is None:
                    raise PermanentIntegrationError("analysis_job_result_invalid")
                return GameJobLease(
                    job_id=job.id,
                    app_id=job.canonical_target_id,
                    canonical_url=job.canonical_url,
                    completed_profile_id=profile_id,
                )
            if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                raise PermanentIntegrationError("analysis_job_state_invalid")
            now = self._aware_now()
            if job.status is JobStatus.QUEUED:
                job.status = JobStatus.RUNNING
            if job.stage is None:
                job.stage = AnalysisStage.FETCHING_DATA
            job.completed_units = min(
                max(job.completed_units, 0), TOTAL_GAME_ANALYSIS_UNITS
            )
            job.total_units = TOTAL_GAME_ANALYSIS_UNITS
            if job.started_at is None:
                job.started_at = now
            return GameJobLease(
                job_id=job.id,
                app_id=job.canonical_target_id,
                canonical_url=job.canonical_url,
            )

    def advance(self, job_id: UUID, *, completed_units: int) -> None:
        if completed_units not in (2, 4):
            raise ValueError("game progress must use a documented coarse boundary")
        with self._session_factory() as session, session.begin():
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job is None:
                raise PermanentIntegrationError("analysis_job_not_found")
            self._require_game_job(job)
            if job.status is JobStatus.SUCCEEDED:
                if self._valid_succeeded_profile_id(session, job) is None:
                    raise PermanentIntegrationError("analysis_job_result_invalid")
                return
            if job.status is not JobStatus.RUNNING:
                raise PermanentIntegrationError("analysis_job_state_invalid")
            job.total_units = TOTAL_GAME_ANALYSIS_UNITS
            job.completed_units = max(job.completed_units, completed_units)
            job.completed_units = min(job.completed_units, job.total_units)
            requested_stage = (
                AnalysisStage.FINALIZING
                if completed_units == 4
                else AnalysisStage.ANALYZING
            )
            stage_order = {
                None: 0,
                AnalysisStage.FETCHING_DATA: 1,
                AnalysisStage.ANALYZING: 2,
                AnalysisStage.FINALIZING: 3,
            }
            if stage_order[requested_stage] > stage_order[job.stage]:
                job.stage = requested_stage

    def finalize(
        self,
        lease: GameJobLease,
        publication: GameAnalysisPublication,
    ) -> UUID:
        if not isinstance(lease, GameJobLease):
            raise TypeError("finalization requires a GameJobLease")
        if not isinstance(publication, GameAnalysisPublication):
            raise TypeError("finalization requires a GameAnalysisPublication")
        with self._session_factory() as session, session.begin():
            job = session.scalar(
                select(AnalysisJob)
                .where(AnalysisJob.id == lease.job_id)
                .with_for_update()
            )
            if job is None:
                raise PermanentIntegrationError("analysis_job_not_found")
            self._require_game_job(job)
            if job.canonical_target_id != lease.app_id or job.canonical_url.rstrip(
                "/"
            ) != lease.canonical_url.rstrip("/"):
                raise PermanentIntegrationError("analysis_job_identity_changed")
            if job.status is JobStatus.SUCCEEDED:
                profile_id = self._valid_succeeded_profile_id(session, job)
                if profile_id is None:
                    raise PermanentIntegrationError("analysis_job_result_invalid")
                return profile_id
            if job.status is not JobStatus.RUNNING:
                raise PermanentIntegrationError("analysis_job_state_invalid")
            if job.stage is not AnalysisStage.FINALIZING:
                raise PermanentIntegrationError("analysis_job_stage_invalid")
            if (
                publication.source.app_id != lease.app_id
                or publication.source.canonical_url.rstrip("/")
                != lease.canonical_url.rstrip("/")
            ):
                raise PermanentIntegrationError("steam_source_identity_mismatch")

            settings = session.scalar(select(SharedSettings).with_for_update())
            if settings is None:
                raise PermanentIntegrationError("shared_settings_missing")
            interval_days = self._read_game_interval(settings)
            if not 1 <= interval_days <= 90:
                raise PermanentIntegrationError("game_interval_invalid")
            analyzed_at = self._aware_now()

            profile = session.scalar(
                select(GameProfile)
                .where(GameProfile.steam_app_id == lease.app_id)
                .with_for_update()
            )
            if profile is None:
                profile = GameProfile(steam_app_id=lease.app_id)
                session.add(profile)

            source = publication.source
            current_facts = source.model_dump(mode="json", exclude={"raw"})
            synthesis = publication.synthesis.model_dump(mode="json")
            analysis = {
                key: value
                for key, value in synthesis.items()
                if key not in {"english_language_check", "game_brief"}
            }
            brief = synthesis["game_brief"]
            source_status = {
                "steam": "available",
                "visual_analysis": publication.visual.status,
            }
            model_metadata = {
                "extraction_model": "deepseek-v4-flash",
                "vision_model": "deepseek-v4-flash-vision-exp",
                "synthesis_model": "deepseek-v4-pro",
                "vision_available": publication.visual.status == "available",
            }
            prompt_metadata = {
                "extraction_prompt_version": GAME_EXTRACTION_PROMPT_VERSION,
                "visual_prompt_version": GAME_VISUAL_PROMPT_VERSION,
                "synthesis_prompt_version": GAME_SYNTHESIS_PROMPT_VERSION,
            }
            profile.canonical_url = source.canonical_url
            profile.sort_name = self._sort_name(source.name, lease.app_id)
            profile.current_facts = public_json_object(current_facts)
            profile.analysis = public_json_object(analysis)
            profile.brief = public_json_object(brief)
            profile.source_status = public_json_object(source_status)
            profile.model_metadata = public_json_object(model_metadata)
            profile.prompt_metadata = public_json_object(prompt_metadata)
            profile.last_analyzed_at = analyzed_at
            profile.next_analysis_at = analyzed_at + timedelta(days=interval_days)
            session.flush()

            job.status = JobStatus.SUCCEEDED
            job.stage = AnalysisStage.FINALIZING
            job.completed_units = TOTAL_GAME_ANALYSIS_UNITS
            job.total_units = TOTAL_GAME_ANALYSIS_UNITS
            job.profile_id = profile.id
            job.result_payload = {"profile_id": str(profile.id)}
            job.completed_at = analyzed_at
            session.flush()
            return profile.id

    @staticmethod
    def _read_game_interval(settings: SharedSettings) -> int:
        value = settings.game_interval_days
        if type(value) is not int:
            raise PermanentIntegrationError("game_interval_invalid")
        return value

    @staticmethod
    def _sort_name(name: str, app_id: str) -> str:
        normalized = name.strip() if isinstance(name, str) else ""
        if not normalized:
            normalized = f"Steam {app_id}"
        return normalized[:255]

    @staticmethod
    def _require_game_job(job: AnalysisJob) -> None:
        if job.target_type is not TargetType.GAME:
            raise PermanentIntegrationError("analysis_job_target_invalid")

    @staticmethod
    def _valid_succeeded_profile_id(session: Session, job: AnalysisJob) -> UUID | None:
        if job.profile_id is None:
            return None
        profile = session.get(GameProfile, job.profile_id)
        if profile is None or profile.steam_app_id != job.canonical_target_id:
            return None
        return profile.id

    def _aware_now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise PermanentIntegrationError("analysis_clock_invalid")
        return value.astimezone(UTC)
