from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select

from app.analysis.creator_map_reduce_pipeline import (
    BRIEF_NODE_KEY,
    CONTACT_NODE_KEY,
    REDUCTION_NODE_KEYS,
    SOURCE_NODE_KEY,
    VISUAL_NODE_KEY,
    CreatorContactCheckpoint,
    CreatorSourceCheckpoint,
)
from app.cli.resume_creator_analysis import CreatorAnalysisResumer, ResumeCreatorError
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob, CreatorAnalysisNode
from app.db.models.profiles import CreatorProfile
from app.schemas.ai_creator import CreatorContactEvidence
from app.schemas.ai_creator_map_reduce import (
    CreatorBriefSynthesis,
    CreatorCommercialSafetyReduction,
    CreatorContentFormatReduction,
    CreatorPerformanceAudienceReduction,
    CreatorPresentationReduction,
    CreatorVideoBatchDigest,
)
from tests.integration.test_creator_analysis_commit import committed_factory
from tests.unit.analysis.test_creator_map_reduce_pipeline import _output_for
from tests.unit.analysis.test_creator_pipeline import _source


NOW = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def align_created_job_clock():
    """Keep DB-created retry jobs before this module's injected service clock."""
    def set_created_at(mapper, connection, job):
        if job.created_at is None:
            job.created_at = NOW - timedelta(minutes=1)

    event.listen(AnalysisJob, "before_insert", set_created_at)
    try:
        yield
    finally:
        event.remove(AnalysisJob, "before_insert", set_created_at)


def seed(factory, *, succeeded=False, missing_content_format=False):
    source = _source()
    videos = tuple(
        source.videos[0].model_copy(update={"id": f"video-{i}"}) for i in range(50)
    )
    source = source.model_copy(update={"videos": videos})
    from app.analysis.creator_pipeline import unavailable_visual_analysis

    visual = unavailable_visual_analysis("Thumbnail fetch failed.")
    outputs = {
        SOURCE_NODE_KEY: CreatorSourceCheckpoint.from_source(source),
        VISUAL_NODE_KEY: visual,
        CONTACT_NODE_KEY: CreatorContactCheckpoint(
            evidence=CreatorContactEvidence(candidates=()), status="unavailable"
        ),
        **{f"batch:v1:{i:02d}": _output_for(CreatorVideoBatchDigest) for i in range(5)},
    }
    for name, schema in (
        ("content_format", CreatorContentFormatReduction),
        ("presentation", CreatorPresentationReduction),
        ("performance_audience", CreatorPerformanceAudienceReduction),
        ("commercial_safety", CreatorCommercialSafetyReduction),
    ):
        outputs[REDUCTION_NODE_KEYS[name]] = _output_for(schema)
    if succeeded:
        outputs[BRIEF_NODE_KEY] = _output_for(CreatorBriefSynthesis)
    if missing_content_format:
        del outputs[REDUCTION_NODE_KEYS["content_format"]]
    job_id, profile_id = uuid4(), uuid4()
    created = NOW - timedelta(hours=1)
    with factory.begin() as session:
        if succeeded:
            session.add(
                CreatorProfile(
                    id=profile_id,
                    youtube_channel_id=source.channel_id,
                    canonical_url=source.canonical_url,
                    sort_name=source.title,
                    favorite=True,
                    manual_notes="Keep manual notes",
                    brief={"previous": "must survive"},
                    source_status={"visual_analysis": "unavailable"},
                    last_analyzed_at=created + timedelta(minutes=2),
                )
            )
            session.flush()
        session.add(
            AnalysisJob(
                id=job_id,
                target_type=TargetType.CREATOR,
                canonical_target_id=source.channel_id,
                canonical_url=source.canonical_url,
                mode=JobMode.REANALYZE,
                status=JobStatus.SUCCEEDED if succeeded else JobStatus.FAILED,
                stage=(
                    AnalysisStage.FINALIZING if succeeded else AnalysisStage.ANALYZING
                ),
                completed_units=5 if succeeded else 2,
                total_units=5,
                created_at=created,
                started_at=created,
                completed_at=created + timedelta(minutes=2),
                retryable=not succeeded,
                error_code=(
                    None
                    if succeeded
                    else (
                        "deepseek_model_evidence_invalid"
                        if missing_content_format
                        else "deepseek_model_output_invalid"
                    )
                ),
                error_message=(
                    None
                    if succeeded
                    else "Analysis is temporarily unavailable. Please retry."
                ),
                profile_id=profile_id if succeeded else None,
                result_payload={"profile_id": str(profile_id)} if succeeded else None,
            )
        )
        session.flush()
        for key, output in outputs.items():
            session.add(
                CreatorAnalysisNode(
                    job_id=job_id,
                    node_key=key,
                    output_payload=output.model_dump(mode="json"),
                    created_at=created,
                    updated_at=created,
                )
            )
    return job_id, profile_id, outputs


