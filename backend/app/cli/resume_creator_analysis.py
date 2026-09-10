"""Maintenance-only Creator recovery; preserve history and reuse validated nodes.

Use --dry-run to inspect the exact node plan without writes or dispatch. A normal
run creates a fresh job transactionally, then uses the normal worker/publication
path. It never reopens terminal jobs or writes Profiles directly.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
import json
import sys
from typing import Literal, Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.creator_map_reduce_pipeline import (
    BRIEF_NODE_KEY,
    REDUCTION_NODE_KEYS,
    SOURCE_NODE_KEY,
    VISUAL_NODE_KEY,
    CreatorSourceCheckpoint,
)
from app.analysis.prompts.creator_map_reduce import creator_video_batch_count
from app.analysis.creator_recovery import node_schemas as _node_schemas
from app.analysis.targets import canonicalize_target
from app.db.models.enums import JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob, CreatorAnalysisNode
from app.db.models.profiles import CreatorProfile
from app.repositories.jobs import JobsRepository, require_valid_succeeded_job_result
from app.schemas.ai_creator import CreatorVisualAnalysis


Mode = Literal["brief", "visual", "content-format"]
SessionFactory = Callable[[], AbstractContextManager[Session]]


class JobDispatcher(Protocol):
    def dispatch(self, job_id: UUID) -> None: ...


class ResumeCreatorError(RuntimeError):
    """Safe operator-facing failure without database/model payloads."""


@dataclass(frozen=True)
class ResumeResult:
    source_job_id: UUID
    mode: Mode
    job_id: UUID | None
    copied_nodes: tuple[str, ...]
    recomputed_nodes: tuple[str, ...]
    created: bool = False
    dispatched: bool = False
    dry_run: bool = False


class CreatorAnalysisResumer:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dispatcher: JobDispatcher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._clock = clock

    def run(
        self, source_job_id: UUID, *, mode: Mode, dry_run: bool = False
    ) -> ResumeResult:
        if not isinstance(source_job_id, UUID) or source_job_id.int == 0:
            raise ResumeCreatorError("A nonzero source Job UUID is required.")
        if mode not in {"brief", "visual", "content-format"}:
            raise ResumeCreatorError(
                "Recovery mode must be brief, visual, or content-format."
            )
        try:
            result = self._prepare(source_job_id, mode=mode, dry_run=dry_run)
        except ResumeCreatorError:
            raise
        except Exception:
            raise ResumeCreatorError(
                "Creator recovery could not be prepared safely."
            ) from None
        if not result.created:
            return result
        assert result.job_id is not None
        try:
            self._dispatcher.dispatch(result.job_id)
        except Exception:
            self._mark_queue_failure(result.job_id)
            raise ResumeCreatorError(
                f"Recovery Job {result.job_id} could not be queued. Retry this command."
            ) from None
        return replace(result, dispatched=True)

    def _prepare(
        self, source_job_id: UUID, *, mode: Mode, dry_run: bool
    ) -> ResumeResult:
        now = self._clock()
        with self._session_factory() as session, session.begin():
            repository = JobsRepository(session)
            source = repository.get_job_for_update(source_job_id)
            if source is None or source.target_type is not TargetType.CREATOR:
                raise ResumeCreatorError("The source must be an existing Creator Job.")
            expected_status = (
                JobStatus.SUCCEEDED if mode == "visual" else JobStatus.FAILED
            )
            if source.status is not expected_status:
                raise ResumeCreatorError(
                    "The source Job is not eligible for this recovery mode."
                )
            if mode != "visual" and not source.retryable:
                raise ResumeCreatorError("The failed source Job is not retryable.")
            target = canonicalize_target(TargetType.CREATOR, source.canonical_url)
            if (
                target.requires_resolution
                or target.canonical_id != source.canonical_target_id
            ):
                raise ResumeCreatorError("The source Creator identity does not match.")
            if not now - timedelta(days=30) <= source.created_at <= now:
                raise ResumeCreatorError(
                    "The source Job is older than the 30-day recovery window."
                )
            profile = session.scalar(
                select(CreatorProfile)
                .where(CreatorProfile.youtube_channel_id == source.canonical_target_id)
                .with_for_update()
            )
            if mode == "visual":
                require_valid_succeeded_job_result(
                    session, source, succeeded_profile=profile
                )
                if (
                    profile is None
                    or profile.source_status.get("visual_analysis") != "unavailable"
                    or profile.last_analyzed_at != source.completed_at
                ):
                    raise ResumeCreatorError(
                        "Visual recovery requires the current Profile's unavailable visual result."
                    )
            elif (
                profile is not None
                and profile.last_analyzed_at is not None
                and profile.last_analyzed_at > source.created_at
            ):
                raise ResumeCreatorError(
                    "A newer Creator Profile exists; use normal reanalysis instead."
                )

            nodes = {
                node.node_key: node
                for node in session.scalars(
                    select(CreatorAnalysisNode).where(
                        CreatorAnalysisNode.job_id == source.id
                    )
                )
            }
            source_node = nodes.get(SOURCE_NODE_KEY)
            if (
                source_node is None
                or not now - timedelta(days=30) <= source_node.created_at <= now
            ):
                raise ResumeCreatorError(
                    "A current source checkpoint within 30 days is required."
                )
            try:
                checkpoint = CreatorSourceCheckpoint.model_validate(
                    source_node.output_payload
                )
                source_data = checkpoint.to_source()
                if (
                    source_data.channel_id != source.canonical_target_id
                    or source_data.canonical_url != target.canonical_url
                ):
                    raise ResumeCreatorError(
                        "The source checkpoint's Creator identity does not match."
                    )
                schemas = _node_schemas(creator_video_batch_count(source_data))
                if set(nodes) - set(schemas):
                    raise ResumeCreatorError(
                        "Unknown checkpoint versions require normal reanalysis."
                    )
                optional_nodes = {BRIEF_NODE_KEY}
                if mode == "content-format":
                    optional_nodes.add(REDUCTION_NODE_KEYS["content_format"])
                if set(schemas) - optional_nodes - set(nodes):
                    raise ResumeCreatorError(
                        "Required successful checkpoints are missing."
                    )
                for key, node in nodes.items():
                    schemas[key].model_validate(node.output_payload)
                if (
                    mode == "visual"
                    and CreatorVisualAnalysis.model_validate(
                        nodes[VISUAL_NODE_KEY].output_payload
                    ).status
                    != "unavailable"
                ):
                    raise ResumeCreatorError(
                        "The source visual checkpoint is not unavailable."
                    )
            except (ValidationError, ValueError, TypeError):
                raise ResumeCreatorError(
                    "A source checkpoint failed schema validation."
                ) from None

            excluded = {BRIEF_NODE_KEY}
            if mode == "visual":
                excluded.update({VISUAL_NODE_KEY, REDUCTION_NODE_KEYS["presentation"]})
            elif mode == "content-format":
                excluded.add(REDUCTION_NODE_KEYS["content_format"])
            copied = tuple(sorted(set(nodes) - excluded))
            recomputed = tuple(sorted(excluded))
            active = repository.active_job(target)
            if active is not None or dry_run:
                return ResumeResult(
                    source.id,
                    mode,
                    active.id if active else None,
                    copied,
                    recomputed,
                    dry_run=dry_run,
                )
            created = repository.create_or_reuse_job(
                target,
                mode=JobMode.REANALYZE,
                correlation_id=f"creator-resume:{mode}:{source.id}",
            )
            assert created.created and created.job is not None
            for key in copied:
                node = nodes[key]
                session.add(
                    CreatorAnalysisNode(
                        job_id=created.job.id,
                        node_key=key,
                        output_payload=deepcopy(node.output_payload),
                        created_at=node.created_at,
                        updated_at=node.updated_at,
                    )
                )
            session.flush()
            return ResumeResult(
                source.id, mode, created.job.id, copied, recomputed, created=True
            )

    def _mark_queue_failure(self, job_id: UUID) -> None:
        from app.core.analysis_job_contract import QUEUE_FAILURE_MESSAGE
        from app.workers.analysis_tasks import (
            TerminalFailure,
            write_queued_publication_failure,
        )

        try:
            write_queued_publication_failure(
                job_id,
                TerminalFailure(
                    "analysis_queue_unavailable", QUEUE_FAILURE_MESSAGE, True
                ),
                session_factory=self._session_factory,
                clock=self._clock,
            )
        except Exception:
            raise ResumeCreatorError(
                f"Recovery Job {job_id} dispatch is uncertain; inspect its status before retrying."
            ) from None


def build_production_service() -> CreatorAnalysisResumer:
    from app.api.routes.jobs import CeleryJobDispatcher
    from app.core.database import session_scope

    return CreatorAnalysisResumer(
        session_factory=session_scope, dispatcher=CeleryJobDispatcher()
    )


def main(argv=None, *, service_factory=build_production_service) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_job_id", type=UUID)
    parser.add_argument(
        "--mode", choices=("brief", "visual", "content-format"), required=True
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = service_factory().run(
            args.source_job_id, mode=args.mode, dry_run=args.dry_run
        )
    except ResumeCreatorError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("Error: Creator recovery could not be started safely.", file=sys.stderr)
        return 2
    print(json.dumps(asdict(result), default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
