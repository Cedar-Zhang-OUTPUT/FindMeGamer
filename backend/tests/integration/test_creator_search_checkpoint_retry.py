from contextlib import contextmanager
from datetime import timedelta
from copy import deepcopy

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import sessionmaker

from app.core.idempotency import utc_now
from app.db.models.enums import JobStatus, JobMode, TargetType, AnalysisStage
from app.db.models.jobs import AnalysisJob, CreatorAnalysisNode
from app.workers.creator_search_enrichment import enrich_profile
from app.workers.creator_search_tasks import SearchFailure
from tests.integration.test_creator_search_enrichment import seed_unit
from tests.integration.test_discovery_evaluation import sessions_for
from tests.unit.analysis.test_creator_failed_recovery import saved_nodes


def failed_unit(client, session, monkeypatch):
    unit, profile = seed_unit(client, session, monkeypatch)
    source, nodes = saved_nodes()
    unit.platform = profile.platform = "youtube"
    unit.account_id = profile.platform_account_id = profile.youtube_channel_id = (
        source.channel_id
    )
    profile.canonical_url = source.canonical_url
    profile.analysis = {}
    profile.last_analyzed_at = None
    now = utc_now()
    job = AnalysisJob(
        target_type=TargetType.CREATOR,
        canonical_target_id=source.channel_id,
        canonical_url=source.canonical_url,
        mode=JobMode.CREATE,
        status=JobStatus.FAILED,
        stage=AnalysisStage.ANALYZING,
        completed_units=2,
        total_units=5,
        started_at=now - timedelta(minutes=10),
        completed_at=now - timedelta(minutes=1),
        created_at=now - timedelta(minutes=11),
        retryable=True,
        error_code="deepseek_model_output_invalid",
        error_message="Analysis is temporarily unavailable. Please retry.",
        correlation_id=f"creator-search:{unit.search_id}",
    )
    session.add(job)
    session.flush()
    unit.analysis_job_id = job.id
    unit.owns_analysis_job = True
    unit.profile_status = "failed"
    for key, node in nodes.items():
        session.add(
            CreatorAnalysisNode(
                job_id=job.id,
                node_key=key,
                output_payload=node.output_payload,
                created_at=now - timedelta(minutes=10),
            )
        )
    session.commit()
    return unit, profile, job


class MustNotExecute:
    def execute(self, job_id):
        raise AssertionError("Unexpected pipeline execution")


@pytest.mark.parametrize("missing", ["source:v1", "contact:v2", "visual:v1"])
def test_no_checkpoint_refetch_fallback(auth_client, session, monkeypatch, missing):
    unit, profile, job = failed_unit(auth_client, session, monkeypatch)
    session.delete(session.get(CreatorAnalysisNode, (job.id, missing)))
    session.commit()
    with pytest.raises(SearchFailure, match="search_resume_checkpoint_missing"):
        enrich_profile(
            unit.id, session_factory=sessions_for(session), executor=MustNotExecute()
        )
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1


def test_failed_unit_without_a_job_requires_explicit_new_analysis(
    auth_client, session, monkeypatch
):
    unit, profile = seed_unit(auth_client, session, monkeypatch)
    unit.profile_status = "running"  # orchestration has begun this retry wave
    unit.profile_error_code = "search_profile_failed"
    session.commit()
    with pytest.raises(SearchFailure, match="search_resume_checkpoint_missing"):
        enrich_profile(
            unit.id, session_factory=sessions_for(session), executor=MustNotExecute()
        )
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 0


