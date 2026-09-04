"""Short transactional storage for successful Creator analysis nodes."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.enums import JobStatus, TargetType
from app.db.models.jobs import AnalysisJob, CreatorAnalysisNode
from app.integrations.errors import PermanentIntegrationError


T = TypeVar("T", bound=BaseModel)
SessionFactory = Callable[[], AbstractContextManager[Session]]
_NODE_KEY = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")


class CreatorAnalysisCheckpointStore:
    """Persist only validated successes; an existing valid result always wins."""

    def __init__(self, *, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def load(self, job_id: UUID, node_key: str, schema: type[T]) -> T | None:
        self._validate_identity(job_id, node_key, schema)
        with self._session_factory() as session:
            job = session.get(AnalysisJob, job_id)
            self._require_creator_parent(job, allow_succeeded=True)
            node = session.get(CreatorAnalysisNode, (job_id, node_key))
            if node is None:
                return None
            return self._validate_payload(node.output_payload, schema)

    def save_success(self, job_id: UUID, node_key: str, output: T) -> T:
        schema = type(output)
        self._validate_identity(job_id, node_key, schema)
        if not isinstance(output, BaseModel):
            raise TypeError("checkpoint output must be a validated Pydantic model")
        payload = output.model_dump(mode="json")
        with self._session_factory() as session, session.begin():
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            self._require_creator_parent(job, allow_succeeded=False)
            existing = session.get(CreatorAnalysisNode, (job_id, node_key))
            if existing is not None:
                return self._validate_payload(existing.output_payload, schema)
            node = CreatorAnalysisNode(
                job_id=job_id,
                node_key=node_key,
                output_payload=payload,
            )
            session.add(node)
            session.flush()
            return output

    @staticmethod
    def _validate_identity(job_id: UUID, node_key: str, schema: type[T]) -> None:
        if not isinstance(job_id, UUID) or job_id.int == 0:
            raise TypeError("checkpoint job id must be a nonzero UUID")
        if not isinstance(node_key, str) or not _NODE_KEY.fullmatch(node_key):
            raise ValueError("invalid Creator analysis node key")
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise TypeError("checkpoint schema must be a Pydantic model")

    @staticmethod
    def _require_creator_parent(
        job: AnalysisJob | None, *, allow_succeeded: bool
    ) -> None:
        allowed = {JobStatus.RUNNING}
        if allow_succeeded:
            allowed.add(JobStatus.SUCCEEDED)
        if (
            job is None
            or job.target_type is not TargetType.CREATOR
            or job.status not in allowed
        ):
            raise PermanentIntegrationError("analysis_job_state_invalid")

    @staticmethod
    def _validate_payload(payload: object, schema: type[T]) -> T:
        try:
            return schema.model_validate(payload)
        except (ValidationError, ValueError, TypeError):
            raise PermanentIntegrationError("analysis_job_state_invalid") from None
