"""Short durable transitions around external discovery and Game Analysis work."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid5

from pydantic import ValidationError
from sqlalchemy import select, func

from app.analysis.targets import canonicalize_target
from app.core.analysis_job_contract import public_job_failure
from app.db.models.discover import DiscoverJob, DiscoverCandidate
from app.db.models.enums import TargetType, JobMode, JobStatus
from app.db.models.jobs import AnalysisJob, acquire_job_change_lock
from app.db.models.profiles import CreatorProfile, GameProfile
from app.discovery.planning import build_plan, HomepageCandidate, matches
from app.repositories.discover import DiscoverRepository
from app.repositories.jobs import JobsRepository, require_valid_succeeded_job_result
from app.schemas.ai_game import GameBrief
from app.schemas.discover import DiscoverConditions
from app.services.profile_editing import effective_name, effective_section

LEASE = timedelta(minutes=10)
PUBLICATION_RETRY = timedelta(minutes=2)
PLATFORM_RESULT_LIMIT = 20


def usable_game(game):
    if game is None or game.last_analyzed_at is None:
        return False
    try:
        GameBrief.model_validate(game.brief)
    except (ValidationError, TypeError):
        return False
    return True


class DiscoverService:
    def __init__(
        self, *, session_factory, provider_factory, analysis_dispatcher, clock=None
    ):
        self.sessions = session_factory
        self.providers = provider_factory
        self.analysis_dispatcher = analysis_dispatcher
        self.clock = clock or (lambda: datetime.now(UTC))

    def execute(self, job_id):
        token = self._claim(job_id)
        if token is None:
            return
        try:
            prepared = self._prepare(job_id, token)
            if prepared is None:
                return
            snapshot, conditions, completed = prepared
            queries = build_plan(snapshot, conditions.keywords)
            for platform in conditions.platforms:
                if platform in completed:
                    continue
                try:
                    remaining = self._remaining(job_id, platform)
                    if remaining:
                        with self.providers(platform) as provider:
                            # Keep bounded oversampling so Library hits do not
                            # consume the per-platform quota of new accounts.
                            for page in provider.search(queries, conditions, limit=100):
                                if not self._save_page(
                                    job_id, token, platform, page, conditions
                                ):
                                    break
                    self._platform_done(job_id, token, platform)
                except Exception as error:
                    self._platform_failed(job_id, token, platform, error)
            self._finish(job_id, token)
        except Exception:
            # Unexpected provider/runtime failures never serialize raw messages.
            self._fail(
                job_id,
                token,
                "discover_internal_error",
                "Discovery could not finish. Please retry.",
            )

    def _claim(self, job_id):
        with self.sessions() as session:
            job = DiscoverRepository(session).get(job_id, lock=True)
            now = self.clock()
            if (
                job is None
                or job.status not in {"queued", "running"}
                or (job.lease_until and job.lease_until > now)
            ):
                session.commit()
                return None
            token = uuid4()
            job.lease_token, job.lease_until = token, now + LEASE
            job.status = "running"
            session.commit()
            return token

    def _owned(self, session, job_id, token):
        job = DiscoverRepository(session).get(job_id, lock=True)
        return job if job and job.lease_token == token else None

    def _prepare(self, job_id, token):
        dispatch_id = None
        prepared = None
        with self.sessions() as session:
            # Same global lock as JobsRepository/API prevents duplicate active jobs.
            acquire_job_change_lock(session)
            job = self._owned(session, job_id, token)
            if job is None:
                session.commit()
                return None
            if job.game_snapshot is None:
                target = canonicalize_target(TargetType.GAME, job.steam_url)
                game = session.scalar(
                    select(GameProfile).where(
                        GameProfile.steam_app_id == target.canonical_id
                    )
                )
                prerequisite = (
                    session.get(AnalysisJob, job.game_job_id)
                    if job.game_job_id
                    else None
                )
                if prerequisite and prerequisite.status is JobStatus.FAILED:
                    self._set_failure(
                        job,
                        "game_analysis_failed",
                        "Game analysis failed. Retry to prepare the game.",
                    )
                elif usable_game(game):
                    if prerequisite and prerequisite.status is JobStatus.SUCCEEDED:
                        require_valid_succeeded_job_result(session, prerequisite)
                    job.game_id = game.id
                    job.game_name = effective_name(game)
                    job.game_snapshot = {
                        "name": effective_name(game),
                        "facts": effective_section(game, "facts"),
                        "analysis": effective_section(game, "analysis"),
                        "brief": effective_section(game, "brief"),
                        "profile_revision": game.profile_revision,
                    }
                elif prerequisite and prerequisite.status is JobStatus.SUCCEEDED:
                    self._set_failure(
                        job,
                        "game_profile_unusable",
                        "Game analysis did not produce a usable profile. Retry to prepare the game.",
                    )
                else:
                    created_prerequisite = False
                    if prerequisite is None:
                        result = JobsRepository(session).create_or_reuse_job(
                            target,
                            mode=JobMode.REANALYZE if game else JobMode.CREATE,
                            correlation_id=str(job.id),
                        )
                        prerequisite = result.job
                        created_prerequisite = result.created
                        if prerequisite is None:
                            raise ValueError("Missing prerequisite")
                        job.game_job_id = prerequisite.id
                        job.game_dispatched_at = None
                    # Reserve publication across every Discover request joining this
                    # analysis. Uncertain broker delivery is recoverable after 2 min.
                    recent_dispatch = session.scalar(
                        select(func.max(DiscoverJob.game_dispatched_at)).where(
                            DiscoverJob.game_job_id == prerequisite.id
                        )
                    )
                    if (
                        prerequisite.status is JobStatus.QUEUED
                        and (
                            created_prerequisite
                            or prerequisite.created_at
                            <= self.clock() - PUBLICATION_RETRY
                        )
                        and (
                            recent_dispatch is None
                            or recent_dispatch <= self.clock() - PUBLICATION_RETRY
                        )
                    ):
                        job.game_dispatched_at = self.clock()
                        dispatch_id = prerequisite.id
                    job.stage = "preparing_game"
                    job.lease_token = None
                    job.lease_until = None
            if job.game_snapshot is not None:
                job.stage = "finding_creators"
                prepared = (
                    job.game_snapshot,
                    DiscoverConditions.model_validate(job.conditions),
                    list(job.completed_platforms),
                )
            session.commit()
        if dispatch_id:
            try:
                self.analysis_dispatcher.dispatch(dispatch_id)
            except Exception:
                # Beat will reconcile the same persisted prerequisite; no new job.
                pass
        return prepared

    def _remaining(self, job_id, platform):
        with self.sessions() as session:
            count = session.scalar(
                select(func.count())
                .select_from(DiscoverCandidate)
                .where(
                    DiscoverCandidate.discover_id == job_id,
                    DiscoverCandidate.platform == platform,
                )
            )
            return max(0, PLATFORM_RESULT_LIMIT - count)

    def _save_page(self, job_id, token, platform, page, conditions):
        # Validate/filter outside the write lock and keep provider metadata only.
        candidates = [
            HomepageCandidate.model_validate(
                c.model_dump() if isinstance(c, HomepageCandidate) else c
            )
            for c in page
        ]
        with self.sessions() as session:
            job = self._owned(session, job_id, token)
            if job is None:
                session.commit()
                return False
            existing = set(
                session.scalars(
                    select(DiscoverCandidate.id).where(
                        DiscoverCandidate.discover_id == job_id,
                        DiscoverCandidate.platform == platform,
                    )
                )
            )
            library_accounts = set(
                session.scalars(
                    select(CreatorProfile.platform_account_id).where(
                        CreatorProfile.platform == platform,
                        CreatorProfile.platform_account_id.in_(
                            [
                                c.platform_account_id
                                for c in candidates
                                if c.platform == platform
                            ]
                        ),
                    )
                )
            )
            for candidate in candidates:
                if candidate.platform != platform or not matches(candidate, conditions):
                    continue
                if candidate.platform_account_id in library_accounts:
                    continue
                identifier = uuid5(
                    job_id, f"{candidate.platform}:{candidate.platform_account_id}"
                )
                if identifier in existing or len(existing) >= PLATFORM_RESULT_LIMIT:
                    continue
                session.add(
                    DiscoverCandidate(
                        id=identifier,
                        discover_id=job_id,
                        platform=platform,
                        platform_account_id=candidate.platform_account_id,
                        metadata_snapshot=candidate.model_dump(),
                    )
                )
                existing.add(identifier)
            job.lease_until = self.clock() + LEASE
            session.commit()
            return len(existing) < PLATFORM_RESULT_LIMIT

    def _platform_done(self, job_id, token, platform):
        with self.sessions() as session:
            job = self._owned(session, job_id, token)
            if job:
                job.completed_platforms = list(
                    dict.fromkeys([*job.completed_platforms, platform])
                )
                job.issues = [
                    issue for issue in job.issues if issue.get("platform") != platform
                ]
            session.commit()

    def _platform_failed(self, job_id, token, platform, error):
        code = getattr(error, "code", None)
        failure = public_job_failure(code)
        issue = {
            "platform": platform,
            "code": code if failure else "discover_provider_failed",
            "message": (
                failure.message
                if failure
                else "Platform discovery failed. Please retry."
            ),
        }
        with self.sessions() as session:
            job = self._owned(session, job_id, token)
            if job:
                job.issues = [
                    i for i in job.issues if i.get("platform") != platform
                ] + [issue]
            session.commit()

    def _finish(self, job_id, token):
        with self.sessions() as session:
            job = self._owned(session, job_id, token)
            if job:
                any_candidates = session.scalar(
                    select(DiscoverCandidate.id)
                    .where(DiscoverCandidate.discover_id == job_id)
                    .limit(1)
                )
                job.status = (
                    "done"
                    if not job.issues
                    else (
                        "partial"
                        if any_candidates or job.completed_platforms
                        else "failed"
                    )
                )
                job.stage = None
                job.lease_until = None
                job.lease_token = None
            session.commit()

    def _set_failure(self, job, code, message):
        job.status = "failed"
        job.stage = None
        job.issues = [{"platform": None, "code": code, "message": message}]
        job.lease_until = None
        job.lease_token = None

    def _fail(self, job_id, token, code, message):
        with self.sessions() as session:
            job = self._owned(session, job_id, token)
            if job:
                self._set_failure(job, code, message)
            session.commit()