class Dispatcher:
    def __init__(self, factory):
        self.factory = factory
        self.calls = []

    def dispatch(self, job_id):
        # A separate connection must see every node: dispatch must follow commit.
        with self.factory() as session:
            assert session.get(AnalysisJob, job_id).status is JobStatus.QUEUED
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(CreatorAnalysisNode)
                    .where(CreatorAnalysisNode.job_id == job_id)
                )
                > 0
            )
        self.calls.append(job_id)


def resumer(factory, dispatcher=None):
    return CreatorAnalysisResumer(
        session_factory=factory,
        dispatcher=dispatcher or Dispatcher(factory),
        clock=lambda: NOW,
    )


@pytest.mark.parametrize(
    ("mode", "expected"), [("brief", 12), ("visual", 10), ("content-format", 11)]
)
def test_resume_clones_only_required_nodes_after_commit_and_preserves_history(
    committed_factory, mode, expected
):
    source_id, profile_id, outputs = seed(
        committed_factory,
        succeeded=mode == "visual",
        missing_content_format=mode == "content-format",
    )
    dispatcher = Dispatcher(committed_factory)
    result = resumer(committed_factory, dispatcher).run(source_id, mode=mode)
    assert result.created and result.dispatched
    assert result.job_id != source_id
    assert len(result.copied_nodes) == expected
    with committed_factory() as session:
        original = session.get(AnalysisJob, source_id)
        assert original.status is (
            JobStatus.SUCCEEDED if mode == "visual" else JobStatus.FAILED
        )
        new = session.get(AnalysisJob, result.job_id)
        assert new.status is JobStatus.QUEUED
        assert new.canonical_target_id == original.canonical_target_id
        nodes = session.scalars(
            select(CreatorAnalysisNode).where(
                CreatorAnalysisNode.job_id == result.job_id
            )
        ).all()
        assert len(nodes) == expected
        for node in nodes:
            old = session.get(CreatorAnalysisNode, (source_id, node.node_key))
            assert (
                node.output_payload
                == old.output_payload
                == outputs[node.node_key].model_dump(mode="json")
            )
            assert node.created_at == old.created_at
        assert BRIEF_NODE_KEY not in result.copied_nodes
        if mode == "content-format":
            assert original.retryable is True
            assert original.error_code == "deepseek_model_evidence_invalid"
            assert original.completed_at == NOW - timedelta(minutes=58)
            assert set(result.recomputed_nodes) == {
                REDUCTION_NODE_KEYS["content_format"],
                BRIEF_NODE_KEY,
            }
            assert REDUCTION_NODE_KEYS["content_format"] not in result.copied_nodes
        if mode == "visual":
            assert VISUAL_NODE_KEY not in result.copied_nodes
            assert REDUCTION_NODE_KEYS["presentation"] not in result.copied_nodes
            profile = session.get(CreatorProfile, profile_id)
            assert profile.brief == {"previous": "must survive"}
            assert profile.favorite and profile.manual_notes == "Keep manual notes"
    assert dispatcher.calls == [result.job_id]


@pytest.mark.parametrize("mode", ["brief", "content-format"])
def test_repeated_resume_reuses_active_job_without_duplicate_dispatch(
    committed_factory,
    mode,
):
    source_id, _, _ = seed(
        committed_factory, missing_content_format=mode == "content-format"
    )
    dispatcher = Dispatcher(committed_factory)
    service = resumer(committed_factory, dispatcher)
    first = service.run(source_id, mode=mode)
    second = service.run(source_id, mode=mode)
    assert first.job_id == second.job_id
    assert not second.created and not second.dispatched
    assert dispatcher.calls == [first.job_id]


@pytest.mark.parametrize(("mode", "expected"), [("brief", 12), ("content-format", 11)])
def test_dry_run_validates_but_does_not_write_or_dispatch(
    committed_factory, mode, expected
):
    source_id, _, _ = seed(
        committed_factory, missing_content_format=mode == "content-format"
    )
    dispatcher = Dispatcher(committed_factory)
    result = resumer(committed_factory, dispatcher).run(
        source_id, mode=mode, dry_run=True
    )
    assert result.dry_run and result.job_id is None
    assert len(result.copied_nodes) == expected
    with committed_factory() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1
    assert dispatcher.calls == []


