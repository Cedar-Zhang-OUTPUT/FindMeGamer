from sqlalchemy import select

from app.db.models.discover_batch import DiscoverAnalysisBatch, DiscoverAnalysisItem
from app.schemas.discover_batch import DiscoverBatchDetail, DiscoverBatchItemDetail


class DiscoverBatchRepository:
    def __init__(self, session):
        self.session = session

    def get(self, identifier, *, lock=False):
        query = select(DiscoverAnalysisBatch).where(
            DiscoverAnalysisBatch.id == identifier
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def items(self, identifier):
        return self.session.scalars(
            select(DiscoverAnalysisItem)
            .where(DiscoverAnalysisItem.batch_id == identifier)
            .order_by(DiscoverAnalysisItem.candidate_id)
        ).all()

    def detail(self, batch):
        return DiscoverBatchDetail(
            id=batch.id,
            discover_id=batch.discover_id,
            mode=batch.mode,
            status=batch.status,
            match_task_id=batch.match_task_id,
            error=batch.error,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
            items=[
                DiscoverBatchItemDetail(
                    candidate_id=i.candidate_id,
                    profile_id=i.profile_id,
                    analysis_job_id=i.analysis_job_id,
                    status=i.status,
                    error=i.error,
                    reused=i.reused,
                )
                for i in self.items(batch.id)
            ],
        )
