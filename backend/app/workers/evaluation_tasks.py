"""Bounded progressive evaluation with child checkpoints and explicit recovery."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from time import monotonic
from sqlalchemy import select
from datetime import timedelta
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.analysis_diagnostics import diagnostic_context, emit, last_model_call_id
from app.db.models.creator_search import CreatorSearch, CreatorSearchUnit
from app.core.crypto import EncryptedValue, SecretCipher
from app.core.database import session_scope
from app.core.idempotency import utc_now
from app.db.models.discovery_evaluation import EvaluationStep
from app.discovery.evaluation_snapshot import digest
from app.integrations.errors import (
    IntegrationError,
    InvalidModelOutput,
    TransientIntegrationError,
)
from app.repositories.discovery_evaluation import (
    CHUNK_SIZE,
    add_step,
    expired,
    items_for,
    lock_run,
    steps_for,
)
from app.repositories.settings import SettingsRepository
from app.workers.celery_app import celery_app

CONCURRENCY = 4
LEASE_SECONDS = 300
logger = logging.getLogger(__name__)
_SAFE_FAILURE_REASONS = frozenset(
    {
        "evaluation_screen_ids_invalid",
        "evaluation_candidate_id_invalid",
        "evaluation_work_ids_invalid",
        "evaluation_evidence_invalid",
        "evaluation_narrative_invalid",
        "evaluation_rank_ids_invalid",
        "deepseek_model_output_invalid",
        "deepseek_response_invalid",
    }
)


def _log_failure(run_id, step_id, kind, failure):
    # Fixed codes only: exception text and model responses may contain contacts
    # or credentials. Keep the existing public API error contract unchanged.
    reason = getattr(failure, "code", None)
    logger.warning(
        "%s",
        json.dumps(
            {
                "event": "evaluation_step_failed",
                "run_id": str(run_id),
                "step_id": str(step_id),
                "kind": kind,
                "error_code": error_code(failure),
                "reason": reason if reason in _SAFE_FAILURE_REASONS else "unclassified",
            }
        ),
    )


class EvaluationConfigurationMissing(Exception):
    pass


def production_execute(kind, payload):
    from app.discovery.evaluation_ai import EvaluationAI
    from app.integrations.deepseek import DeepSeekGateway

    with session_scope() as session:
        secret = SettingsRepository(session).get_connection("deepseek")
        if secret is None:
            raise EvaluationConfigurationMissing()
        value = EncryptedValue(ciphertext=secret.ciphertext, nonce=secret.nonce)
    try:
        credential = SecretCipher.from_file(get_settings().master_key_file).decrypt(
            value
        )
    except Exception:
        raise EvaluationConfigurationMissing() from None
    with DeepSeekGateway(
        api_key=credential, base_url=get_settings().deepseek_api_base_url
    ) as gateway:
        ai = EvaluationAI(gateway)
        if kind == "screening":
            return ai.screen(payload["game"], payload["candidates"])
        if kind == "deep_match":
            return ai.deep(payload["game"], payload["candidate"])
        return ai.rank(payload["game"], payload["briefs"])


def error_code(error):
    if isinstance(error, EvaluationConfigurationMissing):
        return "evaluation_configuration_missing"
    if isinstance(error, InvalidModelOutput) or (
        isinstance(error, IntegrationError)
        and error.code in {"deepseek_model_output_invalid", "deepseek_response_invalid"}
    ):
        return "evaluation_model_output_invalid"
    if isinstance(error, TransientIntegrationError):
        return "evaluation_model_unavailable"
    if isinstance(error, IntegrationError):
        return "evaluation_model_rejected"
    return "evaluation_failed"


def _advance(session, run, items, steps):
    for step in steps:
        if expired(step):
            step.status, step.error_code = "failed", "evaluation_outcome_unknown"
            step.lease_token = None
    screening = [s for s in steps if s.kind == "screening"]
    if any(s.status in {"pending", "running"} for s in screening):
        return "screening"
    deep_members = {i for s in steps if s.kind == "deep_match" for i in s.item_ids}
    for item in items:
        if item.screening_selected and str(item.id) not in deep_members:
            step = add_step(
                session, run.id, "deep:" + str(item.id), "deep_match", [item.id]
            )
            steps.append(step)
    session.flush()
    deep = [s for s in steps if s.kind == "deep_match"]
    if any(s.status in {"pending", "running"} for s in deep):
        return "deep_match"
    ranked_members = {i for s in steps if s.kind == "ranking" for i in s.item_ids}
    ready = [
        i.id
        for i in items
        if i.match_brief is not None and str(i.id) not in ranked_members
    ]
    for start in range(0, len(ready), CHUNK_SIZE):
        members = ready[start : start + CHUNK_SIZE]
        key = "rank:" + digest([str(i) for i in members])
        steps.append(add_step(session, run.id, key, "ranking", members))
    session.flush()
    if any(s.kind == "ranking" and s.status in {"pending", "running"} for s in steps):
        return "ranking"
    failed = any(s.status == "failed" for s in steps) or any(
        i.identity_changed for i in items
    )
    matched = any(i.match_brief is not None for i in items)
    run.status = (
        ("partial" if matched else "failed")
        if failed
        else "completed" if matched else "no_matches"
    )
    run.stage = "complete"
    return None


def _claims(session, run_id):
    run = lock_run(session, run_id)
    if run is None or run.status not in {"queued", "running"}:
        return []
    items, steps = items_for(session, run.id), steps_for(session, run.id)
    kind = _advance(session, run, items, steps)
    if kind is None:
        return []
    run.status, run.stage = "running", kind
    capacity = CONCURRENCY - sum(s.status == "running" for s in steps)
    pending = [s for s in steps if s.kind == kind and s.status == "pending"][
        : max(0, capacity)
    ]
    by_id = {str(i.id): i for i in items}
    claims = []
    for step in pending:
        step.status = "running"
        step.attempt += 1
        step.lease_token = uuid4()
        step.lease_expires_at = utc_now() + timedelta(seconds=LEASE_SECONDS)
        members = [by_id[i] for i in step.item_ids]
        payload = {"game": run.game_brief}
        if kind == "screening":
            payload["candidates"] = [i.snapshot for i in members]
        elif kind == "deep_match":
            payload["candidate"] = members[0].snapshot
        else:
            payload["briefs"] = [i.match_brief for i in members]
        claims.append((step.id, step.lease_token, kind, payload))
    return claims


def _publish(session, run_id, claim, output, failure):
    run = lock_run(session, run_id)
    step_id, token, kind, _payload = claim
    step = session.get(EvaluationStep, step_id)
    if (
        run is None
        or step is None
        or step.status != "running"
        or step.lease_token != token
        or expired(step)
    ):
        return
    if failure:
        step.status, step.error_code = "failed", error_code(failure)
        _log_failure(run_id, step_id, kind, failure)
    else:
        data = output.model_dump(mode="json")
        members = [i for i in items_for(session, run_id) if str(i.id) in step.item_ids]
        if kind == "screening":
            selected = set(data["selected_ids"])
            for item in members:
                item.screening_selected = str(item.candidate_id) in selected
        elif kind == "deep_match":
            members[0].match_brief = data
        else:
            scores = {r["candidate_id"]: r["score"] for r in data["items"]}
            for item in members:
                item.score = scores[str(item.candidate_id)]
        step.output, step.status, step.error_code = data, "succeeded", None
    step.lease_token, step.lease_expires_at = None, None


def run_evaluation(
    run_id, *, session_factory=session_scope, execute_model=None, should_continue=None
):
    run_id = UUID(str(run_id))
    execute_model = execute_model or production_execute
    while True:
        if should_continue is not None and not should_continue():
            with session_factory() as session:
                run = lock_run(session, run_id)
                if run and run.status in {"queued", "running"}:
                    run.status = "partial"
                    run.stage = "stopped"
            return
        with session_factory() as session:
            claims = _claims(session, run_id)
            search_id = session.scalar(
                select(CreatorSearch.id)
                .where(CreatorSearch.evaluation_id == run_id)
                .order_by(CreatorSearch.created_at)
                .limit(1)
            )
            origin = {}
            if search_id is not None:
                for unit in session.scalars(
                    select(CreatorSearchUnit).where(
                        CreatorSearchUnit.search_id == search_id
                    )
                ):
                    origin[str(unit.candidate_id)] = {
                        "creator_id": unit.creator_id,
                        "job_id": unit.analysis_job_id,
                    }
        if not claims:
            return
        # Model calls never hold the claim/publication transaction. Distinct workers
        # share the per-run running-step count, preventing duplicate or unbounded work.
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {
                pool.submit(
                    copy_context().run,
                    _execute_diagnostic_claim,
                    run_id,
                    search_id,
                    claim,
                    execute_model,
                    origin.get(claim[3].get("candidate", {}).get("candidate_id"), {}),
                ): claim
                for claim in claims
            }
            for future in as_completed(futures):
                output, failure = None, None
                try:
                    output = future.result()
                except Exception as error:
                    failure = error
                with session_factory() as session:
                    _publish(session, run_id, futures[future], output, failure)


def _execute_diagnostic_claim(run_id, search_id, claim, execute_model, origin=None):
    step_id, _token, kind, payload = claim
    candidate = payload.get("candidate", {})
    origin = origin or {}
    with diagnostic_context(
        evaluation_run_id=run_id,
        search_id=search_id,
        step_id=step_id,
        candidate_id=candidate.get("candidate_id"),
        creator_id=origin.get("creator_id"),
        job_id=origin.get("job_id"),
    ):
        started = monotonic()
        emit("evaluation_step_started", kind=kind)
        try:
            result = execute_model(kind, payload)
        except Exception as error:
            reason = getattr(error, "code", None)
            emit(
                "evaluation_step_finished",
                kind=kind,
                status="failed",
                reason=reason if reason in _SAFE_FAILURE_REASONS else "unclassified",
                error_code=error_code(error),
                call_id=last_model_call_id(),
                duration_ms=round((monotonic() - started) * 1000, 2),
            )
            raise
        emit(
            "evaluation_step_finished",
            kind=kind,
            status="succeeded",
            call_id=last_model_call_id(),
            duration_ms=round((monotonic() - started) * 1000, 2),
        )
        return result


@celery_app.task(name="find_me_gamer.discovery.evaluate", max_retries=0)
def evaluate_discovery_task(run_id):
    run_evaluation(run_id)
