"""At most one durable provider page in flight, with no automatic paid retries."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.crypto import EncryptedValue, SecretCipher
from app.core.database import session_scope
from app.db.models.discovery import DiscoveryAttempt, DiscoveryBatch, DiscoveryCandidate
from app.repositories.discovery import invalidate_expired, lock_query
from app.repositories.settings import SettingsRepository
from app.schemas.discovery import DiscoveryRequest
from app.workers.celery_app import celery_app

DISCOVERY_TASK_NAME = "find_me_gamer.discovery.run_batch"
LEASE_SECONDS = 300


class MissingConnection(Exception):
    pass


@contextmanager
def production_gateway(platform):
    # Credential read closes before any network call. Usage probes never gate search.
    with session_scope() as session:
        secret = SettingsRepository(session).get_connection(platform)
        if secret is None:
            raise MissingConnection()
        encrypted = EncryptedValue(ciphertext=secret.ciphertext, nonce=secret.nonce)
    try:
        credential = SecretCipher.from_file(get_settings().master_key_file).decrypt(
            encrypted
        )
    except Exception:
        raise MissingConnection() from None
    if platform == "youtube":
        from app.integrations.youtube_discovery import YouTubeDiscoveryGateway

        gateway = YouTubeDiscoveryGateway(
            api_key=credential, base_url=get_settings().youtube_api_base_url
        )
    else:
        from app.integrations.x_discovery import XDiscoveryGateway

        gateway = XDiscoveryGateway(
            bearer_token=credential, base_url=get_settings().x_api_base_url
        )
    with gateway:
        yield gateway


def finish(query, batch, reason):
    batch.reason = reason
    batch.status = "stopped" if query.stop_requested else "completed"
    if query.stop_requested:
        query.status = "stopped"
    elif reason in (
        "result_limit",
        "providers_finished",
        "total_budget_exhausted",
        "no_available_sources",
    ):
        query.status = "completed"
    else:
        query.status = "paused"


def reserve(session, batch_id):
    batch = session.get(DiscoveryBatch, batch_id)
    if batch is None:
        return None
    query = lock_query(session, batch.query_id)
    session.refresh(batch)
    if batch.status not in ("queued", "running"):
        return None
    if invalidate_expired(session, query):
        return None
    if batch.status == "outcome_unknown":
        return None
    limits = query.conditions
    if query.stop_requested:
        finish(query, batch, "stopped")
        return None
    if query.result_count >= limits.get("result_limit", 600):
        finish(query, batch, "result_limit")
        return None
    if query.result_count - batch.initial_result_count >= batch.target_count:
        finish(query, batch, "target_reached")
        return None
    states = dict(query.provider_states)
    request = None
    for provider in limits["providers"]:
        platform = provider["platform"]
        state = dict(states.get(platform, {}))
        if state.get("status") in (
            "exhausted",
            "failed",
            "partial",
            "missing_connection",
            "not_supported",
            "budget_exhausted",
            "unavailable",
        ):
            continue
        if platform not in ("youtube", "x"):
            states[platform] = {
                "status": "not_supported",
                "issues": [{"code": "not_supported"}],
            }
            continue
        raw = dict(provider)
        raw["cursor"] = state.get("cursor")
        request = DiscoveryRequest.model_validate(raw)
        break
    query.provider_states = states
    if request is None:
        statuses = {state.get("status") for state in states.values()}
        if "failed" in statuses:
            reason = "provider_failed"
        elif "partial" in statuses:
            reason = "source_partial"
        elif statuses.intersection({"missing_connection", "unavailable"}):
            reason = "source_unavailable"
        elif statuses == {"not_supported"}:
            reason = "no_available_sources"
        else:
            reason = "providers_finished"
        finish(query, batch, reason)
        return None
    cost = 2 if request.platform == "youtube" else 1
    scan = request.page_size
    if request.max_requests < cost:
        states[request.platform] = {
            "status": "budget_exhausted",
            "issues": [{"code": "budget_exhausted"}],
        }
        query.provider_states = states
        finish(query, batch, "budget_exhausted")
        return None
    if query.requests_reserved + cost > limits.get(
        "total_request_budget", 120
    ) or query.scanned_reserved + scan > limits.get("total_scan_budget", 6000):
        finish(query, batch, "total_budget_exhausted")
        return None
    if batch.requests_reserved + cost > limits.get(
        "batch_request_budget", 20
    ) or batch.scanned_reserved + scan > limits.get("batch_scan_budget", 1000):
        finish(query, batch, "budget_exhausted")
        return None
    sequence = (
        session.scalar(
            select(func.max(DiscoveryAttempt.sequence)).where(
                DiscoveryAttempt.batch_id == batch.id
            )
        )
        or 0
    ) + 1
    token = uuid4()
    attempt = DiscoveryAttempt(
        batch_id=batch.id,
        platform=request.platform,
        input=request.model_dump(mode="json"),
        lease_token=token,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS),
        requests_reserved=cost,
        scan_reserved=scan,
        sequence=sequence,
    )
    session.add(attempt)
    query.requests_reserved += cost
    query.scanned_reserved += scan
    batch.requests_reserved += cost
    batch.scanned_reserved += scan
    batch.status = query.status = "running"
    session.flush()
    return attempt.id, token, request


def apply_outcome(session, attempt_id, token, page, failure):
    attempt = session.get(DiscoveryAttempt, attempt_id)
    batch = session.get(DiscoveryBatch, attempt.batch_id)
    query = lock_query(session, batch.query_id)
    session.refresh(attempt)
    session.refresh(batch)
    if attempt.status != "in_flight" or attempt.lease_token != token:
        return False
    if attempt.lease_expires_at <= datetime.now(UTC):
        failure = "outcome_unknown"
    if failure == "outcome_unknown":
        attempt.status = batch.status = query.status = "outcome_unknown"
        attempt.lease_token = uuid4()
        attempt.outcome = {"status": "outcome_unknown"}
        batch.reason = "outcome_unknown"
        return False
    states = dict(query.provider_states)
    if failure == "missing_connection":
        attempt.status = "unavailable"
        attempt.outcome = {"status": "missing_connection"}
        states[attempt.platform] = {
            "status": "missing_connection",
            "issues": [{"code": "unavailable"}],
            "cursor": attempt.input.get("cursor"),
        }
        # No request was sent. These reservations can be released safely.
        query.requests_reserved -= attempt.requests_reserved
        query.scanned_reserved -= attempt.scan_reserved
        batch.requests_reserved -= attempt.requests_reserved
        batch.scanned_reserved -= attempt.scan_reserved
        attempt.requests_reserved = attempt.scan_reserved = 0
        query.provider_states = states
        return True
    from app.discovery.library import import_discovered_account, evaluate_candidate

    for account in page.accounts:
        contents = [
            content
            for content in page.contents
            if content.account_id == account.account_id
            and content.platform == account.platform
        ]
        creator = import_discovered_account(session, account, contents)
        if creator is None:
            continue
        eligible, notes = evaluate_candidate(
            session, creator, account, contents, query.conditions.get("filters", {})
        )
        if not eligible or query.result_count >= query.conditions.get(
            "result_limit", 600
        ):
            continue
        existing = session.scalar(
            select(DiscoveryCandidate.id).where(
                DiscoveryCandidate.query_id == query.id,
                DiscoveryCandidate.platform == account.platform,
                DiscoveryCandidate.account_id == account.account_id,
            )
        )
        if existing:
            continue
        query.result_count += 1
        session.add(
            DiscoveryCandidate(
                query_id=query.id,
                creator_id=creator.id,
                platform=account.platform,
                account_id=account.account_id,
                identity_revision=creator.identity_revision,
                account_snapshot=account.model_dump(mode="json"),
                filter_notes=notes,
                ordinal=query.result_count,
            )
        )
        session.flush()
    attempt.status = "applied"
    attempt.outcome = page.model_dump(
        mode="json", exclude={"accounts", "contents", "next_cursor"}
    )
    state_status = (
        "more"
        if page.status == "more" and page.next_cursor
        else ("exhausted" if page.status == "complete" else page.status)
    )
    states[attempt.platform] = {
        "status": state_status,
        "cursor": (
            page.next_cursor.model_dump(mode="json")
            if page.next_cursor
            else (attempt.input.get("cursor") if page.status != "complete" else None)
        ),
        "coverage": page.coverage,
        "provider_items_received": page.provider_items_received,
        "issues": [issue.model_dump(mode="json") for issue in page.issues],
    }
    query.provider_states = states
    if query.stop_requested:
        finish(query, batch, "stopped")
        return False
    return True


def run_discovery_batch(batch_id, *, session_factory, gateway_factory=None):
    batch_id = UUID(str(batch_id))
    gateway_factory = gateway_factory or production_gateway
    while True:
        with session_factory() as session:
            reserved = reserve(session, batch_id)
            session.commit()
        if reserved is None:
            return
        attempt_id, token, request = reserved
        page, failure = None, None
        try:
            with gateway_factory(request.platform) as gateway:
                page = gateway.discover(request)
            if page.platform != request.platform:
                raise ValueError("Provider platform mismatch")
        except MissingConnection:
            failure = "missing_connection"
        except Exception:
            failure = "outcome_unknown"
        with session_factory() as session:
            try:
                keep_running = apply_outcome(session, attempt_id, token, page, failure)
                session.commit()
            except Exception:
                # A page is indivisible: a failed import must not leave partial
                # candidates, source changes, or an advanced cursor behind.
                session.rollback()
                apply_outcome(session, attempt_id, token, None, "outcome_unknown")
                session.commit()
                keep_running = False
        if not keep_running:
            return


@celery_app.task(name=DISCOVERY_TASK_NAME, max_retries=0)
def run_batch(batch_id):
    run_discovery_batch(batch_id, session_factory=session_scope)
