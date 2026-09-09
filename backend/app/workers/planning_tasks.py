"""Claim once, call a bounded model outside transactions, publish one query."""

from datetime import timedelta
import json
import logging
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import EncryptedValue, SecretCipher
from app.core.database import session_scope
from app.core.idempotency import utc_now
from app.db.models.discovery import DiscoveryBatch, DiscoveryQuery
from app.integrations.errors import (
    IntegrationError,
    InvalidModelOutput,
    TransientIntegrationError,
)
from app.repositories.discovery import start_batch
from app.repositories.discovery_plan import expired, lock_plan
from app.repositories.settings import SettingsRepository
from app.schemas.activity import QueryCreate
from app.workers.celery_app import celery_app

LEASE_SECONDS = 300
logger = logging.getLogger(__name__)
_SAFE_FAILURE_REASONS = frozenset({
    "planning_platform_invalid", "deepseek_model_output_invalid",
    "deepseek_response_invalid", "deepseek_response_too_large",
    "deepseek_unavailable", "deepseek_request_rejected",
    "deepseek_configuration_invalid", "deepseek_input_invalid",
    "game_context_required", "plan_platforms_invalid",
})


def _log_failure(plan_id, error, public_code, attempt):
    reason = getattr(error, "code", None)
    if isinstance(error, PlanningConfigurationMissing):
        reason = "planning_configuration_missing"
    elif not isinstance(reason, str) or reason not in _SAFE_FAILURE_REASONS:
        reason = "unclassified"
    logger.warning("%s", json.dumps({
        "event": "discovery_planning_failed", "plan_id": str(plan_id),
        "attempt": attempt, "public_code": public_code, "reason": reason,
    }))


class PlanningConfigurationMissing(Exception):
    pass


def production_generate(snapshot, conditions, model, *, session_factory=session_scope):
    from app.discovery.planning import generate_plan
    from app.integrations.deepseek import DeepSeekGateway

    with session_factory() as session:
        secret = SettingsRepository(session).get_connection("deepseek")
        if secret is None:
            raise PlanningConfigurationMissing()
        encrypted = EncryptedValue(ciphertext=secret.ciphertext, nonce=secret.nonce)
    try:
        credential = SecretCipher.from_file(get_settings().master_key_file).decrypt(
            encrypted
        )
    except Exception:
        raise PlanningConfigurationMissing() from None
    with DeepSeekGateway(
        api_key=credential, base_url=get_settings().deepseek_api_base_url
    ) as gateway:
        return generate_plan(snapshot, conditions, gateway=gateway, model=model)


def _dispatch(batch_id):
    from app.api.routes.activity import CeleryDiscoveryDispatcher

    CeleryDiscoveryDispatcher().dispatch(batch_id)


def _first_batch(session, plan):
    if plan.query_id is None:
        return None
    return session.scalar(
        select(DiscoveryBatch.id).where(
            DiscoveryBatch.query_id == plan.query_id, DiscoveryBatch.ordinal == 1
        )
    )


def _deliver(plan_id, batch_id, session_factory, dispatch_discovery):
    failed = False
    try:
        dispatch_discovery(batch_id)
    except Exception:
        failed = True
    with session_factory() as session:
        plan = lock_plan(session, plan_id)
        if plan and plan.status == "ready":
            plan.error_code = "planning_discovery_queue_unavailable" if failed else None
            plan.retryable = failed


def _error_info(error):
    from app.discovery.planning import PlanningInputError

    if isinstance(error, PlanningInputError):
        return "game_context_required", False
    if isinstance(error, PlanningConfigurationMissing):
        return "planning_configuration_missing", True
    if isinstance(error, InvalidModelOutput) or (
        isinstance(error, IntegrationError)
        and error.code in {"deepseek_model_output_invalid", "deepseek_response_invalid"}
    ):
        return "planning_model_output_invalid", True
    if isinstance(error, TransientIntegrationError):
        return "planning_model_unavailable", True
    if isinstance(error, IntegrationError):
        return "planning_model_rejected", True
    return "planning_failed", True


