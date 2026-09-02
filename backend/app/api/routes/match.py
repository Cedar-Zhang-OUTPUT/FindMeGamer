"""Authenticated Match creation, history, detail, and checkpoint retry API."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
import json
import secrets
from typing import Annotated, ContextManager, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.errors import APIError, safe_correlation_id
from app.core.idempotency import (
    IDEMPOTENCY_RETENTION,
    InvalidIdempotencyKey,
    request_hash,
    validate_idempotency_key,
)
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.jobs import acquire_job_change_lock
from app.db.models.match import (
    MatchCandidateInput,
    MatchPairwiseRecord,
    MatchResultGroup,
    MatchResultItem as StoredMatchResult,
    MatchScreeningRecord,
    MatchStage,
    MatchStatus,
    MatchTask,
    PairwiseState,
)
from app.db.models.outreach import Delivery, OutreachCampaign
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile
from app.repositories.match import MatchInputError, MatchRepository
from app.repositories.settings import SettingsRepository
from app.schemas.match import (
    MatchBrief,
    MatchCreate,
    MatchCreatorCard,
    MatchCreatorContact,
    MatchDetail,
    MatchDimensionOutcomes,
    MatchError,
    MatchGameHeader,
    MatchOutreachState,
    MatchPage,
    MatchResultItem,
    MatchSummary,
)
from app.workers.match_tasks import FINALIZE_MATCH_TASK_NAME, START_MATCH_TASK_NAME


SessionFactory = Callable[[], ContextManager[Session]]
Clock = Callable[[], datetime]
SeedFactory = Callable[[], int]
_CURSOR_LIMIT = 2048


class MatchAPIDispatcher(Protocol):
    def dispatch(self, task_name: str, task_id: UUID) -> None: ...


class CeleryMatchAPIDispatcher:
    def dispatch(self, task_name: str, task_id: UUID) -> None:
        if task_name not in {START_MATCH_TASK_NAME, FINALIZE_MATCH_TASK_NAME}:
            raise ValueError("invalid Match task name")
        if type(task_id) is not UUID or task_id.int == 0:
            raise ValueError("invalid Match task ID")
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            task_name,
            args=[str(task_id)],
            retry=False,
            ignore_result=True,
        )


def random_signed_64_bit() -> int:
    return secrets.randbits(64) - 2**63


_RETRYABLE_FAILURES = frozenset(
    {
        "deepseek_model_output_invalid",
        "deepseek_unavailable",
        "match_database_unavailable",
        "match_internal_error",
        "match_queue_unavailable",
    }
)
_PERMANENT_FAILURES = frozenset(
    {
        "deepseek_configuration_invalid",
        "deepseek_input_invalid",
        "deepseek_request_rejected",
        "deepseek_response_invalid",
        "deepseek_response_too_large",
        "locked_creator_identity_invalid",
        "locked_creator_profile_invalid",
        "locked_game_brief_invalid",
        "match_candidate_not_selected",
        "match_checkpoint_invalid",
        "match_clock_invalid",
        "match_pair_checkpoint_invalid",
        "match_pair_identity_invalid",
        "match_pair_not_found",
        "match_pair_not_runnable",
        "match_pair_not_running",
        "match_task_not_found",
        "match_task_not_preparable",
        "match_task_not_rankable",
        "match_publication_invalid",
        "match_ranking_checkpoint_invalid",
        "screening_output_invalid",
        "screening_output_unknown_creator",
    }
)


def _aware_utc(clock: Clock) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise APIError(
            status_code=500,
            code="match_clock_invalid",
            message="Match could not be completed. Please retry.",
        )
    return value.astimezone(UTC)


def _failure(task: MatchTask) -> tuple[MatchError | None, bool]:
    if task.status not in {MatchStatus.FAILED, MatchStatus.SUPERSEDED}:
        return None, False
    code = task.error_code
    if code == "match_queue_unavailable":
        return (
            MatchError(code=code, message="Match could not be queued. Please retry."),
            True,
        )
    if code in _RETRYABLE_FAILURES:
        message = (
            "Match failed unexpectedly. Please retry."
            if code == "match_internal_error"
            else "Match is temporarily unavailable. Please retry."
        )
        return MatchError(code=code, message=message), task.status is MatchStatus.FAILED
    if code in _PERMANENT_FAILURES:
        return (
            MatchError(
                code=code, message="Match could not be completed. Please retry."
            ),
            False,
        )
    return (
        MatchError(
            code="match_internal_error",
            message="Match failed unexpectedly. Please retry.",
        ),
        task.status is MatchStatus.FAILED,
    )


def _game_header(game: GameProfile) -> MatchGameHeader:
    facts = game.current_facts if isinstance(game.current_facts, dict) else {}
    cover = next(
        (
            value
            for key in (
                "cover_image_url",
                "cover_url",
                "header_image",
                "header_image_url",
                "image_url",
            )
            if isinstance((value := facts.get(key)), str) and value
        ),
        None,
    )
    return MatchGameHeader(
        id=game.id,
        name=game.sort_name,
        steam_app_id=game.steam_app_id,
        canonical_url=game.canonical_url,
        cover_url=cover,
    )


def project_match_summary(task: MatchTask, game: GameProfile) -> MatchSummary:
    error, retryable = _failure(task)
    if task.completed_units > task.total_units or task.result_count > task.total_units:
        raise APIError(
            status_code=500,
            code="match_state_invalid",
            message="The Match state is invalid.",
        )
    return MatchSummary(
        id=task.id,
        game=_game_header(game),
        status=task.status.value,
        stage=task.stage.value,
        completed_units=task.completed_units,
        total_units=task.total_units,
        result_count=task.result_count,
        retryable=retryable and bool(task.retryable),
        error=error,
        correlation_id=safe_correlation_id(task.correlation_id),
        supersedes_id=task.supersedes_id,
        created_at=task.created_at.astimezone(UTC),
        updated_at=task.updated_at.astimezone(UTC),
        started_at=task.started_at.astimezone(UTC) if task.started_at else None,
        completed_at=task.completed_at.astimezone(UTC) if task.completed_at else None,
    )


def _is_stale_status(value: object) -> bool:
    if isinstance(value, str):
        return value.casefold() == "stale"
    if isinstance(value, dict):
        return any(
            _is_stale_status(value.get(key))
            for key in ("status", "state", "freshness")
            if key in value
        )
    return False


def _creator_is_stale(source_status: object) -> bool:
    if not isinstance(source_status, dict):
        return False
    direct = (
        "status",
        "state",
        "freshness",
        "youtube",
        "youtube_status",
        "youtube_state",
        "youtube_freshness",
    )
    if any(
        _is_stale_status(source_status.get(key))
        for key in direct
        if key in source_status
    ):
        return True
    sources = source_status.get("sources")
    return isinstance(sources, dict) and _is_stale_status(sources.get("youtube"))


def _selected_contact(
    contacts: list[CreatorContact], *, manual_only: bool = False
) -> MatchCreatorContact | None:
    active = [value for value in contacts if value.is_active]
    manual = sorted(
        (value for value in active if value.is_manual),
        key=lambda value: (value.created_at, str(value.id)),
    )
    if manual:
        selected = manual[0]
        source = "manual"
    else:
        if manual_only:
            return None
        validation_rank = {"verified": 3, "valid": 2, "unverified": 1, "invalid": 0}
        discovered = sorted(
            (value for value in active if not value.is_manual),
            key=lambda value: (
                -value.priority,
                -validation_rank.get(value.validation_state.casefold(), -1),
                value.created_at,
                str(value.id),
            ),
        )
        if not discovered:
            return None
        selected = discovered[0]
        source = selected.source_type
    return MatchCreatorContact(
        email=selected.email,
        source=source,
        source_url=selected.source_url,
        validation_state=selected.validation_state,
    )


def _bounded_count(value: object) -> int | None:
    if type(value) is int:
        candidate = value
    elif type(value) is float:
        decimal = Decimal(str(value))
        if not decimal.is_finite():
            return None
        candidate = int(decimal.to_integral_value(rounding=ROUND_HALF_UP))
    else:
        return None
    return candidate if 0 <= candidate <= 2**63 - 1 else None


def _available_text(value: object) -> str | None:
    if not isinstance(value, dict) or value.get("status") != "available":
        return None
    text = value.get("value")
    return text if isinstance(text, str) and 0 < len(text) <= 2000 else None


def _creator_card(creator: CreatorProfile) -> MatchCreatorCard:
    stale = _creator_is_stale(creator.source_status)
    facts = (
        creator.current_facts
        if not stale and isinstance(creator.current_facts, dict)
        else {}
    )
    analysis = (
        creator.analysis if not stale and isinstance(creator.analysis, dict) else {}
    )
    brief = creator.brief if not stale and isinstance(creator.brief, dict) else {}
    metrics = facts.get("recent_metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    contact = _selected_contact(list(creator.contacts), manual_only=stale)
    title = facts.get("title")
    avatar = facts.get("avatar_url")
    performance = _available_text(analysis.get("recent_performance_summary"))
    if performance is None:
        performance = _available_text(brief.get("performance_context"))
    if performance is None:
        flat_performance = facts.get("performance_summary")
        performance = (
            flat_performance
            if isinstance(flat_performance, str) and 0 < len(flat_performance) <= 2000
            else None
        )
    return MatchCreatorCard(
        id=creator.id,
        name=title if isinstance(title, str) and title else creator.sort_name,
        youtube_channel_id=creator.youtube_channel_id,
        canonical_url=creator.canonical_url,
        avatar_url=avatar if isinstance(avatar, str) and avatar else None,
        favorite=creator.favorite,
        subscriber_count=_bounded_count(facts.get("subscriber_count")),
        recent_average_views=_bounded_count(
            metrics.get("average_views", facts.get("recent_average_views"))
        ),
        recent_median_views=_bounded_count(
            metrics.get("median_views", facts.get("recent_median_views"))
        ),
        performance_summary=performance,
        contact_available=contact is not None,
        contact=contact,
    )


def _result_projection(
    row: StoredMatchResult,
    creator: CreatorProfile,
    delivery: Delivery | None,
) -> MatchResultItem:
    brief = row.match_brief if isinstance(row.match_brief, dict) else {}
    public_brief = {key: brief.get(key) for key in MatchBrief.model_fields}
    outreach = MatchOutreachState()
    if delivery is not None:
        outreach = MatchOutreachState(
            send_state=delivery.send_state.value,
            response_state=delivery.response_state.value,
            delivery_id=delivery.id,
        )
    return MatchResultItem(
        creator=_creator_card(creator),
        result_group=(
            row.result_group.value
            if hasattr(row.result_group, "value")
            else row.result_group
        ),
        qualitative_label=(
            row.qualitative_label.value
            if hasattr(row.qualitative_label, "value")
            else row.qualitative_label
        ),
        dimension_outcomes=MatchDimensionOutcomes.model_validate(
            row.dimension_outcomes
        ),
        match_reasons=tuple(row.match_reasons),
        match_brief=MatchBrief.model_validate(public_brief),
        outreach=outreach,
    )


def project_match_detail(
    session: Session, task: MatchTask, game: GameProfile
) -> MatchDetail:
    summary = project_match_summary(task, game)
    if task.status is not MatchStatus.SUCCEEDED:
        return MatchDetail(
            **summary.model_dump(),
            result_state="pending",
            recommended_matches=[],
            other_matches=[],
        )
    rows = session.scalars(
        select(StoredMatchResult)
        .where(StoredMatchResult.match_task_id == task.id)
        .order_by(
            case(
                (StoredMatchResult.result_group == MatchResultGroup.RECOMMENDED, 0),
                else_=1,
            ),
            StoredMatchResult.backend_order,
        )
    ).all()
    if len(rows) != task.result_count:
        raise APIError(
            status_code=500,
            code="match_result_invalid",
            message="The Match result is invalid.",
        )
    campaigns = session.scalars(
        select(OutreachCampaign).where(OutreachCampaign.match_task_id == task.id)
    ).all()
    if len(campaigns) != 1:
        raise APIError(
            status_code=500,
            code="match_result_invalid",
            message="The Match result is invalid.",
        )
    creators = {
        value.id: value
        for value in session.scalars(
            select(CreatorProfile)
            .options(selectinload(CreatorProfile.contacts))
            .where(CreatorProfile.id.in_({row.creator_id for row in rows}))
        )
    }
    deliveries = {
        value.creator_id: value
        for value in session.scalars(
            select(Delivery).where(
                Delivery.campaign_id == campaigns[0].id,
                Delivery.superseded_at.is_(None),
            )
        )
    }
    projected: list[MatchResultItem] = []
    for row in rows:
        creator = creators.get(row.creator_id)
        if creator is None:
            raise APIError(
                status_code=500,
                code="match_result_invalid",
                message="The Match result is invalid.",
            )
        projected.append(
            _result_projection(row, creator, deliveries.get(row.creator_id))
        )
    return MatchDetail(
        **summary.model_dump(),
        result_state="no_suitable_creators" if not rows else "available",
        recommended_matches=[
            item for item in projected if item.result_group == "recommended"
        ],
        other_matches=[item for item in projected if item.result_group == "other"],
    )


def _idempotency_key(raw: str | None) -> str:
    try:
        return validate_idempotency_key(raw)
    except InvalidIdempotencyKey:
        raise APIError(
            status_code=400,
            code="idempotency_key_invalid",
            message="A valid Idempotency-Key is required.",
        ) from None


def _idempotency_conflict() -> APIError:
    return APIError(
        status_code=409,
        code="idempotency_key_conflict",
        message="The Idempotency-Key was already used for another request.",
    )


def _record_for_update(session: Session, key: str) -> IdempotencyRecord | None:
    return session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.key == key).with_for_update()
    )


def _store_idempotency(
    session: Session,
    *,
    key: str,
    digest: str,
    path: str,
    body: dict,
    now: datetime,
) -> None:
    session.add(
        IdempotencyRecord(
            key=key,
            request_hash=digest,
            method="POST",
            path=path,
            response_status=202,
            response_body=body,
            expires_at=now + IDEMPOTENCY_RETENTION,
        )
    )


def _task_and_game(session: Session, task_id: UUID, *, lock: bool = False):
    statement = select(MatchTask).where(MatchTask.id == task_id)
    if lock:
        statement = statement.with_for_update()
    task = session.scalar(statement)
    if task is None:
        return None, None
    return task, session.get(GameProfile, task.game_id)


def _safe_response(session: Session, task_id: UUID) -> dict:
    task, game = _task_and_game(session, task_id)
    if task is None or game is None:
        raise APIError(
            status_code=500,
            code="match_state_invalid",
            message="The Match state is invalid.",
        )
    return project_match_summary(task, game).model_dump(mode="json")


def _existing_replay(
    session: Session, *, key: str, digest: str, now: datetime
) -> tuple[UUID | None, IdempotencyRecord | None]:
    record = _record_for_update(session, key)
    if record is None:
        return None, None
    if record.expires_at is not None and record.expires_at <= now:
        session.delete(record)
        session.flush()
        return None, None
    if record.request_hash != digest:
        raise _idempotency_conflict()
    try:
        task_id = UUID(record.response_body["id"])
    except (KeyError, TypeError, ValueError):
        raise APIError(
            status_code=500,
            code="match_state_invalid",
            message="The Match state is invalid.",
        ) from None
    return task_id, record


def _required_resume_stage(session: Session, task: MatchTask) -> str:
    if task.locked_game_brief is None:
        raise APIError(
            status_code=409,
            code="match_inputs_expired",
            message="The Match inputs can no longer be resumed.",
        )
    screenings = session.scalars(
        select(MatchScreeningRecord).where(
            MatchScreeningRecord.match_task_id == task.id
        )
    ).all()
    if task.stage is MatchStage.SCREENING:
        if any(row.locked_creator_brief is None for row in screenings):
            raise APIError(
                status_code=409,
                code="match_checkpoint_invalid",
                message="The Match checkpoint is invalid.",
            )
        return START_MATCH_TASK_NAME
    selected = {row.creator_id for row in screenings if row.selected}
    candidates = {
        row.creator_id: row
        for row in session.scalars(
            select(MatchCandidateInput).where(
                MatchCandidateInput.match_task_id == task.id
            )
        )
    }
    if (
        not selected
        or set(candidates) != selected
        or any(row.locked_creator_profile is None for row in candidates.values())
    ):
        raise APIError(
            status_code=409,
            code="match_checkpoint_invalid",
            message="The Match checkpoint is invalid.",
        )
    pairs = session.scalars(
        select(MatchPairwiseRecord).where(MatchPairwiseRecord.match_task_id == task.id)
    ).all()
    if task.stage is MatchStage.PAIRWISE and any(
        row.state is PairwiseState.FAILED and not row.retryable for row in pairs
    ):
        raise APIError(
            status_code=409,
            code="match_not_retryable",
            message="This Match cannot be retried.",
        )
    if task.stage is MatchStage.RANKING:
        if {row.creator_id for row in pairs} != selected or any(
            row.state is not PairwiseState.SUCCEEDED or row.match_brief is None
            for row in pairs
        ):
            raise APIError(
                status_code=409,
                code="match_checkpoint_invalid",
                message="The Match checkpoint is invalid.",
            )
        return FINALIZE_MATCH_TASK_NAME
    return START_MATCH_TASK_NAME


def _mark_queue_failure(
    session_factory: SessionFactory, task_id: UUID, key: str, now: datetime
) -> dict:
    with session_factory() as session:
        acquire_job_change_lock(session)
        task, game = _task_and_game(session, task_id, lock=True)
        if task is None or game is None:
            raise APIError(
                status_code=500,
                code="match_state_invalid",
                message="The Match state is invalid.",
            )
        if task.status in {MatchStatus.QUEUED, MatchStatus.RUNNING}:
            task.status = MatchStatus.FAILED
            task.error_code = "match_queue_unavailable"
            task.error_message = "Match could not be queued. Please retry."
            task.retryable = True
            task.completed_at = now
            session.flush()
        body = project_match_summary(task, game).model_dump(mode="json")
        record = _record_for_update(session, key)
        if record is not None and record.response_body.get("id") == str(task.id):
            record.response_body = body
        session.commit()
        return body


def _cursor_timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _cursor_signature(payload: dict, key: bytes) -> str:
    return hmac.new(
        key,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()


def _encode_cursor(value: tuple[datetime, UUID], key: bytes) -> str:
    signed = {
        "v": 1,
        "key": [_cursor_timestamp(value[0]), str(value[1])],
        "scope": "matches",
    }
    payload = {**signed, "signature": _cursor_signature(signed, key)}
    return (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


def _invalid_cursor() -> APIError:
    return APIError(
        status_code=400,
        code="match_cursor_invalid",
        message="The Match cursor is invalid.",
    )


def _decode_cursor(raw: str | None, key: bytes) -> tuple[datetime, UUID] | None:
    if raw is None:
        return None
    if not raw or len(raw) > _CURSOR_LIMIT:
        raise _invalid_cursor()
    try:
        decoded = base64.b64decode(
            raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True
        )
        if base64.urlsafe_b64encode(decoded).decode().rstrip("=") != raw:
            raise ValueError
        value = json.loads(decoded)
        if (
            set(value) != {"v", "key", "scope", "signature"}
            or value["v"] != 1
            or value["scope"] != "matches"
            or len(value["key"]) != 2
        ):
            raise ValueError
        signed = {"v": value["v"], "key": value["key"], "scope": value["scope"]}
        if not hmac.compare_digest(value["signature"], _cursor_signature(signed, key)):
            raise ValueError
        timestamp_text, id_text = value["key"]
        if not timestamp_text.endswith("Z"):
            raise ValueError
        timestamp = datetime.fromisoformat(timestamp_text[:-1] + "+00:00")
        task_id = UUID(id_text)
        if _cursor_timestamp(timestamp) != timestamp_text or str(task_id) != id_text:
            raise ValueError
        return timestamp, task_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        raise _invalid_cursor() from None


def create_router(
    authenticate_workspace: Callable,
    *,
    session_factory: SessionFactory,
    dispatcher: MatchAPIDispatcher | None,
    clock: Clock,
    seed_factory: SeedFactory,
    cursor_signing_secret: str,
) -> APIRouter:
    effective_dispatcher = dispatcher or CeleryMatchAPIDispatcher()
    cursor_key = hashlib.sha256(
        b"find-me-gamer/match-cursor/v1\0" + cursor_signing_secret.encode()
    ).digest()
    router = APIRouter(
        prefix="/api/v1/matches",
        tags=["matches"],
        dependencies=[Depends(authenticate_workspace)],
    )

    def dispatch(
        task_id: UUID, task_name: str, key: str, now: datetime, body: dict
    ) -> JSONResponse:
        try:
            effective_dispatcher.dispatch(task_name, task_id)
            return JSONResponse(status_code=202, content=body)
        except APIError:
            raise
        except Exception:
            body = _mark_queue_failure(session_factory, task_id, key, now)
            return JSONResponse(status_code=202, content=body)

    @router.post(
        "", response_model=MatchSummary, status_code=202, operation_id="createMatch"
    )
    def create_match(
        payload: MatchCreate,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> JSONResponse:
        key = _idempotency_key(idempotency_key)
        path = "/api/v1/matches"
        digest = request_hash(
            method="POST",
            path=path,
            canonical_request={"game_id": str(payload.game_id)},
        )
        now = _aware_utc(clock)
        for _attempt in range(3):
            with session_factory() as session:
                try:
                    acquire_job_change_lock(session)
                    replay_id, _record = _existing_replay(
                        session, key=key, digest=digest, now=now
                    )
                    if replay_id is not None:
                        body = _safe_response(session, replay_id)
                        session.commit()
                        return JSONResponse(status_code=202, content=body)
                    if session.get(GameProfile, payload.game_id) is None:
                        raise APIError(
                            status_code=404,
                            code="game_profile_not_found",
                            message="The Game Profile was not found.",
                        )
                    threshold = Decimal(
                        SettingsRepository(session)
                        .get_reanalysis()
                        .recommended_match_threshold
                    )
                    try:
                        task = MatchRepository(
                            session, clock=lambda: now
                        ).create_locked_task(payload.game_id, seed_factory(), threshold)
                    except MatchInputError as error:
                        if str(error) == "game_profile_not_found":
                            raise APIError(
                                status_code=404,
                                code="game_profile_not_found",
                                message="The Game Profile was not found.",
                            ) from None
                        raise APIError(
                            status_code=409,
                            code="game_profile_unusable",
                            message="The Game Profile cannot be used for Match.",
                        ) from None
                    task.correlation_id = request.state.correlation_id
                    session.flush()
                    game = session.get(GameProfile, task.game_id)
                    body = project_match_summary(task, game).model_dump(mode="json")
                    _store_idempotency(
                        session, key=key, digest=digest, path=path, body=body, now=now
                    )
                    session.commit()
                    return dispatch(task.id, START_MATCH_TASK_NAME, key, now, body)
                except IntegrityError:
                    session.rollback()
        raise APIError(
            status_code=503,
            code="match_creation_conflict",
            message="The Match request could not be committed safely.",
            retryable=True,
        )

    @router.get("", response_model=MatchPage, operation_id="listMatches")
    def list_matches(
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> MatchPage:
        decoded = _decode_cursor(cursor, cursor_key)
        with session_factory() as session:
            statement = select(MatchTask)
            if decoded is not None:
                statement = statement.where(
                    (MatchTask.created_at < decoded[0])
                    | (
                        (MatchTask.created_at == decoded[0])
                        & (MatchTask.id < decoded[1])
                    )
                )
            rows = session.scalars(
                statement.order_by(
                    MatchTask.created_at.desc(), MatchTask.id.desc()
                ).limit(limit + 1)
            ).all()
            page = list(rows[:limit])
            games = {
                value.id: value
                for value in session.scalars(
                    select(GameProfile).where(
                        GameProfile.id.in_({row.game_id for row in page})
                    )
                )
            }
            items = []
            for row in page:
                game = games.get(row.game_id)
                if game is None:
                    raise APIError(
                        status_code=500,
                        code="match_state_invalid",
                        message="The Match state is invalid.",
                    )
                items.append(project_match_summary(row, game))
            next_cursor = (
                _encode_cursor((page[-1].created_at, page[-1].id), cursor_key)
                if len(rows) > limit
                else None
            )
            session.commit()
            return MatchPage(
                items=items, cursor=next_cursor, has_more=len(rows) > limit
            )

    @router.get("/{match_task_id}", response_model=MatchDetail, operation_id="getMatch")
    def get_match(match_task_id: UUID) -> MatchDetail:
        with session_factory() as session:
            task, game = _task_and_game(session, match_task_id)
            if task is None or game is None:
                raise APIError(
                    status_code=404,
                    code="match_not_found",
                    message="The Match was not found.",
                )
            response = project_match_detail(session, task, game)
            session.commit()
            return response

    @router.post(
        "/{match_task_id}/retry",
        response_model=MatchSummary,
        status_code=202,
        operation_id="retryMatch",
    )
    def retry_match(
        match_task_id: UUID,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> JSONResponse:
        key = _idempotency_key(idempotency_key)
        path = f"/api/v1/matches/{match_task_id}/retry"
        digest = request_hash(
            method="POST",
            path=path,
            canonical_request={"source_match_id": str(match_task_id)},
        )
        now = _aware_utc(clock)
        for _attempt in range(3):
            with session_factory() as session:
                try:
                    acquire_job_change_lock(session)
                    replay_id, _record = _existing_replay(
                        session, key=key, digest=digest, now=now
                    )
                    if replay_id is not None:
                        body = _safe_response(session, replay_id)
                        session.commit()
                        return JSONResponse(status_code=202, content=body)
                    source, _game = _task_and_game(session, match_task_id, lock=True)
                    if source is None:
                        raise APIError(
                            status_code=404,
                            code="match_not_found",
                            message="The failed Match was not found.",
                        )
                    successor = session.scalar(
                        select(MatchTask)
                        .where(MatchTask.supersedes_id == source.id)
                        .with_for_update()
                    )
                    if (
                        source.status is MatchStatus.SUPERSEDED
                        and successor is not None
                    ):
                        task, task_name, should_dispatch = (
                            successor,
                            START_MATCH_TASK_NAME,
                            False,
                        )
                    else:
                        if (
                            source.status is not MatchStatus.FAILED
                            or not source.retryable
                        ):
                            raise APIError(
                                status_code=409,
                                code="match_not_retryable",
                                message="This Match cannot be retried.",
                            )
                        if source.input_expires_at > now:
                            task_name = _required_resume_stage(session, source)
                            source.status = MatchStatus.RUNNING
                            source.error_code = None
                            source.error_message = None
                            source.retryable = False
                            source.completed_at = None
                            source.started_at = source.started_at or now
                            task, should_dispatch = source, True
                        else:
                            if successor is None:
                                threshold = Decimal(
                                    SettingsRepository(session)
                                    .get_reanalysis()
                                    .recommended_match_threshold
                                )
                                try:
                                    successor = MatchRepository(
                                        session, clock=lambda: now
                                    ).create_locked_task(
                                        source.game_id, seed_factory(), threshold
                                    )
                                except MatchInputError:
                                    raise APIError(
                                        status_code=409,
                                        code="match_current_inputs_unusable",
                                        message="Current Match inputs are unavailable.",
                                    ) from None
                                successor.supersedes_id = source.id
                            source.status = MatchStatus.SUPERSEDED
                            source.retryable = False
                            source.completed_at = source.completed_at or now
                            task, task_name, should_dispatch = (
                                successor,
                                START_MATCH_TASK_NAME,
                                True,
                            )
                    session.flush()
                    game = session.get(GameProfile, task.game_id)
                    body = project_match_summary(task, game).model_dump(mode="json")
                    _store_idempotency(
                        session, key=key, digest=digest, path=path, body=body, now=now
                    )
                    session.commit()
                    if not should_dispatch:
                        return JSONResponse(status_code=202, content=body)
                    return dispatch(task.id, task_name, key, now, body)
                except IntegrityError:
                    session.rollback()
        raise APIError(
            status_code=503,
            code="match_retry_conflict",
            message="The Match retry could not be committed safely.",
            retryable=True,
        )

    return router


__all__ = [
    "CeleryMatchAPIDispatcher",
    "create_router",
    "project_match_detail",
    "project_match_summary",
    "random_signed_64_bit",
]
