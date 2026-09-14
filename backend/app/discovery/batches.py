"""Durable batch transitions; external publication happens only after commit."""

from datetime import UTC, datetime
from decimal import Decimal
import secrets

from sqlalchemy import select, func

from app.analysis.targets import canonicalize_target
from app.db.models.discover import DiscoverCandidate, DiscoverJob
from app.db.models.discover_batch import DiscoverAnalysisItem
from app.db.models.enums import JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob, acquire_job_change_lock
from app.db.models.profiles import CreatorProfile
from app.db.models.match import MatchTask, MatchStatus, MatchCandidateInput
from app.discovery.service import PUBLICATION_RETRY
from app.repositories.discover_batch import DiscoverBatchRepository
from app.repositories.jobs import JobsRepository, require_valid_succeeded_job_result
from app.repositories.match import (
    MatchRepository,
    MatchInputError,
    MATCH_INPUT_RETENTION,
)
from app.repositories.settings import SettingsRepository
from app.workers.match_tasks import START_MATCH_TASK_NAME


class DiscoverBatchService:
    def __init__(
        self, *, session_factory, analysis_dispatcher, match_dispatcher, clock=None
    ):
        self.sessions = session_factory
        self.analysis_dispatcher = analysis_dispatcher
        self.match_dispatcher = match_dispatcher
        self.clock = clock or (lambda: datetime.now(UTC))

    def execute(self, batch_id):
        dispatch_ids = []
        match_dispatch_id = None
        with self.sessions() as session:
            acquire_job_change_lock(session)
            repo = DiscoverBatchRepository(session)
            batch = repo.get(batch_id, lock=True)
            if batch is None:
                session.commit()
                return
            if batch.status in {"queued", "running"}:
                batch.status = "running"
                items = repo.items(batch_id)
                for item in items:
                    if item.status in {"succeeded", "failed"}:
                        continue
                    dispatch_id = self._advance_item(session, batch, item)
                    if dispatch_id:
                        dispatch_ids.append(dispatch_id)
                if all(item.status in {"succeeded", "failed"} for item in items):
                    successes = sum(item.status == "succeeded" for item in items)
                    batch.status = (
                        "done"
                        if successes == len(items)
                        else "partial" if successes else "failed"
                    )
                    if (
                        batch.mode == "analyze_and_match"
                        and batch.match_task_id is None
                    ):
                        self._create_match(session, batch)
            if batch.match_task_id:
                task = session.get(MatchTask, batch.match_task_id)
                if task.status is MatchStatus.QUEUED and (
                    batch.match_dispatched_at is None
                    or batch.match_dispatched_at <= self.clock() - PUBLICATION_RETRY
                ):
                    batch.match_dispatched_at = self.clock()
                    match_dispatch_id = task.id
            session.commit()
        for identifier in dispatch_ids:
            try:
                self.analysis_dispatcher.dispatch(identifier)
            except Exception:
                pass  # Expiring publication reservations retain the same job ID.
        if match_dispatch_id:
            try:
                self.match_dispatcher.dispatch(START_MATCH_TASK_NAME, match_dispatch_id)
            except Exception:
                pass

    def _create_match(self, session, batch):
        discovery = session.get(DiscoverJob, batch.discover_id)
        if discovery.game_id is None:
            self._block(
                batch,
                "game_profile_unusable",
                "The Game Profile cannot be used for Match.",
            )
            return
        try:
            # Roll back an empty input snapshot without leaving an empty Match.
            with session.begin_nested():
                task = MatchRepository(session, clock=self.clock).create_locked_task(
                    discovery.game_id,
                    secrets.randbits(64) - 2**63,
                    Decimal(
                        SettingsRepository(session)
                        .get_reanalysis()
                        .recommended_match_threshold
                    ),
                )
                if (
                    session.scalar(
                        select(MatchCandidateInput.creator_id)
                        .where(MatchCandidateInput.match_task_id == task.id)
                        .limit(1)
                    )
                    is None
                ):
                    raise MatchInputError("no_eligible_creators")
                task.correlation_id = str(batch.id)
                batch.match_task_id = task.id
        except MatchInputError as error:
            if str(error) == "no_eligible_creators":
                self._block(
                    batch,
                    "no_eligible_creators",
                    "No Library creators are currently eligible for Match.",
                )
            else:
                self._block(
                    batch,
                    "game_profile_unusable",
                    "The Game Profile cannot be used for Match.",
                )

    @staticmethod
    def _block(batch, code, message):
        batch.status = "blocked"
        batch.error = {"code": code, "message": message}

    def _usable(self, session, profile):
        return (
            profile is not None
            and MatchRepository(session)._eligible_creator_brief(
                profile, cutoff=self.clock() - MATCH_INPUT_RETENTION
            )
            is not None
        )

    def _advance_item(self, session, batch, item):
        candidate = session.get(DiscoverCandidate, item.candidate_id)
        profile = session.scalar(
            select(CreatorProfile).where(
                CreatorProfile.platform == candidate.platform,
                CreatorProfile.platform_account_id == candidate.platform_account_id,
            )
        )
        job = (
            session.get(AnalysisJob, item.analysis_job_id)
            if item.analysis_job_id
            else None
        )
        if job and job.status is JobStatus.FAILED:
            item.status = "failed"
            item.error = {"code": job.error_code, "message": job.error_message}
            return None
        if job and job.status is JobStatus.SUCCEEDED:
            try:
                require_valid_succeeded_job_result(session, job)
            except Exception:
                return self._unusable(item)
            profile = session.get(CreatorProfile, job.profile_id)
            if not self._usable(session, profile):
                return self._unusable(item)
        if self._usable(session, profile):
            item.profile_id, item.status = profile.id, "succeeded"
            item.reused = job is None or job.status is not JobStatus.SUCCEEDED
            return None
        created = False
        if job is None:
            result = JobsRepository(session).create_or_reuse_job(
                canonicalize_target(
                    TargetType.CREATOR, candidate.metadata_snapshot["canonical_url"]
                ),
                mode=JobMode.REANALYZE if profile else JobMode.CREATE,
                correlation_id=str(batch.id),
            )
            job, created = result.job, result.created
            item.analysis_job_id = job.id
        item.status = "running" if job.status is JobStatus.RUNNING else "queued"
        recent = session.scalar(
            select(func.max(DiscoverAnalysisItem.dispatched_at)).where(
                DiscoverAnalysisItem.analysis_job_id == job.id
            )
        )
        if (
            job.status is JobStatus.QUEUED
            and (created or job.created_at <= self.clock() - PUBLICATION_RETRY)
            and (recent is None or recent <= self.clock() - PUBLICATION_RETRY)
        ):
            item.dispatched_at = self.clock()
            return job.id
        return None

    @staticmethod
    def _unusable(item):
        item.status = "failed"
        item.error = {
            "code": "creator_profile_unusable",
            "message": "Analysis did not produce a usable Creator Profile.",
        }
