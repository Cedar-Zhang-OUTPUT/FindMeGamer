from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select, text, tuple_
from sqlalchemy.orm import load_only

from app.analysis.targets import canonicalize_target
from app.core.errors import APIError
from app.core.idempotency import (
    validate_idempotency_key,
    InvalidIdempotencyKey,
    request_hash,
)
from app.db.models.discover import DiscoverJob
from app.db.models.discover import DiscoverCandidate
from app.db.models.discover_batch import DiscoverAnalysisBatch, DiscoverAnalysisItem
from app.repositories.discover_batch import DiscoverBatchRepository
from app.schemas.discover_batch import (
    DiscoverBatchCreate,
    DiscoverBatchDetail,
    DiscoverBatchHistory,
)
from app.db.models.enums import TargetType
from app.db.models.profiles import GameProfile
from app.db.models.settings import ServiceSecret
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.integrations.steam import SteamGateway
from app.core.config import get_settings
from app.repositories.discover import DiscoverRepository
from app.schemas.discover import (
    DiscoverCreate,
    DiscoverDetail,
    DiscoverPage,
    DiscoverCapabilities,
    DiscoverCapability,
    ResolveGameRequest,
    ResolveGameResponse,
)
from app.services.profile_editing import effective_name


def capabilities(session):
    configured = set(session.scalars(select(ServiceSecret.service)))
    return DiscoverCapabilities(
        platforms=[
            DiscoverCapability(
                platform=p,
                available=p in configured and p in {"youtube", "x"},
                reason=(
                    None
                    if p in configured and p in {"youtube", "x"}
                    else (
                        "Unavailable in this version."
                        if p in {"twitch", "instagram"}
                        else "Configure this platform in Settings."
                    )
                ),
            )
            for p in ("youtube", "x", "twitch", "instagram")
        ]
    )


