from copy import deepcopy

import pytest
from sqlalchemy import select

from app.analysis.contracts import XCreatorSource, XPostSource
from app.analysis.creator_checkpoints import CreatorAnalysisCheckpointStore
from app.analysis.service import CreatorAnalysisService
from app.db.models.jobs import AnalysisJob
from app.db.models.profiles import CreatorProfile, CreatorContact
from app.db.models.enums import JobStatus
from app.integrations.errors import TransientIntegrationError
from tests.integration.test_creator_analysis_commit import (
    committed_factory,
    _job,
    Artifacts,
)
from tests.unit.analysis.test_creator_pipeline import (
    FakePages,
    FakeEmailResearch,
    EmailResearchRecord,
)
from tests.unit.analysis.test_ai_schemas import (
    creator_synthesis_payload,
    creator_metadata_unavailable_payload,
)
from app.schemas.ai_creator import CreatorSynthesis


def test_x_connection_secret_is_configurable_without_exposing_token(auth_client):
    response = auth_client.put(
        "/api/v1/settings/connections/x", json={"secret": "fixture-token"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["configured"] is True
    assert "fixture-token" not in response.text
    assert (
        auth_client.get("/api/v1/settings/connections/x").json()["configured"] is True
    )


def source(description="Contact press@example.com"):
    return XCreatorSource(
        platform_account_id="12345",
        canonical_url="https://x.com/i/user/12345",
        title="Example",
        username="example",
        description=description,
        follower_count=123,
        posts=(
            XPostSource(
                id="777", canonical_url="https://x.com/i/status/777", text="Indie games"
            ),
        ),
        raw_account={"data": {"id": "12345"}},
        raw_posts={"data": [{"id": "777"}]},
    )


def synthesis_payload():
    payload = creator_synthesis_payload()

    def rewrite(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "source_type" and item == "video_id":
                    value[key] = "public_link"
                elif key == "reference" and item == "video:video-1":
                    value[key] = "https://x.com/i/status/777"
                else:
                    rewrite(item)
        elif isinstance(value, list):
            for item in value:
                rewrite(item)

    rewrite(payload)
    for key in (
        "linked_site",
        "social_links",
        "representative_video_context",
        "livestream_tendency",
        "long_form_tendency",
        "short_form_tendency",
        "production_quality",
    ):
        payload[key] = {
            "status": "unavailable",
            "reason": "No video evidence supplied.",
        }
    return payload


class Model:
    failure = False

    def complete_structured(self, model, messages, schema):
        if self.failure:
            raise TransientIntegrationError("deepseek_unavailable")
        return schema.model_validate(
            synthesis_payload()
            if schema is CreatorSynthesis
            else creator_metadata_unavailable_payload()
        )


def pipeline(
    factory, *, description="Contact press@example.com", model=None, research=None
):
    from app.analysis.x_creator_pipeline import XCreatorAnalysisPipeline

    class X:
        def fetch_creator(self, account_id):
            assert account_id == "12345"
            return source(description)

    return XCreatorAnalysisPipeline(
        service=CreatorAnalysisService(session_factory=factory),
        x=X(),
        artifacts=Artifacts(),
        public_pages=FakePages(),
        deepseek=model or Model(),
        email_research=research,
        checkpoints=CreatorAnalysisCheckpointStore(session_factory=factory),
    )


def x_job(factory):
    job_id = _job(factory)
    with factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        job.canonical_target_id = "x:12345"
        job.canonical_url = "https://x.com/i/user/12345"
    return job_id


def test_x_publication_is_valid_in_migrated_db_and_common_consumers(committed_factory):
    from app.api.routes.match import _creator_card
    from app.api.routes.outreach import _creator_identity
    from app.repositories.match import MatchRepository

    factory = committed_factory
    job_id = x_job(factory)
    profile_id = pipeline(factory).run(job_id)
    with factory() as session:
        job = session.get(AnalysisJob, job_id)
        profile = session.get(CreatorProfile, profile_id)
        assert job.status is JobStatus.SUCCEEDED
        assert (
            profile.platform,
            profile.platform_account_id,
            profile.youtube_channel_id,
        ) == ("x", "12345", None)
        assert profile.source_status["x"] == "available"
        assert "youtube" not in profile.source_status
        assert profile.current_facts["follower_count"] == 123
        assert "subscriber_count" not in profile.current_facts
        assert "representative_videos" not in profile.current_facts
        assert profile.source_status["visual_analysis"] == "unavailable"
        assert profile.prompt_metadata["synthesis_prompt_version"] == "x-creator-v1"
        assert profile.brief["positioning"]["status"] == "available"
        assert _creator_identity(profile).platform == "x"
        assert _creator_card(profile).platform == "x"
        assert MatchRepository._youtube_source_is_current(
            profile.source_status, platform="x"
        )
    assert pipeline(factory).run(job_id) == profile_id


def test_x_email_fallback_and_failed_refresh_preserve_contacts_and_override(
    committed_factory,
):
    factory = committed_factory
    research = FakeEmailResearch(
        result=(
            EmailResearchRecord(
                "press@example.com", "Press", "https://example.com/press"
            ),
            EmailResearchRecord(
                "biz@example.com", "Partnerships", "https://example.com/contact"
            ),
        )
    )
    profile_id = pipeline(factory, description="Indie games", research=research).run(
        x_job(factory)
    )
    with factory.begin() as session:
        profile = session.get(CreatorProfile, profile_id)
        profile.manual_notes = "Keep this note"
        profile.manual_overrides = {"facts.title": "Manual title"}
        before = deepcopy(profile.brief)
        contacts = session.scalars(
            select(CreatorContact).where(CreatorContact.creator_id == profile_id)
        ).all()
        assert {c.purpose for c in contacts} == {"Press", "Partnerships"}
    model = Model()
    model.failure = True
    job_id = x_job(factory)
    with pytest.raises(TransientIntegrationError):
        pipeline(factory, model=model).run(job_id)
    with factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile.brief == before
        assert profile.manual_notes == "Keep this note"
        assert profile.manual_overrides == {"facts.title": "Manual title"}
        assert (
            len(
                session.scalars(
                    select(CreatorContact).where(
                        CreatorContact.creator_id == profile_id
                    )
                ).all()
            )
            == 2
        )
    model.failure = False
    assert pipeline(factory, model=model).run(job_id) == profile_id


def test_x_edit_catalog_excludes_video_source_fields_and_hides_stale_x():
    from app.services.profile_editing import edit_document

    profile = CreatorProfile(
        platform="x",
        platform_account_id="12345",
        canonical_url="https://x.com/i/user/12345",
        sort_name="Example",
        current_facts={"title": "Example"},
        source_status={"x": "stale"},
    )
    from uuid import uuid4

    profile.id = uuid4()
    doc = edit_document(profile)
    fields = {field.key: field for field in doc.fields}
    assert "analysis.representative_video_context" not in fields
    assert fields["facts.title"].source_value is None


def test_x_checkpoint_retry_skips_completed_source_metadata_and_contacts(
    committed_factory,
):
    from app.analysis.x_creator_pipeline import XCreatorAnalysisPipeline

    factory = committed_factory

    class RetryModel(Model):
        fail = True
        calls = []

        def complete_structured(self, model, messages, schema):
            self.calls.append(schema.__name__)
            if schema is CreatorSynthesis and self.fail:
                raise TransientIntegrationError("deepseek_unavailable")
            return super().complete_structured(model, messages, schema)

    model = RetryModel()
    job_id = x_job(factory)
    first = pipeline(factory, model=model)
    with pytest.raises(TransientIntegrationError):
        first.run(job_id)

    class ForbiddenX:
        def fetch_creator(self, account_id):
            raise AssertionError("completed source fetched again")

    model.fail = False
    retry = XCreatorAnalysisPipeline(
        service=CreatorAnalysisService(session_factory=factory),
        x=ForbiddenX(),
        artifacts=Artifacts(),
        public_pages=FakePages(),
        deepseek=model,
        checkpoints=CreatorAnalysisCheckpointStore(session_factory=factory),
    )
    assert retry.run(job_id)
    assert model.calls == [
        "CreatorMetadataAnalysis",
        "CreatorSynthesis",
        "CreatorSynthesis",
    ]


def test_published_x_creator_reads_through_match_and_outreach_preview(
    auth_client, session
):
    from sqlalchemy.orm import sessionmaker
    from tests.integration.test_send_batch_api import (
        _published_match,
        _configure,
        _payload,
    )

    task, creators, campaign = _published_match(
        session, [("Example", "press@example.com")]
    )
    creator = creators[0]
    creator.platform = "x"
    creator.platform_account_id = "12345"
    creator.youtube_channel_id = None
    creator.canonical_url = "https://x.com/i/user/12345"
    session.flush()
    factory = sessionmaker(
        bind=session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    assert pipeline(factory).run(x_job(factory)) == creator.id
    session.expire_all()
    existing = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "existing-x-profile"},
        json={"target_type": "creator", "url": "https://twitter.com/i/user/12345"},
    )
    assert existing.status_code == 200, existing.text
    assert existing.json()["existing_profile_id"] == str(creator.id)
    response = auth_client.get(f"/api/v1/matches/{task.id}")
    assert response.status_code == 200, response.text
    card = response.json()["recommended_matches"][0]["creator"]
    assert (
        card["platform"],
        card["platform_account_id"],
        card["youtube_channel_id"],
    ) == ("x", "12345", None)
    _configure(auth_client)
    preview = auth_client.post(
        "/api/v1/outreach/send-batches/preview", json=_payload(task, creators)
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["items"][0]["creator_id"] == str(creator.id)
    # A fresh Match captures X evidence; the platform is never rewritten as YouTube.
    from uuid import uuid4, UUID
    from app.db.models.match import MatchCandidateInput

    created = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": str(uuid4())},
        json={"game_id": str(task.game_id)},
    )
    assert created.status_code == 202, created.text
    snapshot = session.scalar(
        select(MatchCandidateInput).where(
            MatchCandidateInput.match_task_id == UUID(created.json()["id"]),
            MatchCandidateInput.creator_id == creator.id,
        )
    )
    assert snapshot is not None
    assert snapshot.locked_creator_profile["platform"] == "x"


def test_x_due_schedule_and_staleness_use_generic_identity(committed_factory):
    from datetime import UTC, datetime, timedelta
    from app.repositories.profiles import ProfilesRepository

    factory = committed_factory
    profile_id = pipeline(factory).run(x_job(factory))
    now = datetime.now(UTC)
    with factory.begin() as session:
        profile = session.get(CreatorProfile, profile_id)
        profile.next_analysis_at = now - timedelta(days=1)
        profile.last_analyzed_at = now - timedelta(days=31)
        session.flush()
        repository = ProfilesRepository(session)
        due = repository.list_due_profiles(now=now, limit=100)
        assert [(p.profile_id, p.canonical_target_id) for p in due] == [
            (profile_id, "x:12345")
        ]
        assert repository.mark_stale_creators(now) == 1
        session.refresh(profile)
        assert profile.source_status["x"] == "stale"
        assert "youtube" not in profile.source_status
        assert repository.mark_stale_creators(now) == 0
    x_job(factory)
    with factory() as session:
        assert ProfilesRepository(session).list_due_profiles(now=now, limit=100) == []


@pytest.mark.parametrize(
    "code",
    [
        "x_configuration_invalid",
        "x_payment_required",
        "x_spend_cap_reached",
        "x_request_rejected",
        "x_rate_limited",
        "x_unavailable",
    ],
)
def test_x_safe_worker_failures_persist_under_migrated_constraint(
    committed_factory, code
):
    from app.core.analysis_job_contract import public_job_failure
    from app.workers.analysis_tasks import AnalysisJobExecutor, TerminalFailure

    factory = committed_factory
    job_id = x_job(factory)
    expected = public_job_failure(code)
    executor = AnalysisJobExecutor(
        session_factory=factory, pipeline_factory=lambda _: None
    )
    assert executor.fail(
        job_id,
        TerminalFailure(
            code=code, message=expected.message, retryable=expected.retryable
        ),
    )
    with factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job.error_code == code
        assert job.retryable == expected.retryable
        assert job.status is JobStatus.FAILED


def test_production_dispatcher_selects_x_from_persisted_job(
    committed_factory, monkeypatch
):
    from contextlib import contextmanager
    from app.analysis.runtime import ProductionAnalysisRuntime
    from app.core.config import get_settings
    from app.workers.analysis_tasks import AnalysisJobExecutor

    factory = committed_factory
    job_id = x_job(factory)
    runtime = ProductionAnalysisRuntime(
        settings=get_settings(), session_factory=factory, secret_provider=None
    )

    @contextmanager
    def build(target_type, *, platform):
        assert platform == "x"
        yield pipeline(factory)

    monkeypatch.setattr(runtime, "pipeline_for", build)
    AnalysisJobExecutor(
        session_factory=factory, pipeline_factory=runtime.dispatch_for
    ).execute(job_id)
    with factory() as session:
        assert session.get(AnalysisJob, job_id).status is JobStatus.SUCCEEDED
