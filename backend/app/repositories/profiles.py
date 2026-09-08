from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar
from uuid import UUID

from sqlalchemy import Select, cast, func, literal, select, tuple_, union_all, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, selectinload

from app.db.models.enums import JobStatus, TargetType
from app.db.models.jobs import AnalysisJob, acquire_job_change_lock
from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile


ProfileT = TypeVar("ProfileT", GameProfile, CreatorProfile)
CursorValue = tuple[str, UUID]


@dataclass(frozen=True, slots=True)
class DueProfile:
    next_analysis_at: datetime
    target_type: TargetType
    profile_id: UUID
    canonical_target_id: str
    canonical_url: str


class ProfilesRepository:
    def __init__(self, database_session: Session) -> None:
        self._session = database_session

    def list_games(
        self,
        *,
        query: str,
        only_collection: bool,
        cursor: CursorValue | None,
        limit: int,
    ) -> tuple[Sequence[GameProfile], bool]:
        statement = select(GameProfile).where(GameProfile.steam_app_id.is_not(None))
        statement = self._apply_filters(
            statement,
            GameProfile,
            query=query,
            only_collection=only_collection,
            cursor=cursor,
        )
        rows = self._session.scalars(statement.limit(limit + 1)).all()
        return rows[:limit], len(rows) > limit

    def list_creators(
        self,
        *,
        query: str,
        only_collection: bool,
        cursor: CursorValue | None,
        limit: int,
    ) -> tuple[Sequence[CreatorProfile], bool]:
        statement = select(CreatorProfile).options(
            selectinload(CreatorProfile.contacts)
        )
        statement = self._apply_filters(
            statement,
            CreatorProfile,
            query=query,
            only_collection=only_collection,
            cursor=cursor,
        )
        rows = self._session.scalars(statement.limit(limit + 1)).all()
        return rows[:limit], len(rows) > limit

    def cursor_matches(
        self,
        profile_type: str,
        cursor: CursorValue,
        *,
        query: str,
        only_collection: bool,
    ) -> bool:
        model = GameProfile if profile_type == "games" else CreatorProfile
        sort_name, profile_id = cursor
        statement = select(model.id).where(
            model.id == profile_id,
            model.sort_name == sort_name,
        )
        if profile_type == "games":
            statement = statement.where(GameProfile.steam_app_id.is_not(None))
        statement = self._apply_search_and_collection(
            statement,
            model,
            query=query,
            only_collection=only_collection,
        )
        return self._session.scalar(statement) is not None

    def get_game(self, profile_id: UUID) -> GameProfile | None:
        return self._session.scalar(
            select(GameProfile).where(
                GameProfile.id == profile_id, GameProfile.steam_app_id.is_not(None)
            )
        )

    def get_creator(self, profile_id: UUID) -> CreatorProfile | None:
        return self._session.scalar(
            select(CreatorProfile)
            .where(CreatorProfile.id == profile_id)
            .options(selectinload(CreatorProfile.contacts))
        )

    def get_creator_for_update(self, profile_id: UUID) -> CreatorProfile | None:
        acquire_job_change_lock(self._session)
        return self._session.scalar(
            select(CreatorProfile)
            .where(CreatorProfile.id == profile_id)
            .with_for_update()
            .options(selectinload(CreatorProfile.contacts))
        )

    def list_due_profiles(self, *, now: datetime, limit: int) -> list[DueProfile]:
        active_game = (
            select(AnalysisJob.id)
            .where(
                AnalysisJob.target_type == TargetType.GAME,
                AnalysisJob.canonical_target_id == GameProfile.steam_app_id,
                AnalysisJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
            )
            .exists()
        )
        active_creator = (
            select(AnalysisJob.id)
            .where(
                AnalysisJob.target_type == TargetType.CREATOR,
                AnalysisJob.canonical_target_id == CreatorProfile.youtube_channel_id,
                AnalysisJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
            )
            .exists()
        )
        due = union_all(
            select(
                GameProfile.next_analysis_at.label("next_analysis_at"),
                literal(TargetType.GAME.value).label("target_type"),
                GameProfile.id.label("profile_id"),
                GameProfile.steam_app_id.label("canonical_target_id"),
                GameProfile.canonical_url.label("canonical_url"),
            ).where(
                GameProfile.next_analysis_at.is_not(None),
                GameProfile.steam_app_id.is_not(None),
                GameProfile.next_analysis_at <= now,
                ~active_game,
            ),
            select(
                CreatorProfile.next_analysis_at.label("next_analysis_at"),
                literal(TargetType.CREATOR.value).label("target_type"),
                CreatorProfile.id.label("profile_id"),
                CreatorProfile.youtube_channel_id.label("canonical_target_id"),
                CreatorProfile.canonical_url.label("canonical_url"),
            ).where(
                CreatorProfile.next_analysis_at.is_not(None),
                CreatorProfile.next_analysis_at <= now,
                ~active_creator,
            ),
        ).subquery()
        rows = self._session.execute(
            select(due)
            .order_by(
                due.c.next_analysis_at,
                due.c.target_type,
                due.c.profile_id,
            )
            .limit(limit)
        ).all()
        return [
            DueProfile(
                next_analysis_at=row.next_analysis_at,
                target_type=TargetType(row.target_type),
                profile_id=row.profile_id,
                canonical_target_id=row.canonical_target_id,
                canonical_url=row.canonical_url,
            )
            for row in rows
        ]

    def mark_stale_creators(self, now: datetime) -> int:
        cutoff = now - timedelta(days=30)
        stale_patch = cast(
            {"youtube": "stale", "freshness": "stale"},
            JSONB,
        )
        result = self._session.execute(
            update(CreatorProfile)
            .where(
                CreatorProfile.last_analyzed_at.is_not(None),
                CreatorProfile.last_analyzed_at < cutoff,
                (
                    func.lower(
                        CreatorProfile.source_status["youtube"].astext
                    ).is_distinct_from("stale")
                    | func.lower(
                        CreatorProfile.source_status["freshness"].astext
                    ).is_distinct_from("stale")
                ),
            )
            .values(source_status=CreatorProfile.source_status.op("||")(stale_patch))
            .execution_options(synchronize_session=False)
        )
        return result.rowcount

    def set_game_favorite(
        self, profile_id: UUID, *, favorite: bool
    ) -> GameProfile | None:
        profile = self.get_game(profile_id)
        if profile is None:
            return None
        profile.favorite = favorite
        self._session.flush()
        return profile

    def set_creator_favorite(
        self, profile_id: UUID, *, favorite: bool
    ) -> CreatorProfile | None:
        profile = self.get_creator(profile_id)
        if profile is None:
            return None
        profile.favorite = favorite
        self._session.flush()
        return profile

    def update_creator_manual(
        self,
        profile_id: UUID,
        *,
        contact_email: str | None,
        notes: str | None,
    ) -> CreatorProfile | None:
        creator = self.get_creator_for_update(profile_id)
        if creator is None:
            return None

        creator.manual_notes = notes
        manual_contacts = sorted(
            (contact for contact in creator.contacts if contact.is_manual),
            key=lambda contact: (contact.created_at, str(contact.id)),
        )
        for contact in manual_contacts:
            contact.is_active = False

        if contact_email is not None:
            if manual_contacts:
                manual_contact = manual_contacts[0]
            else:
                manual_contact = CreatorContact(
                    creator_id=creator.id,
                    email=contact_email,
                    source_type="manual",
                    is_manual=True,
                    validation_state="unverified",
                    priority=0,
                    is_active=True,
                )
                creator.contacts.append(manual_contact)
            manual_contact.email = contact_email
            manual_contact.source_type = "manual"
            manual_contact.source_url = None
            manual_contact.is_manual = True
            manual_contact.validation_state = "unverified"
            manual_contact.priority = 0
            manual_contact.is_active = True

        self._session.flush()
        return creator

    @staticmethod
    def _apply_filters(
        statement: Select,
        model: type[ProfileT],
        *,
        query: str,
        only_collection: bool,
        cursor: CursorValue | None,
    ) -> Select:
        statement = ProfilesRepository._apply_search_and_collection(
            statement,
            model,
            query=query,
            only_collection=only_collection,
        )
        sort_column = model.sort_name.collate("C")
        if cursor is not None:
            statement = statement.where(
                tuple_(sort_column, model.id) > tuple_(cursor[0], cursor[1])
            )
        return statement.order_by(sort_column, model.id)

    @staticmethod
    def _apply_search_and_collection(
        statement: Select,
        model: type[ProfileT],
        *,
        query: str,
        only_collection: bool,
    ) -> Select:
        normalized_query = query.strip()
        if normalized_query:
            statement = statement.where(
                model.sort_name.icontains(normalized_query, autoescape=True)
            )
        if only_collection:
            statement = statement.where(model.favorite.is_(True))
        return statement
