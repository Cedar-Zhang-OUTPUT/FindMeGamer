"""Short transactional persistence boundaries for Profile Analyze pipelines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.contracts import CreatorSource, SteamGameSource, VideoSource
from app.analysis.creator_metrics import CreatorComputedMetrics
from app.analysis.prompts.creator import (
    CREATOR_METADATA_PROMPT_VERSION,
    CREATOR_SYNTHESIS_PROMPT_VERSION,
    CREATOR_VISUAL_PROMPT_VERSION,
)
from app.analysis.prompts.game import (
    GAME_EXTRACTION_PROMPT_VERSION,
    GAME_SYNTHESIS_PROMPT_VERSION,
    GAME_VISUAL_PROMPT_VERSION,
)
from app.core.analysis_job_contract import valid_analysis_job_state
from app.db.models.enums import AnalysisStage, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob, acquire_job_change_lock
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.db.models.settings import SharedSettings
from app.integrations.errors import PermanentIntegrationError
from app.repositories.jobs import require_valid_succeeded_job_result
from app.repositories.settings import SHARED_SETTINGS_ID
from app.schemas.ai_game import GameSynthesis, GameVisualAnalysis
from app.schemas.ai_creator import (
    BoundCreatorContacts,
    CreatorContactEvidence,
    CreatorSynthesis,
    CreatorVisualAnalysis,
    EmailContactCandidate,
)
from app.schemas.profiles import public_json_object


TOTAL_GAME_ANALYSIS_UNITS = 5
TOTAL_CREATOR_ANALYSIS_UNITS = 5


def _require_valid_job_state(job: AnalysisJob) -> None:
    if not valid_analysis_job_state(
        status=job.status,
        stage=job.stage,
        completed_units=job.completed_units,
        total_units=job.total_units,
        error_code=job.error_code,
        error_message=job.error_message,
        retryable=job.retryable,
        profile_id=job.profile_id,
        result_present=job.result_payload is not None,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    ):
        raise PermanentIntegrationError("analysis_job_state_invalid")


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
            acquire_job_change_lock(session)
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job is None:
                raise PermanentIntegrationError("analysis_job_not_found")
            self._require_game_job(job)
            if job.status is JobStatus.SUCCEEDED:
                profile_id = self._valid_succeeded_profile_id(session, job)
                _require_valid_job_state(job)
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
            _require_valid_job_state(job)
            if job.status is JobStatus.QUEUED:
                now = self._aware_now()
                job.status = JobStatus.RUNNING
                job.stage = AnalysisStage.FETCHING_DATA
                job.completed_units = 0
                job.total_units = TOTAL_GAME_ANALYSIS_UNITS
                job.started_at = now
            _require_valid_job_state(job)
            return GameJobLease(
                job_id=job.id,
                app_id=job.canonical_target_id,
                canonical_url=job.canonical_url,
            )

    def advance(self, job_id: UUID, *, completed_units: int) -> None:
        if completed_units not in (2, 4):
            raise ValueError("game progress must use a documented coarse boundary")
        with self._session_factory() as session, session.begin():
            acquire_job_change_lock(session)
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job is None:
                raise PermanentIntegrationError("analysis_job_not_found")
            self._require_game_job(job)
            if job.status is JobStatus.SUCCEEDED:
                if self._valid_succeeded_profile_id(session, job) is None:
                    raise PermanentIntegrationError("analysis_job_result_invalid")
                _require_valid_job_state(job)
                return
            if job.status is not JobStatus.RUNNING:
                raise PermanentIntegrationError("analysis_job_state_invalid")
            job.completed_units = max(job.completed_units, completed_units)
            job.completed_units = min(job.completed_units, job.total_units - 1)
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
            _require_valid_job_state(job)

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
            acquire_job_change_lock(session)
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
                _require_valid_job_state(job)
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
                "extraction_model": "deepseek-flash",
                "vision_model": "deepseek-flash",
                "synthesis_model": "deepseek-flash",
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
            profile.profile_revision = (profile.profile_revision or 0) + 1
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
            job.completed_units = job.total_units
            job.profile_id = profile.id
            job.result_payload = {"profile_id": str(profile.id)}
            job.completed_at = analyzed_at
            job.error_code = None
            job.error_message = None
            job.retryable = False
            _require_valid_job_state(job)
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
        require_valid_succeeded_job_result(session, job)
        return job.profile_id

    def _aware_now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise PermanentIntegrationError("analysis_clock_invalid")
        return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CreatorJobLease:
    job_id: UUID
    channel_id: str
    canonical_url: str
    completed_profile_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreatorAnalysisPublication:
    source: CreatorSource
    synthesis: CreatorSynthesis
    visual: CreatorVisualAnalysis
    contacts: BoundCreatorContacts
    contact_evidence: CreatorContactEvidence
    contact_status: str
    metrics: CreatorComputedMetrics
    representative_videos: tuple[VideoSource, ...]

    def __post_init__(self) -> None:
        expected = (
            (self.source, CreatorSource),
            (self.synthesis, CreatorSynthesis),
            (self.visual, CreatorVisualAnalysis),
            (self.contacts, BoundCreatorContacts),
            (self.contact_evidence, CreatorContactEvidence),
            (self.metrics, CreatorComputedMetrics),
        )
        if any(
            not isinstance(value, expected_type) for value, expected_type in expected
        ):
            raise TypeError("invalid Creator publication value")
        if self.contact_status not in {"available", "partial", "unavailable"}:
            raise ValueError("invalid contact discovery status")
        if (
            not isinstance(self.representative_videos, tuple)
            or len(self.representative_videos) > 12
            or not all(
                isinstance(video, VideoSource) for video in self.representative_videos
            )
        ):
            raise TypeError("invalid representative videos")


class CreatorAnalysisService:
    """Persist Creator Job progress and publication in short transactions."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def start(self, job_id: UUID) -> CreatorJobLease:
        with self._session_factory() as session, session.begin():
            acquire_job_change_lock(session)
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job is None:
                raise PermanentIntegrationError("analysis_job_not_found")
            self._require_creator_job(job)
            if job.status is JobStatus.SUCCEEDED:
                profile_id = self._valid_succeeded_profile_id(session, job)
                _require_valid_job_state(job)
                if profile_id is None:
                    raise PermanentIntegrationError("analysis_job_result_invalid")
                return CreatorJobLease(
                    job_id=job.id,
                    channel_id=job.canonical_target_id,
                    canonical_url=job.canonical_url,
                    completed_profile_id=profile_id,
                )
            if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                raise PermanentIntegrationError("analysis_job_state_invalid")
            _require_valid_job_state(job)
            if job.status is JobStatus.QUEUED:
                now = self._aware_now()
                job.status = JobStatus.RUNNING
                job.stage = AnalysisStage.FETCHING_DATA
                job.completed_units = 0
                job.total_units = TOTAL_CREATOR_ANALYSIS_UNITS
                job.started_at = now
            _require_valid_job_state(job)
            return CreatorJobLease(
                job_id=job.id,
                channel_id=job.canonical_target_id,
                canonical_url=job.canonical_url,
            )

    def advance(self, job_id: UUID, *, completed_units: int) -> None:
        if completed_units not in (2, 4):
            raise ValueError("creator progress must use a documented coarse boundary")
        with self._session_factory() as session, session.begin():
            acquire_job_change_lock(session)
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job is None:
                raise PermanentIntegrationError("analysis_job_not_found")
            self._require_creator_job(job)
            if job.status is JobStatus.SUCCEEDED:
                if self._valid_succeeded_profile_id(session, job) is None:
                    raise PermanentIntegrationError("analysis_job_result_invalid")
                _require_valid_job_state(job)
                return
            if job.status is not JobStatus.RUNNING:
                raise PermanentIntegrationError("analysis_job_state_invalid")
            job.completed_units = min(
                max(job.completed_units, completed_units), job.total_units - 1
            )
            requested_stage = (
                AnalysisStage.FINALIZING
                if completed_units == 4
                else AnalysisStage.ANALYZING
            )
            order = {
                None: 0,
                AnalysisStage.FETCHING_DATA: 1,
                AnalysisStage.ANALYZING: 2,
                AnalysisStage.FINALIZING: 3,
            }
            if order[requested_stage] > order[job.stage]:
                job.stage = requested_stage
            _require_valid_job_state(job)

    def finalize(
        self,
        lease: CreatorJobLease,
        publication: CreatorAnalysisPublication,
    ) -> UUID:
        if not isinstance(lease, CreatorJobLease) or not isinstance(
            publication, CreatorAnalysisPublication
        ):
            raise TypeError("invalid Creator finalization input")
        with self._session_factory() as session, session.begin():
            acquire_job_change_lock(session)
            job = session.scalar(
                select(AnalysisJob)
                .where(AnalysisJob.id == lease.job_id)
                .with_for_update()
            )
            if job is None:
                raise PermanentIntegrationError("analysis_job_not_found")
            self._require_creator_job(job)
            if job.canonical_target_id != lease.channel_id or job.canonical_url.rstrip(
                "/"
            ) != lease.canonical_url.rstrip("/"):
                raise PermanentIntegrationError("analysis_job_identity_changed")
            if job.status is JobStatus.SUCCEEDED:
                profile_id = self._valid_succeeded_profile_id(session, job)
                _require_valid_job_state(job)
                if profile_id is None:
                    raise PermanentIntegrationError("analysis_job_result_invalid")
                return profile_id
            if job.status is not JobStatus.RUNNING:
                raise PermanentIntegrationError("analysis_job_state_invalid")
            if job.stage is not AnalysisStage.FINALIZING:
                raise PermanentIntegrationError("analysis_job_stage_invalid")
            source = publication.source
            if source.channel_id != lease.channel_id or source.canonical_url.rstrip(
                "/"
            ) != lease.canonical_url.rstrip("/"):
                raise PermanentIntegrationError("youtube_source_identity_mismatch")

            settings = session.scalar(
                select(SharedSettings)
                .where(SharedSettings.id == SHARED_SETTINGS_ID)
                .with_for_update()
            )
            if settings is None:
                raise PermanentIntegrationError("shared_settings_missing")
            interval_days = self._read_creator_interval(settings)
            if type(interval_days) is not int or not 1 <= interval_days <= 30:
                raise PermanentIntegrationError("creator_interval_invalid")
            analyzed_at = self._aware_now()
            profile = session.scalar(
                select(CreatorProfile)
                .where(
                    CreatorProfile.platform == "youtube",
                    CreatorProfile.platform_account_id == lease.channel_id,
                )
                .with_for_update()
            )
            if profile is None:
                profile = CreatorProfile(
                    id=uuid4(),
                    youtube_channel_id=lease.channel_id,
                    platform="youtube",
                    platform_account_id=lease.channel_id,
                    canonical_url=source.canonical_url,
                    sort_name=self._sort_name(source.title, lease.channel_id),
                )
                session.add(profile)

            current_facts = self._current_facts(publication)
            synthesis = publication.synthesis.model_dump(mode="json")
            analysis = {
                key: value
                for key, value in synthesis.items()
                if key
                not in {
                    "english_language_check",
                    "creator_brief",
                    "public_email",
                    "linked_site",
                    "social_links",
                }
            }
            analysis["public_contact"] = self._public_contact(
                publication.contacts, publication.contact_evidence
            )
            profile.canonical_url = source.canonical_url
            profile.sort_name = self._sort_name(source.title, lease.channel_id)
            profile.current_facts = public_json_object(current_facts)
            profile.profile_revision = (profile.profile_revision or 0) + 1
            profile.analysis = public_json_object(analysis)
            profile.brief = public_json_object(synthesis["creator_brief"])
            profile.source_status = public_json_object(
                {
                    "youtube": "available",
                    "visual_analysis": publication.visual.status,
                    "contact_discovery": publication.contact_status,
                    "freshness": "current",
                }
            )
            profile.model_metadata = public_json_object(
                {
                    "metadata_model": "deepseek-flash",
                    "vision_model": "deepseek-flash",
                    "synthesis_model": "deepseek-flash",
                    "vision_available": publication.visual.status == "available",
                }
            )
            profile.prompt_metadata = public_json_object(
                {
                    "metadata_prompt_version": CREATOR_METADATA_PROMPT_VERSION,
                    "visual_prompt_version": CREATOR_VISUAL_PROMPT_VERSION,
                    "synthesis_prompt_version": CREATOR_SYNTHESIS_PROMPT_VERSION,
                }
            )
            profile.last_analyzed_at = analyzed_at
            profile.next_analysis_at = analyzed_at + timedelta(days=interval_days)

            session.execute(
                delete(CreatorContact).where(
                    CreatorContact.creator_id == profile.id,
                    CreatorContact.is_manual.is_(False),
                )
            )
            selected_email = publication.contacts.public_email
            discovered_emails = [
                candidate
                for candidate in publication.contact_evidence.candidates
                if isinstance(candidate, EmailContactCandidate)
            ]
            seen_emails: set[str] = set()
            for position, discovered_email in enumerate(discovered_emails):
                email_key = discovered_email.value.casefold()
                if email_key in seen_emails:
                    continue
                seen_emails.add(email_key)
                session.add(
                    CreatorContact(
                        creator_id=profile.id,
                        email=discovered_email.value,
                        purpose=discovered_email.purpose,
                        source_type=discovered_email.source_type,
                        source_url=discovered_email.source_url,
                        is_manual=False,
                        validation_state=(
                            "valid"
                            if discovered_email.validation_state == "validated"
                            else "unverified"
                        ),
                        priority=(
                            10
                            if selected_email is not None
                            and discovered_email.candidate_id
                            == selected_email.candidate_id
                            else max(1, 9 - position)
                        ),
                        is_active=True,
                    )
                )
            session.flush()

            job.status = JobStatus.SUCCEEDED
            job.stage = AnalysisStage.FINALIZING
            job.completed_units = job.total_units
            job.profile_id = profile.id
            job.result_payload = {"profile_id": str(profile.id)}
            job.completed_at = analyzed_at
            job.error_code = None
            job.error_message = None
            job.retryable = False
            _require_valid_job_state(job)
            session.flush()
            return profile.id

    @staticmethod
    def _current_facts(publication: CreatorAnalysisPublication) -> dict[str, object]:
        source = publication.source
        return {
            "channel_id": source.channel_id,
            "canonical_url": source.canonical_url,
            "title": source.title,
            "description": source.description,
            "custom_url": source.custom_url,
            "published_at": (
                source.published_at.isoformat() if source.published_at else None
            ),
            "country": source.country,
            "avatar_url": source.thumbnail_urls[0] if source.thumbnail_urls else None,
            "banner_url": source.banner_url,
            "subscriber_count": source.subscriber_count,
            "hidden_subscriber_count": source.hidden_subscriber_count,
            "total_view_count": source.total_view_count,
            "public_video_count": source.public_video_count,
            "recent_metrics": publication.metrics.model_dump(mode="json"),
            "representative_videos": [
                {
                    "id": video.id,
                    "title": video.title,
                    "published_at": (
                        video.published_at.isoformat() if video.published_at else None
                    ),
                    "duration_seconds": video.duration_seconds,
                    "view_count": video.view_count,
                    "like_count": video.like_count,
                    "comment_count": video.comment_count,
                    "thumbnail_url": (
                        video.thumbnail_urls[0] if video.thumbnail_urls else None
                    ),
                }
                for video in publication.representative_videos
            ],
        }

    @staticmethod
    def _public_contact(
        contacts: BoundCreatorContacts, evidence: CreatorContactEvidence
    ) -> dict[str, object]:
        def project(candidate):
            if candidate is None:
                return None
            projected = {
                "value": candidate.value,
                "source_type": candidate.source_type,
                "source_url": candidate.source_url,
                "validation_state": candidate.validation_state,
            }
            if isinstance(candidate, EmailContactCandidate):
                projected["purpose"] = candidate.purpose
            return projected

        emails = [
            project(candidate)
            for candidate in evidence.candidates
            if isinstance(candidate, EmailContactCandidate)
        ]

        return {
            "email": project(contacts.public_email),
            "emails": emails,
            "linked_site": project(contacts.linked_site),
            "social_links": [project(candidate) for candidate in contacts.social_links],
        }

    @staticmethod
    def _read_creator_interval(settings: SharedSettings) -> int:
        value = settings.creator_interval_days
        if type(value) is not int or not 1 <= value <= 30:
            raise PermanentIntegrationError("creator_interval_invalid")
        return value

    @staticmethod
    def _sort_name(title: str, channel_id: str) -> str:
        normalized = title.strip() if isinstance(title, str) else ""
        if not normalized:
            normalized = f"YouTube {channel_id}"
        return normalized[:255]

    @staticmethod
    def _require_creator_job(job: AnalysisJob) -> None:
        if job.target_type is not TargetType.CREATOR:
            raise PermanentIntegrationError("analysis_job_target_invalid")

    @staticmethod
    def _valid_succeeded_profile_id(session: Session, job: AnalysisJob) -> UUID | None:
        require_valid_succeeded_job_result(session, job)
        return job.profile_id

    def _aware_now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise PermanentIntegrationError("analysis_clock_invalid")
        return value.astimezone(UTC)