@pytest.mark.parametrize("scenario", ["reducers", "missing_batch", "brief_fails_once"])
def test_recovery_runs_only_missing_nodes_and_keeps_original_failure(
    auth_client, session, monkeypatch, scenario
):
    from app.analysis.creator_map_reduce_pipeline import CreatorMapReducePipeline
    from app.analysis.creator_checkpoints import CreatorAnalysisCheckpointStore
    from app.analysis.service import CreatorAnalysisService
    from app.workers.analysis_tasks import AnalysisJobExecutor
    from tests.unit.analysis.test_creator_map_reduce_pipeline import _output_for
    from app.schemas.ai_creator_map_reduce import CreatorVideoBatchDigest

    unit, profile, original = failed_unit(auth_client, session, monkeypatch)
    original_id, unit_id = original.id, unit.id
    if scenario == "missing_batch":
        session.delete(session.get(CreatorAnalysisNode, (original_id, "batch:v1:00")))
        session.commit()
    saved = {
        n.node_key: deepcopy(n.output_payload)
        for n in session.scalars(
            select(CreatorAnalysisNode).where(CreatorAnalysisNode.job_id == original_id)
        )
    }
    factory = sessionmaker(
        bind=session.get_bind(),
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    @contextmanager
    def sessions():
        with factory() as current:
            yield current
            current.commit()

    class NoAcquisition:
        def __getattr__(self, name):
            raise AssertionError(f"Unexpected acquisition: {name}")

    calls = []

    class AI:
        def complete_structured(self, model, messages, schema, **kwargs):
            if scenario != "missing_batch":
                assert schema is not CreatorVideoBatchDigest
            calls.append(schema.__name__)
            if (
                scenario == "brief_fails_once"
                and schema.__name__ == "CreatorBriefSynthesis"
                and calls.count("CreatorBriefSynthesis") == 1
            ):
                from app.integrations.errors import InvalidModelOutput

                raise InvalidModelOutput("deepseek_model_output_invalid")
            return _output_for(schema)

    @contextmanager
    def pipeline_factory(target):
        yield CreatorMapReducePipeline(
            service=CreatorAnalysisService(session_factory=factory),
            youtube=NoAcquisition(),
            artifacts=NoAcquisition(),
            public_pages=NoAcquisition(),
            deepseek=AI(),
            checkpoints=CreatorAnalysisCheckpointStore(session_factory=factory),
        )

    executor = AnalysisJobExecutor(
        session_factory=sessions, pipeline_factory=pipeline_factory
    )
    if scenario == "brief_fails_once":
        with pytest.raises(SearchFailure, match="search_profile_failed"):
            enrich_profile(unit_id, session_factory=sessions, executor=executor)
    assert (
        enrich_profile(unit_id, session_factory=sessions, executor=executor) == "ready"
    )
    expected_calls = 5 if scenario == "reducers" else 6
    assert len(calls) == expected_calls
    assert (
        enrich_profile(unit_id, session_factory=sessions, executor=executor) == "ready"
    )
    assert len(calls) == expected_calls
    session.expire_all()
    assert session.get(AnalysisJob, original_id).status is JobStatus.FAILED
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == (
        3 if scenario == "brief_fails_once" else 2
    )
    session.refresh(profile)
    recovery = profile.model_metadata["checkpoint_recovery"]
    if scenario != "brief_fails_once":
        assert recovery["source_job_id"] == str(original_id)
        assert set(recovery["reused_node_keys"]) == set(saved)
    else:
        assert recovery["source_job_id"] != str(original_id)
        assert set(saved) <= set(recovery["reused_node_keys"])
    assert "new calls only" in recovery["model_fields_scope"]
    for key, payload in saved.items():
        assert (
            session.get(CreatorAnalysisNode, (original_id, key)).output_payload
            == payload
        )
        assert (
            session.get(CreatorAnalysisNode, (unit.analysis_job_id, key)).output_payload
            == payload
        )


def test_active_job_not_replayed(auth_client, session, monkeypatch):
    unit, profile, job = failed_unit(auth_client, session, monkeypatch)
    job.status = JobStatus.RUNNING
    job.completed_at = job.error_code = job.error_message = None
    job.retryable = False
    session.commit()
    with pytest.raises(SearchFailure, match="search_profile_busy"):
        enrich_profile(
            unit.id, session_factory=sessions_for(session), executor=MustNotExecute()
        )


def test_successful_profile_never_overwritten_by_failed_recovery(
    auth_client, session, monkeypatch
):
    unit, profile, job = failed_unit(auth_client, session, monkeypatch)
    profile.analysis = {"summary": "Keep existing success"}
    profile.last_analyzed_at = utc_now()
    session.commit()
    assert (
        enrich_profile(
            unit.id, session_factory=sessions_for(session), executor=MustNotExecute()
        )
        == "ready"
    )
    assert profile.analysis == {"summary": "Keep existing success"}
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1


@pytest.mark.parametrize(
    "change,code",
    [
        ("expired", "search_resume_source_expired"),
        ("identity", "search_identity_changed"),
        ("unowned", "search_resume_unavailable"),
        ("other_active", "search_profile_busy"),
    ],
)
def test_recovery_rejects_stale_identity_unowned_and_overlapping_jobs(
    auth_client, session, monkeypatch, change, code
):
    unit, profile, job = failed_unit(auth_client, session, monkeypatch)
    if change == "expired":
        session.get(CreatorAnalysisNode, (job.id, "source:v1")).created_at = (
            utc_now() - timedelta(days=31)
        )
    elif change == "identity":
        profile.identity_revision += 1
    elif change == "unowned":
        unit.owns_analysis_job = False
    else:
        session.add(
            AnalysisJob(
                target_type=job.target_type,
                canonical_target_id=job.canonical_target_id,
                canonical_url=job.canonical_url,
                mode=JobMode.CREATE,
                status=JobStatus.QUEUED,
            )
        )
    session.commit()
    with pytest.raises(SearchFailure, match=code):
        enrich_profile(
            unit.id, session_factory=sessions_for(session), executor=MustNotExecute()
        )
    assert session.scalar(select(func.count()).select_from(AnalysisJob)) == (
        2 if change == "other_active" else 1
    )
