from sqlalchemy import select, tuple_, func

from app.db.models.discover import DiscoverJob, DiscoverCandidate
from app.db.models.profiles import CreatorProfile
from app.schemas.discover import (
    DiscoverDetail,
    DiscoverCandidateResponse,
    DiscoverSummary,
)


class DiscoverRepository:
    def __init__(self, session):
        self.session = session

    def get(self, job_id, *, lock=False):
        query = select(DiscoverJob).where(DiscoverJob.id == job_id)
        return self.session.scalar(query.with_for_update() if lock else query)

    def summaries(self, jobs):
        counts = (
            dict(
                self.session.execute(
                    select(DiscoverCandidate.discover_id, func.count())
                    .where(DiscoverCandidate.discover_id.in_([job.id for job in jobs]))
                    .group_by(DiscoverCandidate.discover_id)
                ).all()
            )
            if jobs
            else {}
        )
        return [
            DiscoverSummary(
                id=job.id,
                game_id=job.game_id,
                game_name=job.game_name,
                status=job.status,
                stage=job.stage,
                candidate_count=counts.get(job.id, 0),
                issue_count=len(job.issues),
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
            for job in jobs
        ]

    def detail(self, job):
        candidates = self.session.scalars(
            select(DiscoverCandidate)
            .where(DiscoverCandidate.discover_id == job.id)
            .order_by(DiscoverCandidate.created_at, DiscoverCandidate.id)
        ).all()
        keys = [(c.platform, c.platform_account_id) for c in candidates]
        profiles = (
            self.session.scalars(
                select(CreatorProfile).where(
                    tuple_(
                        CreatorProfile.platform, CreatorProfile.platform_account_id
                    ).in_(keys)
                )
            ).all()
            if keys
            else []
        )
        library = {(p.platform, p.platform_account_id): p.id for p in profiles}
        return DiscoverDetail(
            id=job.id,
            game_id=job.game_id,
            game_name=job.game_name,
            status=job.status,
            stage=job.stage,
            conditions=job.conditions,
            issues=job.issues,
            created_at=job.created_at,
            updated_at=job.updated_at,
            candidates=[
                DiscoverCandidateResponse(
                    id=c.id,
                    **c.metadata_snapshot,
                    in_library=(c.platform, c.platform_account_id) in library,
                    profile_id=library.get((c.platform, c.platform_account_id)),
                )
                for c in candidates
            ],
        )