@pytest.mark.parametrize(
    "change", ["expired", "identity", "unknown", "invalid", "missing", "running"]
)
@pytest.mark.parametrize("mode", ["brief", "content-format"])
def test_unsupported_source_is_rejected_without_partial_job(
    committed_factory, change, mode
):
    source_id, _, _ = seed(
        committed_factory, missing_content_format=mode == "content-format"
    )
    with committed_factory.begin() as session:
        source_node = session.get(CreatorAnalysisNode, (source_id, SOURCE_NODE_KEY))
        if change == "expired":
            source_node.created_at = NOW - timedelta(days=31)
        elif change == "identity":
            payload = deepcopy(source_node.output_payload)
            payload["channel_id"] = "UCother123"
            source_node.output_payload = payload
        elif change == "unknown":
            session.add(
                CreatorAnalysisNode(
                    job_id=source_id, node_key="unknown:v1", output_payload={}
                )
            )
        elif change == "invalid":
            node = session.get(CreatorAnalysisNode, (source_id, "batch:v1:00"))
            node.output_payload = {"bad": "schema-canary"}
        elif change == "missing":
            session.delete(
                session.get(CreatorAnalysisNode, (source_id, CONTACT_NODE_KEY))
            )
        else:
            job = session.get(AnalysisJob, source_id)
            job.status = JobStatus.RUNNING
            job.completed_at = job.error_code = job.error_message = None
            job.retryable = False
    with pytest.raises(ResumeCreatorError):
        resumer(committed_factory).run(source_id, mode=mode)
    with committed_factory() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1


def test_node_copy_failure_rolls_back_new_job_and_all_copies(committed_factory):
    source_id, _, _ = seed(committed_factory, succeeded=True)

    def fail_copy(_mapper, _connection, target):
        if target.job_id != source_id:
            raise RuntimeError("private-database-canary")

    event.listen(CreatorAnalysisNode, "before_insert", fail_copy)
    try:
        with pytest.raises(ResumeCreatorError, match="could not be prepared"):
            resumer(committed_factory).run(source_id, mode="visual")
    finally:
        event.remove(CreatorAnalysisNode, "before_insert", fail_copy)
    with committed_factory() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1
        assert (
            session.scalar(select(func.count()).select_from(CreatorAnalysisNode)) == 13
        )


def test_queue_failure_preserves_source_and_allows_normal_resume_again(
    committed_factory,
):
    source_id, _, _ = seed(committed_factory)

    class FailedDispatcher:
        def dispatch(self, job_id):
            raise OSError("secret-dispatch-canary")

    with pytest.raises(ResumeCreatorError, match="could not be queued"):
        resumer(committed_factory, FailedDispatcher()).run(source_id, mode="brief")
    with committed_factory() as session:
        jobs = session.scalars(select(AnalysisJob)).all()
        assert len(jobs) == 2 and all(job.status is JobStatus.FAILED for job in jobs)
    assert resumer(committed_factory).run(source_id, mode="brief").dispatched