def create_router(authenticate_workspace, *, session_factory):
    router = APIRouter(
        prefix="/api/v1/discover",
        tags=["Discover"],
        dependencies=[Depends(authenticate_workspace)],
    )

    @router.get(
        "/capabilities",
        response_model=DiscoverCapabilities,
        operation_id="getDiscoverCapabilities",
    )
    def get_capabilities():
        with session_factory() as session:
            return capabilities(session)

    @router.post(
        "/resolve-game",
        response_model=ResolveGameResponse,
        operation_id="resolveDiscoverGame",
    )
    def resolve_game(payload: ResolveGameRequest):
        target = canonicalize_target(TargetType.GAME, payload.steam_url)
        with session_factory() as session:
            game = session.scalar(
                select(GameProfile).where(
                    GameProfile.steam_app_id == target.canonical_id
                )
            )
            if game:
                return ResolveGameResponse(
                    steam_app_id=target.canonical_id,
                    canonical_url=target.canonical_url,
                    name=effective_name(game),
                    game_id=game.id,
                )
        try:
            with SteamGateway(base_url=get_settings().steam_store_base_url) as steam:
                source = steam.fetch_game(target.canonical_id)
        except (PermanentIntegrationError, TransientIntegrationError):
            raise APIError(
                502,
                "steam_resolution_unavailable",
                "Steam game information is unavailable. Please retry.",
                True,
            ) from None
        return ResolveGameResponse(
            steam_app_id=target.canonical_id,
            canonical_url=target.canonical_url,
            name=source.name,
        )

    @router.post(
        "",
        response_model=DiscoverDetail,
        status_code=202,
        operation_id="createDiscover",
    )
    def create(
        payload: DiscoverCreate,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ):
        try:
            key = validate_idempotency_key(idempotency_key)
        except InvalidIdempotencyKey:
            raise APIError(
                422, "idempotency_key_invalid", "Provide an Idempotency-Key."
            ) from None
        digest = request_hash(
            method="POST",
            path="/api/v1/discover",
            canonical_request=payload.model_dump(mode="json"),
        )
        with session_factory() as session:
            # Serialize same-key submission, including the first insert.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "discover:" + key},
            )
            repo = DiscoverRepository(session)
            prior = session.scalar(
                select(DiscoverJob).where(DiscoverJob.idempotency_key == key)
            )
            if prior:
                if prior.request_hash != digest:
                    raise APIError(
                        409,
                        "idempotency_conflict",
                        "This key was already used for a different request.",
                    )
                return repo.detail(prior)
            available = {
                p.platform for p in capabilities(session).platforms if p.available
            }
            if not set(payload.conditions.platforms) <= available:
                raise APIError(
                    422,
                    "discover_platform_unavailable",
                    "One or more selected platforms are unavailable.",
                )
            game = (
                session.get(GameProfile, payload.game_id)
                if payload.game_id
                else session.scalar(
                    select(GameProfile).where(
                        GameProfile.canonical_url == payload.steam_url
                    )
                )
            )
            if payload.game_id and not game:
                raise APIError(
                    404, "game_not_found", "The selected game was not found."
                )
            job = DiscoverJob(
                idempotency_key=key,
                request_hash=digest,
                game_id=game.id if game else None,
                steam_url=game.canonical_url if game else payload.steam_url,
                game_name=effective_name(game) if game else "Preparing game",
                conditions=payload.conditions.model_dump(),
            )
            session.add(job)
            session.flush()
            result = repo.detail(job)
            session.commit()
            return result

    @router.get("", response_model=DiscoverPage, operation_id="listDiscover")
    def history(
        cursor: str | None = Query(default=None, max_length=128),
        limit: int = Query(default=30, ge=1, le=100),
    ):
        with session_factory() as session:
            query = select(DiscoverJob).options(
                load_only(
                    DiscoverJob.id,
                    DiscoverJob.game_id,
                    DiscoverJob.game_name,
                    DiscoverJob.status,
                    DiscoverJob.stage,
                    DiscoverJob.issues,
                    DiscoverJob.created_at,
                    DiscoverJob.updated_at,
                )
            )
            if cursor:
                try:
                    timestamp, identifier = cursor.split("|")
                    date = datetime.fromisoformat(timestamp)
                    if date.tzinfo is None:
                        raise ValueError()
                    query = query.where(
                        tuple_(DiscoverJob.created_at, DiscoverJob.id)
                        < tuple_(date, UUID(identifier))
                    )
                except ValueError:
                    raise APIError(
                        422, "cursor_invalid", "Invalid history cursor."
                    ) from None
            rows = session.scalars(
                query.order_by(
                    DiscoverJob.created_at.desc(), DiscoverJob.id.desc()
                ).limit(limit + 1)
            ).all()
            page = rows[:limit]
            return DiscoverPage(
                items=DiscoverRepository(session).summaries(page),
                next_cursor=(
                    f"{page[-1].created_at.isoformat()}|{page[-1].id}"
                    if len(rows) > limit
                    else None
                ),
            )

    @router.get(
        "/{discover_id}", response_model=DiscoverDetail, operation_id="getDiscover"
    )
    def detail(discover_id: UUID):
        with session_factory() as session:
            repo = DiscoverRepository(session)
            job = repo.get(discover_id)
            if not job:
                raise APIError(404, "discover_not_found", "Discover request not found.")
            return repo.detail(job)

    @router.post(
        "/{discover_id}/retry",
        response_model=DiscoverDetail,
        status_code=202,
        operation_id="retryDiscover",
    )
    def retry(discover_id: UUID):
        with session_factory() as session:
            repo = DiscoverRepository(session)
            job = repo.get(discover_id, lock=True)
            if not job:
                raise APIError(404, "discover_not_found", "Discover request not found.")
            if job.status in {"partial", "failed"}:
                job.status = "queued"
                job.stage = (
                    "finding_creators" if job.game_snapshot else "preparing_game"
                )
                job.game_job_id = job.game_job_id if job.game_snapshot else None
                job.issues = []
                job.dispatched_at = None
                job.lease_token = None
                job.lease_until = None
                session.flush()
            result = repo.detail(job)
            session.commit()
            return result

    @router.post(
        "/{discover_id}/analysis-batches",
        response_model=DiscoverBatchDetail,
        status_code=202,
        operation_id="createDiscoverAnalysisBatch",
    )
    def create_batch(
        discover_id: UUID,
        payload: DiscoverBatchCreate,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ):
        try:
            key = validate_idempotency_key(idempotency_key)
        except InvalidIdempotencyKey:
            raise APIError(
                422, "idempotency_key_invalid", "Provide an Idempotency-Key."
            ) from None
        digest = request_hash(
            method="POST",
            path=f"/api/v1/discover/{discover_id}/analysis-batches",
            canonical_request=payload.model_dump(mode="json"),
        )
        with session_factory() as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "discover-batch:" + key},
            )
            repo = DiscoverBatchRepository(session)
            prior = session.scalar(
                select(DiscoverAnalysisBatch).where(
                    DiscoverAnalysisBatch.idempotency_key == key
                )
            )
            if prior:
                if prior.request_hash != digest:
                    raise APIError(
                        409,
                        "idempotency_conflict",
                        "This key was already used for a different request.",
                    )
                return repo.detail(prior)
            if session.get(DiscoverJob, discover_id) is None:
                raise APIError(404, "discover_not_found", "Discover request not found.")
            ids = set(
                session.scalars(
                    select(DiscoverCandidate.id).where(
                        DiscoverCandidate.discover_id == discover_id,
                        DiscoverCandidate.id.in_(payload.candidate_ids),
                    )
                )
            )
            if ids != set(payload.candidate_ids):
                raise APIError(
                    422,
                    "discover_selection_invalid",
                    "Select candidates from this Discover request.",
                )
            batch = DiscoverAnalysisBatch(
                discover_id=discover_id,
                idempotency_key=key,
                request_hash=digest,
                mode=payload.mode,
            )
            session.add(batch)
            session.flush()
            session.add_all(
                [
                    DiscoverAnalysisItem(batch_id=batch.id, candidate_id=value)
                    for value in payload.candidate_ids
                ]
            )
            session.flush()
            result = repo.detail(batch)
            session.commit()
            # Beat publishes this durable request, including after a lost HTTP response.
            return result

    @router.get(
        "/{discover_id}/analysis-batches",
        response_model=DiscoverBatchHistory,
        operation_id="listDiscoverAnalysisBatches",
    )
    def batch_history(discover_id: UUID):
        with session_factory() as session:
            if session.get(DiscoverJob, discover_id) is None:
                raise APIError(404, "discover_not_found", "Discover request not found.")
            rows = session.scalars(
                select(DiscoverAnalysisBatch)
                .where(DiscoverAnalysisBatch.discover_id == discover_id)
                .order_by(DiscoverAnalysisBatch.created_at.desc())
            ).all()
            return DiscoverBatchHistory(
                items=[DiscoverBatchRepository(session).detail(row) for row in rows]
            )

    @router.get(
        "/{discover_id}/analysis-batches/{batch_id}",
        response_model=DiscoverBatchDetail,
        operation_id="getDiscoverAnalysisBatch",
    )
    def batch_detail(discover_id: UUID, batch_id: UUID):
        with session_factory() as session:
            repo = DiscoverBatchRepository(session)
            batch = repo.get(batch_id)
            if batch is None or batch.discover_id != discover_id:
                raise APIError(
                    404, "discover_batch_not_found", "Analysis batch not found."
                )
            return repo.detail(batch)

    return router