def run_discovery_plan(
    plan_id,
    *,
    session_factory=session_scope,
    plan_generator=None,
    dispatch_discovery=None,
):
    from app.discovery.planning import provider_queries

    plan_id = UUID(str(plan_id))
    dispatch_discovery = dispatch_discovery or _dispatch
    batch_id = None
    with session_factory() as session:
        plan = lock_plan(session, plan_id)
        if plan is None:
            return
        if plan.status == "ready":
            batch_id = _first_batch(session, plan)
            claim = None
        elif plan.status != "queued":
            return  # Expired execution needs explicit retry; no hidden model calls.
        else:
            plan.status = "running"
            plan.attempt += 1
            plan.lease_token = uuid4()
            plan.lease_expires_at = utc_now() + timedelta(seconds=LEASE_SECONDS)
            claim = (
                plan.lease_token,
                plan.source_snapshot,
                plan.conditions,
                plan.model,
                plan.attempt,
            )
    if claim is None:
        if batch_id:
            _deliver(plan_id, batch_id, session_factory, dispatch_discovery)
        return
    token, snapshot, conditions, model, attempt = claim
    try:
        if plan_generator is None:
            output = production_generate(
                snapshot, conditions, model, session_factory=session_factory
            )
        else:
            output = plan_generator(snapshot, conditions, model)
        native_queries = provider_queries(output)
        if set(native_queries) != set(conditions["platforms"]):
            raise InvalidModelOutput("planning_platform_invalid")
        providers = []
        for platform in conditions["platforms"]:
            ceiling, minimum = (50, 1) if platform == "youtube" else (100, 10)
            page_size = max(
                minimum,
                min(
                    ceiling,
                    conditions["batch_scan_budget"],
                    conditions["total_scan_budget"],
                ),
            )
            providers.append(
                {
                    "platform": platform,
                    "query": native_queries[platform],
                    "page_size": page_size,
                    "max_requests": 2 if platform == "youtube" else 1,
                }
            )
        options = {
            k: v
            for k, v in conditions.items()
            if k not in {"mode", "keywords", "platforms"}
        }
        query_conditions = QueryCreate(providers=providers, **options).model_dump(
            mode="json"
        )
    except Exception as error:
        code, retryable = _error_info(error)
        _log_failure(plan_id, error, code, attempt)
        with session_factory() as session:
            plan = lock_plan(session, plan_id)
            if (
                plan
                and plan.status == "running"
                and plan.lease_token == token
                and not expired(plan)
            ):
                plan.status, plan.error_code, plan.retryable = "failed", code, retryable
                plan.lease_token, plan.lease_expires_at = None, None
        return
    with session_factory() as session:
        plan = lock_plan(session, plan_id)
        if (
            plan is None
            or plan.status != "running"
            or plan.lease_token != token
            or expired(plan)
        ):
            return
        if conditions["mode"] == "discover":
            query = DiscoveryQuery(
                id=uuid4(),
                activity_id=plan.activity_id,
                conditions=query_conditions,
                source_snapshot={**snapshot, "discovery_plan_id": str(plan_id)},
            )
            session.add(query)
            session.flush()
            batch_id = start_batch(session, query).id
            plan.query_id = query.id
        plan.output = output.model_dump(mode="json") | {
            "provider_queries": native_queries
        }
        plan.status, plan.error_code, plan.retryable = "ready", None, False
        plan.lease_token, plan.lease_expires_at = None, None
    # If broker dispatch fails, ready state/query remain; replay or retry redispatches
    # the same first batch without another model call or query creation.
    if batch_id:
        _deliver(plan_id, batch_id, session_factory, dispatch_discovery)


@celery_app.task(name="find_me_gamer.discovery.plan", max_retries=0)
def plan_discovery_task(plan_id):
    run_discovery_plan(plan_id)
