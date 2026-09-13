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
from app.repositories.collection_settings import collection_enabled
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
        "library_only",
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
    from app.discovery.library_candidates import scan_library

    scan_library(session, query, batch)
    if query.result_count >= limits.get("result_limit", 600):
        finish(query, batch, "result_limit")
        return None
    states = dict(query.provider_states)
    request = None
    providers = limits["providers"]
    if limits.get("query_directions"):
        # Rotate platforms as well as their directions: a busy YouTube cursor must
        # not spend every batch before X receives its first page.
        previous_platform = session.scalar(
            select(DiscoveryAttempt.platform)
            .join(DiscoveryBatch)
            .where(DiscoveryBatch.query_id == query.id)
            .order_by(DiscoveryBatch.ordinal.desc(), DiscoveryAttempt.sequence.desc())
            .limit(1)
        )
        platforms = [p["platform"] for p in providers]
        if previous_platform in platforms:
            offset = platforms.index(previous_platform) + 1
            providers = providers[offset:] + providers[:offset]
    for provider in providers:
        platform = provider["platform"]
        state = dict(states.get(platform, {}))
        state.pop("blocked_reason", None)
        states[platform] = state
        if platform not in ("youtube", "x"):
            states[platform] = {
                **state,
                "status": "not_supported",
                "issues": [{"code": "not_supported"}],
            }
            continue
        if state.get("status") != "exhausted" and not collection_enabled(
            session, platform
        ):
            states[platform] = {**state, "blocked_reason": "collection_disabled"}
            continue
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
        # Library results must not suppress the first live page per platform.
        # Further pages retain the existing batch target and provider cursor.
        if query.result_count - batch.initial_result_count >= batch.target_count:
            attempted = session.scalar(
                select(DiscoveryAttempt.id)
                .where(
                    DiscoveryAttempt.batch_id == batch.id,
                    DiscoveryAttempt.platform == platform,
                )
                .limit(1)
            )
            if attempted:
                continue
        raw = dict(provider)
        raw["cursor"] = state.get("cursor")
        if limits.get("query_directions", {}).get(platform):
            from app.discovery.directions import select_direction

            direction = select_direction(limits, platform, state)
            if direction is None:
                states[platform] = {**state, "status": "exhausted"}
                continue
            raw["query"], raw["cursor"] = direction
        request = DiscoveryRequest.model_validate(raw)
        break
    query.provider_states = states
    if request is None:
        statuses = {state.get("status") for state in states.values()}
        if any(
            state.get("library", {}).get("status") == "more"
            for state in states.values()
        ):
            reason = "library_more"
        elif any(
            state.get("blocked_reason") == "collection_disabled"
            for state in states.values()
        ):
            reason = "collection_disabled"
        elif "failed" in statuses:
            reason = "provider_failed"
        elif "partial" in statuses:
            reason = "source_partial"
        elif statuses.intersection({"missing_connection", "unavailable"}):
            reason = "source_unavailable"
        elif statuses == {"not_supported"}:
            reason = "library_only"
        elif (
            query.result_count - batch.initial_result_count >= batch.target_count
            and "more" in statuses
        ):
            reason = "target_reached"
        else:
            reason = "providers_finished"
        finish(query, batch, reason)
        return None
    cost = (
        (3 if request.max_requests >= 3 else 2) if request.platform == "youtube" else 1
    )
    scan = request.page_size
    if request.max_requests < cost:
        states[request.platform] = {
            **states.get(request.platform, {}),
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
            **states.get(attempt.platform, {}),
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
    from app.discovery.library_candidates import add_candidate

    filter_counts = {}
    added = eligible_count = 0
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
        if not eligible:
            for reason in notes.get("failed_filters", []):
                filter_counts[reason] = filter_counts.get(reason, 0) + 1
            continue
        eligible_count += 1
        added += int(add_candidate(session, query, creator, account, notes, "realtime"))
    attempt.status = "applied"
    attempt.outcome = page.model_dump(
        mode="json", exclude={"accounts", "contents", "next_cursor"}
    ) | {
        "accounts_received": len(page.accounts),
        "eligible_count": eligible_count,
        "added_count": added,
        "failed_filters": filter_counts,
    }
    state_status = (
        "more"
        if page.status == "more" and page.next_cursor
        else ("exhausted" if page.status == "complete" else page.status)
    )
    states[attempt.platform] = {
        **states.get(attempt.platform, {}),
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
    from app.discovery.directions import record_direction

    states[attempt.platform] = record_direction(
        query.conditions,
        attempt.platform,
        query.provider_states.get(attempt.platform, {}),
        states[attempt.platform],
        attempt.input,
    )
    query.provider_states = states
    if query.stop_requested:
        finish(query, batch, "stopped")
        return False
    return True


def run_discovery_batch(batch_id, *, session_factory, gateway_factory=None):
    from app.repositories.initial_selection import initialize_first_batch

    batch_id = UUID(str(batch_id))
    gateway_factory = gateway_factory or production_gateway
    while True:
        with session_factory() as session:
            reserved = reserve(session, batch_id)
            initialize_first_batch(session, batch_id)
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
                initialize_first_batch(session, batch_id)
                session.commit()
            except Exception:
                # A page is indivisible: a failed import must not leave partial
                # candidates, source changes, or an advanced cursor behind.
                session.rollback()
                apply_outcome(session, attempt_id, token, None, "outcome_unknown")
                initialize_first_batch(session, batch_id)
                session.commit()
                keep_running = False
        if not keep_running:
            return


@celery_app.task(name=DISCOVERY_TASK_NAME, max_retries=0)
def run_batch(batch_id):
    run_discovery_batch(batch_id, session_factory=session_scope)