@pytest.mark.parametrize("mode", ["brief", "visual", "content-format"])
def test_resumed_job_uses_normal_pipeline_and_only_recomputes_planned_nodes(
    committed_factory, mode
):
    import re
    from app.analysis.creator_checkpoints import CreatorAnalysisCheckpointStore
    from app.analysis.creator_map_reduce_pipeline import CreatorMapReducePipeline
    from app.analysis.service import CreatorAnalysisService
    from app.schemas.ai_creator import CreatorVisualAnalysis
    from tests.unit.analysis.test_prompts import available_creator_visual

    source_id, previous_profile_id, _ = seed(
        committed_factory,
        succeeded=mode == "visual",
        missing_content_format=mode == "content-format",
    )
    result = resumer(committed_factory).run(source_id, mode=mode)

    class UnusedGateway:
        def __getattr__(self, name):
            raise AssertionError(f"Cached input must not call {name}")

    class AI:
        calls = []

        def complete_structured(self, model, messages, schema, **kwargs):
            self.calls.append(schema)
            assert schema in {
                CreatorBriefSynthesis,
                CreatorPresentationReduction,
                CreatorContentFormatReduction,
            }
            return _output_for(schema)

        def complete_vision(self, model, prompt, image_urls, schema, **kwargs):
            self.calls.append(schema)
            payload = available_creator_visual().model_dump(mode="json")
            payload["visual_style"]["evidence"][0]["reference"] = re.findall(
                r"video:video-\d+:thumbnail:0", prompt
            )[0]
            return CreatorVisualAnalysis.model_validate(payload)

    ai = AI()
    pipeline = CreatorMapReducePipeline(
        service=CreatorAnalysisService(
            session_factory=committed_factory, clock=lambda: NOW
        ),
        youtube=UnusedGateway(),
        artifacts=UnusedGateway(),
        public_pages=UnusedGateway(),
        deepseek=ai,
        checkpoints=CreatorAnalysisCheckpointStore(session_factory=committed_factory),
    )
    profile_id = pipeline.run(result.job_id)
    expected = {
        "brief": [CreatorBriefSynthesis],
        "visual": [
            CreatorVisualAnalysis,
            CreatorPresentationReduction,
            CreatorBriefSynthesis,
        ],
        "content-format": [CreatorContentFormatReduction, CreatorBriefSynthesis],
    }[mode]
    assert ai.calls == expected
    with committed_factory() as session:
        assert session.get(AnalysisJob, result.job_id).status is JobStatus.SUCCEEDED
        profile = session.get(CreatorProfile, profile_id)
        if mode == "visual":
            assert profile_id == previous_profile_id
            assert profile.source_status["visual_analysis"] == "available"
            assert profile.model_metadata["vision_available"] is True
            assert profile.favorite and profile.manual_notes == "Keep manual notes"
        for key in result.copied_nodes:
            old = session.get(CreatorAnalysisNode, (source_id, key))
            new = session.get(CreatorAnalysisNode, (result.job_id, key))
            assert old.output_payload == new.output_payload


@pytest.mark.parametrize("change", ["already_available", "newer_profile"])
def test_visual_recovery_refuses_stale_or_already_fixed_profile(
    committed_factory, change
):
    source_id, profile_id, _ = seed(committed_factory, succeeded=True)
    with committed_factory.begin() as session:
        profile = session.get(CreatorProfile, profile_id)
        if change == "already_available":
            profile.source_status = {"visual_analysis": "available"}
        else:
            profile.last_analyzed_at = NOW
    with pytest.raises(ResumeCreatorError, match="current Profile"):
        resumer(committed_factory).run(source_id, mode="visual")


@pytest.mark.parametrize(("mode", "expected"), [("brief", 12), ("content-format", 11)])
def test_cli_dry_run_reports_plan_without_payloads(
    committed_factory, capsys, mode, expected
):
    import json
    from app.cli.resume_creator_analysis import main

    source_id, _, _ = seed(
        committed_factory, missing_content_format=mode == "content-format"
    )
    assert (
        main(
            [str(source_id), "--mode", mode, "--dry-run"],
            service_factory=lambda: resumer(committed_factory),
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["source_job_id"] == str(source_id)
    assert report["dry_run"] is True and len(report["copied_nodes"]) == expected
    assert "output_payload" not in report


def test_content_format_recovery_excludes_existing_content_and_brief_nodes(
    committed_factory,
):
    source_id, _, _ = seed(committed_factory)
    with committed_factory.begin() as session:
        session.add(
            CreatorAnalysisNode(
                job_id=source_id,
                node_key=BRIEF_NODE_KEY,
                output_payload=_output_for(CreatorBriefSynthesis).model_dump(
                    mode="json"
                ),
                created_at=NOW - timedelta(hours=1),
                updated_at=NOW - timedelta(hours=1),
            )
        )
    result = resumer(committed_factory).run(source_id, mode="content-format")
    assert len(result.copied_nodes) == 11
    assert set(result.recomputed_nodes) == {
        REDUCTION_NODE_KEYS["content_format"],
        BRIEF_NODE_KEY,
    }
    with committed_factory() as session:
        for key in result.recomputed_nodes:
            assert session.get(CreatorAnalysisNode, (source_id, key)) is not None
            assert session.get(CreatorAnalysisNode, (result.job_id, key)) is None


def test_content_format_recovery_refuses_successful_source(committed_factory):
    source_id, _, _ = seed(committed_factory, succeeded=True)
    with pytest.raises(ResumeCreatorError, match="not eligible"):
        resumer(committed_factory).run(source_id, mode="content-format")
    with committed_factory() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisJob)) == 1
