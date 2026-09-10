"""Explicit end-to-end search with durable per-Creator progress.

No legacy discovery is enrolled, no SMTP is invoked, and duplicate deliveries
never take over a live or expired lease. Recovery is an explicit API operation.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import timedelta
from threading import Event, Thread
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.database import session_scope
from app.core.idempotency import utc_now
from app.db.models.creator_search import CreatorSearch, CreatorSearchUnit
from app.db.models.discovery import DiscoveryQuery, DiscoveryBatch, DiscoveryCandidate
from app.db.models.discovery_plan import DiscoveryPlan
from app.db.models.discovery_evaluation import EvaluationRun
from app.repositories.creator_search import lock_search, units_for
from app.repositories.discovery_evaluation import (
    create_run,
    extend_run,
    steps_for,
    expired,
)
from app.workers.celery_app import celery_app

LEASE_SECONDS = 180
CONCURRENCY = 2


class SearchFailure(Exception):
    def __init__(self, code):
        self.code = code


@contextmanager
def keep_lease(identity, token, sessions, enabled):
    done = Event()

    def beat():
        while not done.wait(30):
            try:
                with sessions() as session:
                    task = lock_search(session, identity)
                    if not task or task.lease_token != token:
                        return
                    task.lease_expires_at = utc_now() + timedelta(seconds=LEASE_SECONDS)
            except Exception:
                # A lost lease fences future work; never log secrets/remote payloads.
                return

    thread = Thread(target=beat, daemon=True) if enabled else None
    if thread:
        thread.start()
    try:
        yield
    finally:
        done.set()
        if thread:
            thread.join(timeout=2)


def _owns(task, token):
    return bool(
        task
        and task.lease_token == token
        and task.lease_expires_at
        and task.lease_expires_at > utc_now()
    )


def _continue(identity, token, sessions):
    with sessions() as session:
        task = lock_search(session, identity)
        return _owns(task, token) and not task.stop_requested


def _discover(identity, token, sessions, plan_generator, gateway_factory):
    from app.workers.planning_tasks import run_discovery_plan
    from app.workers.discovery_tasks import run_discovery_batch
    from app.repositories.discovery import start_batch

    with sessions() as session:
        task = lock_search(session, identity)
        if task.scope_frozen:
            return
        plan = session.get(DiscoveryPlan, task.plan_id)
        plan_id = plan.id
        if plan.status in {"failed", "running"}:
            # Only reached after explicit search retry; no broker redelivery takeover.
            plan.status = "queued"
            plan.lease_token = plan.lease_expires_at = None
            plan.error_code = None
    if not _continue(identity, token, sessions):
        return
    run_discovery_plan(
        plan_id,
        session_factory=sessions,
        plan_generator=plan_generator,
        dispatch_discovery=lambda batch_id: None,
    )
    with sessions() as session:
        task = lock_search(session, identity)
        if not _owns(task, token):
            return
        plan = session.get(DiscoveryPlan, plan_id)
        if plan.status != "ready" or not plan.query_id:
            raise SearchFailure("search_planning_failed")
        task.query_id = plan.query_id
        task.stage = "discovery"
        query = session.get(DiscoveryQuery, task.query_id)
        if task.batch_id is None:
            if task.parent_search_id:
                task.batch_id = start_batch(session, query, task.acknowledge_unknown).id
            else:
                task.batch_id = session.scalar(
                    select(DiscoveryBatch.id).where(
                        DiscoveryBatch.query_id == query.id, DiscoveryBatch.ordinal == 1
                    )
                )
        batch = session.get(DiscoveryBatch, task.batch_id)
        # A stopped batch resumes only through a new bounded discovery batch.
        if batch.status in {"stopped", "outcome_unknown"} and not task.stop_requested:
            task.batch_id = start_batch(session, query, task.acknowledge_unknown).id
        batch_id = task.batch_id
    if not _continue(identity, token, sessions):
        return
    run_discovery_batch(
        batch_id, session_factory=sessions, gateway_factory=gateway_factory
    )
    with sessions() as session:
        task = lock_search(session, identity)
        if not _owns(task, token) or task.stop_requested:
            return
        batch = session.get(DiscoveryBatch, batch_id)
        if batch.status in {"queued", "running"}:
            raise SearchFailure("search_discovery_incomplete")
        excluded = set(task.excluded_candidate_ids or [])
        candidates = session.scalars(
            select(DiscoveryCandidate)
            .where(DiscoveryCandidate.query_id == task.query_id)
            .order_by(DiscoveryCandidate.ordinal)
        )
        for candidate in candidates:
            if str(candidate.id) not in excluded:
                session.add(
                    CreatorSearchUnit(
                        search_id=identity,
                        candidate_id=candidate.id,
                        creator_id=candidate.creator_id,
                        platform=candidate.platform,
                        account_id=candidate.account_id,
                        identity_revision=candidate.identity_revision,
                        ordinal=candidate.ordinal,
                    )
                )
        task.scope_frozen = True
        task.stage = "profiles"
        session.flush()


def _enrich(identity, token, sessions, runner, phase, concurrency):
    field = "profile_status" if phase == "profiles" else "email_status"
    error_field = "profile_error_code" if phase == "profiles" else "email_error_code"
    success = {"ready", "reused"} if phase == "profiles" else {"available", "missing"}
    with sessions() as session:
        task = lock_search(session, identity)
        if not _owns(task, token) or task.stop_requested:
            return
        task.stage = phase
        pending = [
            u.id
            for u in units_for(session, identity)
            if getattr(u, field) not in success
            and (phase == "profiles" or u.profile_status in {"ready", "reused"})
        ]
    # Submit one small wave at a time. Stop never queues the rest of the task.
    for offset in range(0, len(pending), concurrency):
        if not _continue(identity, token, sessions):
            return
        wave = pending[offset : offset + concurrency]
        with sessions() as session:
            task = lock_search(session, identity)
            if not _owns(task, token) or task.stop_requested:
                return
            for uid in wave:
                unit = session.get(CreatorSearchUnit, uid)
                setattr(unit, field, "running")
                # Preserve prior profile failure until the runner decides whether
                # this is a recoverable attempt; a missing job must not refetch.
                if phase != "profiles":
                    setattr(unit, error_field, None)
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(runner, uid): uid for uid in wave}
            for future in as_completed(futures):
                code = None
                try:
                    status = future.result()
                    if status not in success:
                        raise ValueError("Invalid enrichment result")
                except Exception as error:
                    status = "failed"
                    code = (
                        error.code
                        if isinstance(error, SearchFailure)
                        else (
                            "search_profile_failed"
                            if phase == "profiles"
                            else "search_email_failed"
                        )
                    )
                with sessions() as session:
                    task = lock_search(session, identity)
                    if not _owns(task, token):
                        return
                    unit = session.get(CreatorSearchUnit, futures[future])
                    setattr(unit, field, status)
                    setattr(unit, error_field, code)


def _evaluate(identity, token, sessions, execute_model):
    from app.workers.evaluation_tasks import run_evaluation

    with sessions() as session:
        task = lock_search(session, identity)
        if not _owns(task, token) or task.stop_requested:
            return
        units = units_for(session, identity)
        candidates = [
            session.get(DiscoveryCandidate, u.candidate_id)
            for u in units
            if u.profile_status in {"ready", "reused"}
        ]
        if not candidates:
            if units:
                raise SearchFailure("search_no_usable_profiles")
            return
        query = session.get(DiscoveryQuery, task.query_id)
        if task.evaluation_id:
            run = session.get(EvaluationRun, task.evaluation_id)
            extend_run(session, run, candidates)
            for step in steps_for(session, run.id):
                if step.status == "failed" or expired(step):
                    step.status = "pending"
                    step.error_code = step.lease_token = step.lease_expires_at = None
            run.status = "queued"
        else:
            run = create_run(session, query, candidates)
            task.evaluation_id = run.id
        task.stage = "screening"
        run_id = run.id
    run_evaluation(
        run_id,
        session_factory=sessions,
        execute_model=execute_model,
        should_continue=lambda: _continue(identity, token, sessions),
    )


def run_creator_search(
    identity,
    *,
    session_factory=session_scope,
    plan_generator=None,
    gateway_factory=None,
    profile_runner=None,
    email_runner=None,
    execute_model=None,
    heartbeat=True,
    concurrency=CONCURRENCY,
):
    identity = UUID(str(identity))
    with session_factory() as session:
        task = lock_search(session, identity)
        if task is None or task.status != "queued" or task.lease_token:
            return
        if task.stop_requested:
            task.status = "stopped"
            return
        token = uuid4()
        task.status, task.lease_token = "running", token
        task.lease_expires_at = utc_now() + timedelta(seconds=LEASE_SECONDS)
        task.error_code = None
    if profile_runner is None or email_runner is None:
        from app.workers.creator_search_enrichment import enrich_profile, enrich_email

        profile_runner = profile_runner or (
            lambda uid: enrich_profile(uid, session_factory=session_factory)
        )
        email_runner = email_runner or (
            lambda uid: enrich_email(uid, session_factory=session_factory)
        )
    failure = None
    with keep_lease(identity, token, session_factory, heartbeat):
        try:
            _discover(identity, token, session_factory, plan_generator, gateway_factory)
            _enrich(
                identity,
                token,
                session_factory,
                profile_runner,
                "profiles",
                concurrency,
            )
            _enrich(
                identity, token, session_factory, email_runner, "emails", concurrency
            )
            _evaluate(identity, token, session_factory, execute_model)
        except Exception as error:
            failure = (
                error.code if isinstance(error, SearchFailure) else "search_failed"
            )
        with session_factory() as session:
            task = lock_search(session, identity)
            if not _owns(task, token):
                return
            units = units_for(session, identity)
            run = (
                session.get(EvaluationRun, task.evaluation_id)
                if task.evaluation_id
                else None
            )
            batch = (
                session.get(DiscoveryBatch, task.batch_id) if task.batch_id else None
            )
            partial = any(
                u.profile_status == "failed" or u.email_status == "failed"
                for u in units
            )
            partial = partial or bool(run and run.status in {"partial", "failed"})
            partial = partial or bool(batch and batch.status in {"partial", "failed"})
            discovery_problem = bool(
                batch
                and (
                    batch.status == "outcome_unknown"
                    or batch.reason
                    in {
                        "provider_failed",
                        "source_partial",
                        "source_unavailable",
                        "collection_disabled",
                    }
                )
            )
            partial = partial or discovery_problem
            if discovery_problem and not failure:
                failure = (
                    "search_outcome_unknown"
                    if batch.status == "outcome_unknown"
                    and not task.acknowledge_unknown
                    else "search_discovery_partial"
                )
            task.status = (
                "stopped"
                if task.stop_requested
                else "failed" if failure else "partial" if partial else "completed"
            )
            if (
                failure
                and any(u.profile_status in {"ready", "reused"} for u in units)
                and not task.stop_requested
            ):
                task.status = "partial"
            task.error_code = failure
            if not task.stop_requested:
                task.stage = "complete"
            task.lease_token = task.lease_expires_at = None


@celery_app.task(name="find_me_gamer.creator_search.run", max_retries=0)
def creator_search_task(identity):
    run_creator_search(identity)
