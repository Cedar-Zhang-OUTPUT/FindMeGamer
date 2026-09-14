from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta, tzinfo
from threading import Event, Lock, Thread, current_thread
from time import monotonic
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.creator_pipeline import CreatorAnalysisPipeline
from app.analysis.service import CreatorAnalysisService
from app.db.models.enums import AnalysisStage, JobMode, JobStatus, TargetType
from app.db.models.jobs import AnalysisJob, acquire_job_change_lock
from app.db.models.profiles import CreatorContact, CreatorProfile
from app.db.models.settings import SharedSettings
from app.integrations.errors import PermanentIntegrationError, TransientIntegrationError
from app.repositories.profiles import ProfilesRepository
from app.repositories.settings import SHARED_SETTINGS_ID
from app.schemas.ai_creator import (
    CreatorMetadataAnalysis,
    CreatorSynthesis,
    CreatorVisualAnalysis,
)

from tests.unit.analysis.test_ai_schemas import (
    creator_metadata_unavailable_payload,
    creator_synthesis_payload,
    creator_visual_unavailable_payload,
)
from tests.unit.analysis.test_creator_pipeline import (
    EmailResearchRecord,
    FakeEmailResearch,
    FakePages,
    Page,
    _source,
)


NOW = datetime(2026, 9, 4, 9, 15, tzinfo=UTC)
JOB_CREATED_AT = datetime(2000, 1, 1, tzinfo=UTC)


@pytest.fixture
def committed_factory(
    migrated_database: None, database_engine: Engine
) -> Iterator[sessionmaker[Session]]:
    factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(delete(AnalysisJob))
        session.execute(delete(CreatorContact))
        session.execute(delete(CreatorProfile))
        settings = session.scalar(select(SharedSettings).with_for_update())
        assert settings is not None
        settings.creator_interval_days = 14
    yield factory
    with factory.begin() as session:
        session.execute(delete(AnalysisJob))
        session.execute(delete(CreatorContact))
        session.execute(delete(CreatorProfile))


def _job(
    factory: sessionmaker[Session],
    *,
    target_type: TargetType = TargetType.CREATOR,
    status: JobStatus = JobStatus.QUEUED,
    profile_id: UUID | None = None,
) -> UUID:
    job_id = uuid4()
    effective_profile_id = (
        profile_id or uuid4() if status is JobStatus.SUCCEEDED else None
    )
    with factory.begin() as session:
        session.add(
            AnalysisJob(
                id=job_id,
                target_type=target_type,
                canonical_target_id="UCcreator123",
                canonical_url="https://www.youtube.com/channel/UCcreator123",
                mode=JobMode.REANALYZE,
                status=status,
                stage=(
                    AnalysisStage.FINALIZING
                    if status is JobStatus.SUCCEEDED
                    else (
                        AnalysisStage.FETCHING_DATA
                        if status is JobStatus.RUNNING
                        else None
                    )
                ),
                completed_units=5 if status is JobStatus.SUCCEEDED else 0,
                total_units=(
                    5 if status in (JobStatus.RUNNING, JobStatus.SUCCEEDED) else 0
                ),
                error_code=(
                    "analysis_internal_error" if status is JobStatus.FAILED else None
                ),
                error_message=(
                    "Analysis failed unexpectedly. Please retry."
                    if status is JobStatus.FAILED
                    else None
                ),
                retryable=status is JobStatus.FAILED,
                profile_id=effective_profile_id,
                created_at=JOB_CREATED_AT,
                result_payload=(
                    {"profile_id": str(effective_profile_id)}
                    if effective_profile_id is not None
                    else None
                ),
                started_at=(
                    NOW if status in (JobStatus.RUNNING, JobStatus.SUCCEEDED) else None
                ),
                completed_at=(
                    NOW if status in (JobStatus.FAILED, JobStatus.SUCCEEDED) else None
                ),
            )
        )
    return job_id


def _profile(factory: sessionmaker[Session]) -> UUID:
    profile_id = uuid4()
    with factory.begin() as session:
        profile = CreatorProfile(
            id=profile_id,
            youtube_channel_id="UCcreator123",
            canonical_url="https://www.youtube.com/channel/UCcreator123",
            sort_name="Old Creator",
            current_facts={"old": "facts"},
            analysis={"old": "analysis"},
            brief={"old": "brief"},
            source_status={"old": "status"},
            model_metadata={"old": "models"},
            prompt_metadata={"old": "prompts"},
            favorite=True,
            manual_notes="Warm lead",
            last_analyzed_at=NOW - timedelta(days=40),
            next_analysis_at=NOW - timedelta(days=20),
        )
        profile.contacts.extend(
            [
                CreatorContact(
                    email="team@example.com",
                    source_type="manual",
                    is_manual=True,
                    validation_state="unverified",
                    priority=0,
                    is_active=True,
                ),
                CreatorContact(
                    email="old@example.net",
                    purpose="Legacy partnerships",
                    source_type="linked_public_page",
                    source_url="https://old.example/contact",
                    is_manual=False,
                    validation_state="valid",
                    priority=10,
                    is_active=True,
                ),
            ]
        )
        session.add(profile)
    return profile_id


class YouTube:
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure

    def fetch_creator(self, channel_id: str, video_limit: int = 50):
        if self.failure:
            raise self.failure
        return _source()


class Artifacts:
    def __init__(self, *, fail_name: str | None = None) -> None:
        self.fail_name = fail_name
        self.names: list[str] = []

    def put_json(self, job_id: UUID, name: str, payload: object) -> str:
        if name == self.fail_name:
            raise TransientIntegrationError("artifact_unavailable")
        self.names.append(name)
        return f"acquisition/{job_id}/{name}"


class AI:
    def __init__(
        self,
        *,
        fail_schema: type | None = None,
        structured: list[object] | None = None,
        vision_failure: BaseException | None = None,
    ) -> None:
        self.fail_schema = fail_schema
        self.structured = list(structured or [])
        self.vision_failure = vision_failure

    def complete_structured(self, model: str, messages: list, schema: type):
        if schema is self.fail_schema:
            raise TransientIntegrationError("model_unavailable")
        if self.structured:
            value = self.structured.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value
        if schema is CreatorMetadataAnalysis:
            return CreatorMetadataAnalysis.model_validate(
                creator_metadata_unavailable_payload()
            )
        payload = creator_synthesis_payload()
        payload["linked_site"] = {
            "status": "available",
            "candidate_id": "contact.site.0",
        }
        payload["social_links"] = {
            "status": "available",
            "candidate_ids": ["contact.social.0"],
        }
        return CreatorSynthesis.model_validate(payload)

    def complete_vision(self, model: str, prompt: str, image_urls: list, schema: type):
        if self.vision_failure:
            raise self.vision_failure
        return CreatorVisualAnalysis.model_validate(
            creator_visual_unavailable_payload()
        )


def _pipeline(
    factory: sessionmaker[Session],
    *,
    youtube: YouTube | None = None,
    artifacts: Artifacts | None = None,
    pages: FakePages | None = None,
    email_research: FakeEmailResearch | None = None,
    ai: AI | None = None,
    clock=lambda: NOW,
) -> CreatorAnalysisPipeline:
    return CreatorAnalysisPipeline(
        service=CreatorAnalysisService(session_factory=factory, clock=clock),
        youtube=youtube or YouTube(),
        artifacts=artifacts or Artifacts(),
        public_pages=pages
        or FakePages(
            {
                "https://creator.example/about": Page(
                    "https://creator.example/about",
                    "partnerships@example.org https://social.example/creator",
                )
            }
        ),
        deepseek=ai or AI(),
        email_research=email_research,
    )


def _snapshot(factory: sessionmaker[Session], profile_id: UUID) -> dict[str, object]:
    with factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile is not None
        contacts = session.scalars(
            select(CreatorContact)
            .where(CreatorContact.creator_id == profile_id)
            .order_by(CreatorContact.is_manual.desc(), CreatorContact.email)
        ).all()
        return {
            "manual_overrides": deepcopy(profile.manual_overrides),
            "profile_revision": profile.profile_revision,
            "current_facts": deepcopy(profile.current_facts),
            "analysis": deepcopy(profile.analysis),
            "brief": deepcopy(profile.brief),
            "source_status": deepcopy(profile.source_status),
            "model_metadata": deepcopy(profile.model_metadata),
            "prompt_metadata": deepcopy(profile.prompt_metadata),
            "favorite": profile.favorite,
            "manual_notes": profile.manual_notes,
            "last_analyzed_at": profile.last_analyzed_at,
            "next_analysis_at": profile.next_analysis_at,
            "contacts": [
                (
                    contact.email,
                    contact.purpose,
                    contact.source_type,
                    contact.source_url,
                    contact.is_manual,
                    contact.validation_state,
                    contact.priority,
                    contact.is_active,
                )
                for contact in contacts
            ],
        }


def test_create_publishes_exact_projection_and_job_atomically(
    committed_factory,
) -> None:
    with committed_factory.begin() as session:
        settings = session.scalar(select(SharedSettings).with_for_update())
        assert settings is not None
        settings.creator_interval_days = 9
    job_id = _job(committed_factory)
    artifacts = Artifacts()

    profile_id = _pipeline(committed_factory, artifacts=artifacts).run(job_id)

    with committed_factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        job = session.get(AnalysisJob, job_id)
        assert profile is not None and job is not None
        assert profile.youtube_channel_id == "UCcreator123"
        assert profile.current_facts["title"] == "Example Creator"
        assert profile.current_facts["recent_metrics"]["recent_public_video_count"] == 1
        assert profile.current_facts["representative_videos"][0]["id"] == "video-1"
        assert "raw_channel" not in profile.current_facts
        assert "creator_brief" not in profile.analysis
        assert "english_language_check" not in profile.analysis
        assert "public_email" not in profile.analysis
        assert profile.analysis["public_contact"] == {
            "email": {
                "value": "press@example.com",
                "purpose": None,
                "source_type": "channel_description",
                "source_url": "https://www.youtube.com/channel/UCcreator123",
                "validation_state": "validated",
            },
            "emails": [
                {
                    "value": "press@example.com",
                    "purpose": None,
                    "source_type": "channel_description",
                    "source_url": "https://www.youtube.com/channel/UCcreator123",
                    "validation_state": "validated",
                },
                {
                    "value": "partnerships@example.org",
                    "purpose": None,
                    "source_type": "linked_public_page",
                    "source_url": "https://creator.example/about",
                    "validation_state": "validated",
                },
            ],
            "linked_site": {
                "value": "https://creator.example/about",
                "source_type": "channel_description",
                "source_url": "https://www.youtube.com/channel/UCcreator123",
                "validation_state": "unvalidated",
            },
            "social_links": [
                {
                    "value": "https://social.example/creator",
                    "source_type": "channel_description",
                    "source_url": "https://www.youtube.com/channel/UCcreator123",
                    "validation_state": "unvalidated",
                }
            ],
        }
        assert profile.last_analyzed_at == NOW
        assert profile.next_analysis_at == NOW + timedelta(days=9)
        assert profile.source_status == {
            "youtube": "available",
            "visual_analysis": "unavailable",
            "contact_discovery": "available",
            "freshness": "current",
        }
        assert profile.model_metadata == {
            "metadata_model": "deepseek-v4-flash",
            "vision_model": "deepseek-v4-flash-vision-exp",
            "synthesis_model": "deepseek-v4-pro",
            "vision_available": False,
        }
        assert job.status is JobStatus.SUCCEEDED
        assert job.stage is AnalysisStage.FINALIZING
        assert job.completed_units == job.total_units == 5
        assert job.profile_id == profile_id
        assert artifacts.names == [
            "youtube-channel.json",
            "youtube-playlist-pages.json",
            "youtube-video-responses.json",
        ]


def test_publication_uses_canonical_settings_when_rogue_row_exists(
    committed_factory,
) -> None:
    rogue_id = uuid4()
    with committed_factory.begin() as session:
        canonical = session.get(SharedSettings, SHARED_SETTINGS_ID)
        assert canonical is not None
        canonical.creator_interval_days = 11
        session.add(SharedSettings(id=rogue_id, creator_interval_days=7))
    try:
        job_id = _job(committed_factory)

        profile_id = _pipeline(committed_factory).run(job_id)

        with committed_factory() as session:
            profile = session.get(CreatorProfile, profile_id)
            assert profile is not None
            assert profile.next_analysis_at == NOW + timedelta(days=11)
    finally:
        with committed_factory.begin() as session:
            rogue = session.get(SharedSettings, rogue_id)
            if rogue is not None:
                session.delete(rogue)


def test_publication_fails_when_canonical_settings_are_missing_even_with_rogue_row(
    committed_factory,
) -> None:
    rogue_id = uuid4()
    with committed_factory.begin() as session:
        canonical = session.get(SharedSettings, SHARED_SETTINGS_ID)
        assert canonical is not None
        session.delete(canonical)
        session.add(SharedSettings(id=rogue_id, creator_interval_days=7))
    try:
        job_id = _job(committed_factory)

        with pytest.raises(PermanentIntegrationError, match="shared_settings_missing"):
            _pipeline(committed_factory).run(job_id)
    finally:
        with committed_factory.begin() as session:
            rogue = session.get(SharedSettings, rogue_id)
            if rogue is not None:
                session.delete(rogue)
            if session.get(SharedSettings, SHARED_SETTINGS_ID) is None:
                session.add(SharedSettings(id=SHARED_SETTINGS_ID))


def test_reanalysis_preserves_manual_contact_notes_favorite_and_replaces_discovered(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    with committed_factory.begin() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile is not None
        profile.manual_overrides = {
            "facts.title": "Human creator",
            "facts.description": "Human description",
        }
        profile.profile_revision = 6
        profile.source_status = {
            "youtube": "stale",
            "freshness": "stale",
            "custom_marker": "replaced after successful refresh",
        }
    job_id = _job(committed_factory)

    assert _pipeline(committed_factory).run(job_id) == profile_id

    snapshot = _snapshot(committed_factory, profile_id)
    with committed_factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile.manual_overrides == {
            "facts.title": "Human creator",
            "facts.description": "Human description",
        }
        assert profile.current_facts["description"] == _source().description
        from app.services.profile_editing import apply_edit, edit_document
        from app.schemas.profile_editing import ProfileEditPatch

        apply_edit(
            profile,
            ProfileEditPatch(
                expected_revision=7, changes={}, reset_fields=["facts.description"]
            ),
        )
        description = next(
            field
            for field in edit_document(profile).fields
            if field.key == "facts.description"
        )
        assert description.value == _source().description
        assert not description.is_overridden
        assert profile.profile_revision == 8
        found, _ = ProfilesRepository(session).list_creators(
            query="Human creator", only_collection=False, cursor=None, limit=50
        )
        assert [row.id for row in found] == [profile_id]
    assert snapshot["favorite"] is True
    assert snapshot["manual_notes"] == "Warm lead"
    assert snapshot["source_status"] == {
        "youtube": "available",
        "visual_analysis": "unavailable",
        "contact_discovery": "available",
        "freshness": "current",
    }
    assert (
        "team@example.com",
        None,
        "manual",
        None,
        True,
        "unverified",
        0,
        True,
    ) in snapshot["contacts"]
    assert all(item[0] != "old@example.net" for item in snapshot["contacts"])
    assert (
        "press@example.com",
        None,
        "channel_description",
        "https://www.youtube.com/channel/UCcreator123",
        False,
        "valid",
        10,
        True,
    ) in snapshot["contacts"]


def test_no_contact_publication_replaces_discovered_rows_with_explicit_empty_projection(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    job_id = _job(committed_factory)

    class NoContactYouTube(YouTube):
        def fetch_creator(self, channel_id: str, video_limit: int = 50):
            return _source().model_copy(update={"description": "No public contact."})

    synthesis_payload = creator_synthesis_payload()
    synthesis_payload["public_email"] = {
        "status": "unavailable",
        "reason": "Not found.",
    }
    synthesis_payload["linked_site"] = {
        "status": "unavailable",
        "reason": "Not found.",
    }
    synthesis_payload["social_links"] = {
        "status": "unavailable",
        "reason": "Not found.",
    }
    metadata = CreatorMetadataAnalysis.model_validate(
        creator_metadata_unavailable_payload()
    )
    synthesis = CreatorSynthesis.model_validate(synthesis_payload)

    _pipeline(
        committed_factory,
        youtube=NoContactYouTube(),
        pages=FakePages({}),
        ai=AI(structured=[metadata, synthesis]),
    ).run(job_id)

    with committed_factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile is not None
        assert profile.analysis["public_contact"] == {
            "email": None,
            "emails": [],
            "linked_site": None,
            "social_links": [],
        }
        assert profile.source_status["contact_discovery"] == "unavailable"
        contacts = session.scalars(
            select(CreatorContact).where(
                CreatorContact.creator_id == profile_id,
                CreatorContact.is_manual.is_(False),
            )
        ).all()
        assert contacts == []


def test_public_web_research_email_reaches_library_and_outreach_contact_projection(
    committed_factory,
) -> None:
    job_id = _job(committed_factory)

    class SiteOnlyYouTube(YouTube):
        def fetch_creator(self, channel_id: str, video_limit: int = 50):
            return _source().model_copy(
                update={"description": "https://creator.example/about"}
            )

    synthesis_payload = creator_synthesis_payload()
    synthesis_payload["public_email"] = {
        "status": "unavailable",
        "reason": "No direct email appeared in the original channel evidence.",
    }
    synthesis_payload["social_links"] = {
        "status": "unavailable",
        "reason": "No social link appeared in the supplied contact evidence.",
    }
    metadata = CreatorMetadataAnalysis.model_validate(
        creator_metadata_unavailable_payload()
    )
    synthesis = CreatorSynthesis.model_validate(synthesis_payload)
    research = FakeEmailResearch(
        (
            EmailResearchRecord(
                email="agency@example.com",
                usage="Business inquiries",
                source="https://agency.example/creator/contact",
            ),
            EmailResearchRecord(
                email="press@example.com",
                usage="Press requests",
                source="https://press.example/creator",
            ),
        )
    )

    profile_id = _pipeline(
        committed_factory,
        youtube=SiteOnlyYouTube(),
        pages=FakePages(
            {
                "https://creator.example/about": Page(
                    "https://creator.example/about", "No direct email listed."
                )
            }
        ),
        email_research=research,
        ai=AI(structured=[metadata, synthesis]),
    ).run(job_id)

    with committed_factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        contacts = session.scalars(
            select(CreatorContact)
            .where(
                CreatorContact.creator_id == profile_id,
                CreatorContact.is_manual.is_(False),
            )
            .order_by(CreatorContact.priority.desc())
        ).all()
        assert profile is not None
        assert profile.analysis["public_contact"]["email"] == {
            "value": "agency@example.com",
            "purpose": "Business inquiries",
            "source_type": "public_web_research",
            "source_url": "https://agency.example/creator/contact",
            "validation_state": "unvalidated",
        }
        assert profile.analysis["public_contact"]["emails"] == [
            {
                "value": "agency@example.com",
                "purpose": "Business inquiries",
                "source_type": "public_web_research",
                "source_url": "https://agency.example/creator/contact",
                "validation_state": "unvalidated",
            },
            {
                "value": "press@example.com",
                "purpose": "Press requests",
                "source_type": "public_web_research",
                "source_url": "https://press.example/creator",
                "validation_state": "unvalidated",
            },
        ]
        assert [(contact.email, contact.purpose) for contact in contacts] == [
            ("agency@example.com", "Business inquiries"),
            ("press@example.com", "Press requests"),
        ]
        assert all(
            contact.source_type == "public_web_research"
            and contact.validation_state == "unverified"
            and contact.is_active
            for contact in contacts
        )


def test_public_web_research_failure_preserves_existing_profile_and_contacts(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    before = _snapshot(committed_factory, profile_id)
    job_id = _job(committed_factory)

    class NoContactYouTube(YouTube):
        def fetch_creator(self, channel_id: str, video_limit: int = 50):
            return _source().model_copy(update={"description": "No public contact."})

    pipeline = _pipeline(
        committed_factory,
        youtube=NoContactYouTube(),
        pages=FakePages({}),
        email_research=FakeEmailResearch(
            TransientIntegrationError("public_page_unavailable")
        ),
    )

    with pytest.raises(TransientIntegrationError, match="public_page_unavailable"):
        pipeline.run(job_id)

    assert _snapshot(committed_factory, profile_id) == before


@pytest.mark.parametrize(
    "failure_stage",
    [
        "youtube",
        "youtube-channel.json",
        "youtube-playlist-pages.json",
        "youtube-video-responses.json",
        "public_pages",
        "metadata",
        "synthesis",
    ],
)
def test_every_prepublication_failure_preserves_profile_and_contacts(
    committed_factory, failure_stage: str
) -> None:
    profile_id = _profile(committed_factory)
    with committed_factory.begin() as session:
        profile = session.get(CreatorProfile, profile_id)
        profile.manual_overrides = {"facts.title": "Retained human title"}
        profile.profile_revision = 3
    before = _snapshot(committed_factory, profile_id)
    job_id = _job(committed_factory)
    youtube = YouTube(
        failure=(
            TransientIntegrationError("youtube_unavailable")
            if failure_stage == "youtube"
            else None
        )
    )
    artifacts = Artifacts(
        fail_name=failure_stage if failure_stage.endswith(".json") else None
    )
    pages = FakePages(
        {
            "https://creator.example/about": (
                RuntimeError("programmer failure")
                if failure_stage == "public_pages"
                else Page("https://creator.example/about", "partnerships@example.org")
            ),
        }
    )
    fail_schema = (
        CreatorMetadataAnalysis
        if failure_stage == "metadata"
        else CreatorSynthesis if failure_stage == "synthesis" else None
    )
    with pytest.raises(BaseException):
        _pipeline(
            committed_factory,
            youtube=youtube,
            artifacts=artifacts,
            pages=pages,
            ai=AI(fail_schema=fail_schema),
        ).run(job_id)

    assert _snapshot(committed_factory, profile_id) == before


def test_final_flush_failure_rolls_back_profile_contacts_and_job(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    before = _snapshot(committed_factory, profile_id)
    job_id = _job(committed_factory)

    def fail(session: Session, flush_context, instances) -> None:
        if any(
            isinstance(item, CreatorProfile) and item.analysis != {"old": "analysis"}
            for item in session.dirty
        ):
            raise RuntimeError("final-publication-failure")

    event.listen(Session, "before_flush", fail)
    try:
        with pytest.raises(RuntimeError, match="final-publication-failure"):
            _pipeline(committed_factory).run(job_id)
    finally:
        event.remove(Session, "before_flush", fail)

    assert _snapshot(committed_factory, profile_id) == before
    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.RUNNING
        assert job.stage is AnalysisStage.FINALIZING
        assert job.profile_id is None


def test_vision_programmer_failure_preserves_profile_and_contacts(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    before = _snapshot(committed_factory, profile_id)
    job_id = _job(committed_factory)

    with pytest.raises(ValueError, match="vision-programmer-failure"):
        _pipeline(
            committed_factory,
            ai=AI(vision_failure=ValueError("vision-programmer-failure")),
        ).run(job_id)

    assert _snapshot(committed_factory, profile_id) == before


def test_semantic_and_contact_binder_failures_preserve_profile_and_contacts(
    committed_factory,
) -> None:
    from app.integrations.errors import InvalidModelOutput

    profile_id = _profile(committed_factory)
    before = _snapshot(committed_factory, profile_id)
    job_id = _job(committed_factory)
    bad_metadata_payload = creator_metadata_unavailable_payload()
    bad_metadata_payload["pacing"] = {
        "status": "available",
        "value": "Fast",
        "evidence": [
            {
                "kind": "source_fact",
                "source_type": "channel_field",
                "reference": "channel:unknown",
                "observation": "Invalid.",
            }
        ],
        "confidence": "low",
    }
    bad_metadata = CreatorMetadataAnalysis.model_validate(bad_metadata_payload)
    with pytest.raises(InvalidModelOutput, match="evidence"):
        _pipeline(
            committed_factory,
            ai=AI(structured=[bad_metadata, bad_metadata]),
        ).run(job_id)
    assert _snapshot(committed_factory, profile_id) == before

    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.status = JobStatus.FAILED
        job.error_code = "analysis_internal_error"
        job.error_message = "Analysis failed unexpectedly. Please retry."
        job.retryable = True
        job.completed_at = NOW
    next_job = _job(committed_factory)
    bad_contact_payload = creator_synthesis_payload()
    bad_contact_payload["public_email"] = {
        "status": "available",
        "candidate_id": "contact.email.fabricated",
    }
    bad_contact = CreatorSynthesis.model_validate(bad_contact_payload)
    good_metadata = CreatorMetadataAnalysis.model_validate(
        creator_metadata_unavailable_payload()
    )
    with pytest.raises(InvalidModelOutput, match="contacts"):
        _pipeline(
            committed_factory,
            ai=AI(structured=[good_metadata, bad_contact, bad_contact]),
        ).run(next_job)
    assert _snapshot(committed_factory, profile_id) == before


@pytest.mark.parametrize(
    ("status", "stage", "units", "total_units"),
    [
        (JobStatus.RUNNING, AnalysisStage.ANALYZING, 3, 5),
        (JobStatus.RUNNING, AnalysisStage.FINALIZING, 6, 7),
    ],
)
def test_resume_preserves_stage_started_at_and_progress(
    committed_factory, status, stage, units, total_units
) -> None:
    job_id = _job(committed_factory, status=status)
    first_started = NOW - timedelta(minutes=30)
    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.stage = stage
        job.completed_units = units
        job.total_units = total_units
        job.started_at = first_started

    CreatorAnalysisService(session_factory=committed_factory, clock=lambda: NOW).start(
        job_id
    )

    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.RUNNING
        assert job.stage is stage
        assert job.completed_units == units
        assert job.total_units == total_units
        assert job.started_at == first_started


def test_succeeded_idempotency_and_concurrent_finalization_converge(
    committed_factory,
) -> None:
    job_id = _job(committed_factory)
    first = _pipeline(committed_factory).run(job_id)
    assert (
        _pipeline(
            committed_factory,
            youtube=YouTube(failure=AssertionError("no external call")),
        ).run(job_id)
        == first
    )

    with committed_factory() as session:
        assert session.query(CreatorProfile).count() == 1


def test_manual_creator_update_serializes_before_job_finalization(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    job_id = _job(committed_factory, status=JobStatus.RUNNING)
    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.stage = AnalysisStage.FINALIZING
        job.completed_units = 4

    manual_profile_locked = Event()
    release_manual = Event()
    finalizer_pid_ready = Event()
    finalizer_advisory_acquired = Event()
    finalizer_profile_select_started = Event()
    finalizer_pid: list[int] = []
    errors: list[BaseException] = []

    engine = committed_factory.kw["bind"]

    def observe_profile_lock(
        connection, cursor, statement, parameters, context, executemany
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if not (
            normalized.startswith("select creator_profiles")
            and normalized.endswith("for update")
        ):
            return
        if current_thread().name == "manual-profile-update":
            manual_profile_locked.set()
            if not release_manual.wait(timeout=5):
                raise AssertionError("manual update was not released")

    def observe_profile_select_start(
        connection, cursor, statement, parameters, context, executemany
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if (
            current_thread().name == "job-finalizer"
            and normalized.startswith("select creator_profiles")
            and normalized.endswith("for update")
        ):
            finalizer_profile_select_started.set()

    def manual_update() -> None:
        try:
            with committed_factory.begin() as session:
                updated = ProfilesRepository(session).update_creator_manual(
                    profile_id,
                    contact_email="new-owner@example.com",
                    notes="Serialized manual edit",
                )
                assert updated is not None
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    def finalize_job() -> None:
        try:
            with committed_factory.begin() as session:
                finalizer_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
                finalizer_pid_ready.set()
                acquire_job_change_lock(session)
                finalizer_advisory_acquired.set()
                job = session.scalar(
                    select(AnalysisJob)
                    .where(AnalysisJob.id == job_id)
                    .with_for_update()
                )
                profile = session.scalar(
                    select(CreatorProfile)
                    .where(CreatorProfile.id == profile_id)
                    .with_for_update()
                )
                assert job is not None and profile is not None
                job.status = JobStatus.SUCCEEDED
                job.profile_id = profile.id
                job.result_payload = {"profile_id": str(profile.id)}
                job.completed_units = job.total_units
                job.completed_at = NOW
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    event.listen(engine, "after_cursor_execute", observe_profile_lock)
    event.listen(engine, "before_cursor_execute", observe_profile_select_start)
    manual_thread = Thread(target=manual_update, name="manual-profile-update")
    finalizer_thread = Thread(target=finalize_job, name="job-finalizer")
    try:
        manual_thread.start()
        assert manual_profile_locked.wait(timeout=5)
        finalizer_thread.start()
        assert finalizer_pid_ready.wait(timeout=5)

        deadline = monotonic() + 5
        while monotonic() < deadline:
            if finalizer_profile_select_started.is_set():
                break
            with committed_factory() as observer:
                waiting_for_advisory = observer.execute(
                    text(
                        "SELECT count(*) FROM pg_locks "
                        "WHERE pid = :pid AND locktype = 'advisory' AND NOT granted"
                    ),
                    {"pid": finalizer_pid[0]},
                ).scalar_one()
            if waiting_for_advisory:
                break
        else:
            raise AssertionError("finalizer did not reach a serialized lock wait")
    finally:
        release_manual.set()
        manual_thread.join(timeout=5)
        finalizer_thread.join(timeout=5)
        event.remove(engine, "after_cursor_execute", observe_profile_lock)
        event.remove(engine, "before_cursor_execute", observe_profile_select_start)

    assert not manual_thread.is_alive()
    assert not finalizer_thread.is_alive()
    assert errors == []
    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        profile = session.get(CreatorProfile, profile_id)
        assert job is not None and profile is not None
        assert job.status is JobStatus.SUCCEEDED
        assert profile.manual_notes == "Serialized manual edit"


def test_advance_is_forward_only_and_succeeded_is_a_noop(committed_factory) -> None:
    job_id = _job(committed_factory, status=JobStatus.RUNNING)
    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.stage = AnalysisStage.FINALIZING
        job.completed_units = 4
        job.total_units = 5
    service = CreatorAnalysisService(
        session_factory=committed_factory, clock=lambda: NOW
    )
    service.advance(job_id, completed_units=2)
    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.stage is AnalysisStage.FINALIZING
        assert job.completed_units == 4

    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        profile = CreatorProfile(
            youtube_channel_id="UCcreator123",
            canonical_url="https://www.youtube.com/channel/UCcreator123",
            sort_name="Creator",
        )
        session.add(profile)
        session.flush()
        job.status = JobStatus.SUCCEEDED
        job.profile_id = profile.id
        job.result_payload = {"profile_id": str(profile.id)}
        job.completed_units = 5
        job.completed_at = NOW
    service.advance(job_id, completed_units=2)
    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.SUCCEEDED
        assert job.completed_units == 5


def test_advance_keeps_nondefault_running_progress_below_total(
    committed_factory,
) -> None:
    job_id = _job(committed_factory, status=JobStatus.RUNNING)
    with committed_factory.begin() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.completed_units = 0
        job.total_units = 1

    CreatorAnalysisService(
        session_factory=committed_factory, clock=lambda: NOW
    ).advance(job_id, completed_units=2)

    with committed_factory() as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.RUNNING
        assert job.stage is AnalysisStage.ANALYZING
        assert (job.completed_units, job.total_units) == (0, 1)


def test_invalid_current_creator_interval_rolls_back_publication(
    committed_factory,
) -> None:
    profile_id = _profile(committed_factory)
    before = _snapshot(committed_factory, profile_id)
    job_id = _job(committed_factory)
    original = CreatorAnalysisService._read_creator_interval
    CreatorAnalysisService._read_creator_interval = staticmethod(lambda settings: 31)
    try:
        with pytest.raises(PermanentIntegrationError, match="creator_interval_invalid"):
            _pipeline(committed_factory).run(job_id)
    finally:
        CreatorAnalysisService._read_creator_interval = staticmethod(original)
    assert _snapshot(committed_factory, profile_id) == before


def test_full_title_is_preserved_while_sort_name_is_bounded(committed_factory) -> None:
    title = "创" * 300
    job_id = _job(committed_factory)

    class TitledYouTube(YouTube):
        def fetch_creator(self, channel_id: str, video_limit: int = 50):
            return _source().model_copy(update={"title": title})

    profile_id = _pipeline(committed_factory, youtube=TitledYouTube()).run(job_id)
    with committed_factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile is not None
        assert profile.sort_name == title[:255]
        assert profile.current_facts["title"] == title


def test_overlapping_full_runs_converge_on_one_creator_publication(
    committed_factory,
) -> None:
    job_id = _job(committed_factory)
    second_fetch_started = Event()
    release_second_fetch = Event()
    publication_lock = Lock()
    publication_flushes = 0
    results: list[UUID] = []
    errors: list[BaseException] = []

    class BlockingYouTube(YouTube):
        def fetch_creator(self, channel_id: str, video_limit: int = 50):
            second_fetch_started.set()
            if not release_second_fetch.wait(timeout=10):
                raise AssertionError("concurrent test did not release YouTube fetch")
            return super().fetch_creator(channel_id, video_limit)

    def count_publication(session: Session, flush_context) -> None:
        nonlocal publication_flushes
        if any(
            isinstance(item, CreatorProfile) for item in session.new | session.dirty
        ):
            with publication_lock:
                publication_flushes += 1

    delayed = _pipeline(committed_factory, youtube=BlockingYouTube())

    def run_delayed() -> None:
        try:
            results.append(delayed.run(job_id))
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    thread = Thread(target=run_delayed)
    listener_registered = False
    try:
        thread.start()
        assert second_fetch_started.wait(timeout=10)
        event.listen(Session, "after_flush", count_publication)
        listener_registered = True
        first_profile_id = _pipeline(committed_factory).run(job_id)
        release_second_fetch.set()
        thread.join(timeout=10)
    finally:
        release_second_fetch.set()
        thread.join(timeout=10)
        if listener_registered:
            event.remove(Session, "after_flush", count_publication)

    assert not thread.is_alive()
    assert errors == []
    assert results == [first_profile_id]
    assert publication_flushes == 1
    with committed_factory() as session:
        assert session.query(CreatorProfile).count() == 1
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.status is JobStatus.SUCCEEDED
        assert job.profile_id == first_profile_id


def test_no_session_spans_external_calls(committed_factory) -> None:
    active = 0

    @contextmanager
    def tracked_factory():
        nonlocal active
        with committed_factory() as session:
            active += 1
            try:
                yield session
            finally:
                active -= 1

    class ObservingYouTube(YouTube):
        def fetch_creator(self, channel_id: str, video_limit: int = 50):
            assert active == 0
            return super().fetch_creator(channel_id, video_limit)

    class ObservingArtifacts(Artifacts):
        def put_json(self, job_id: UUID, name: str, payload: object) -> str:
            assert active == 0
            return super().put_json(job_id, name, payload)

    job_id = _job(committed_factory)
    pipeline = CreatorAnalysisPipeline(
        service=CreatorAnalysisService(
            session_factory=tracked_factory, clock=lambda: NOW
        ),
        youtube=ObservingYouTube(),
        artifacts=ObservingArtifacts(),
        public_pages=FakePages(
            {
                "https://creator.example/about": Page(
                    "https://creator.example/about", "hi"
                )
            }
        ),
        deepseek=AI(),
    )
    pipeline.run(job_id)
    assert active == 0


def test_clock_and_current_interval_are_validated(committed_factory) -> None:
    job_id = _job(committed_factory)
    with pytest.raises(PermanentIntegrationError, match="analysis_clock_invalid"):
        _pipeline(committed_factory, clock=lambda: datetime(2026, 9, 2, 9, 15)).run(
            job_id
        )

    class Indeterminate(tzinfo):
        def utcoffset(self, value):
            return None

        def dst(self, value):
            return None

    with pytest.raises(PermanentIntegrationError, match="analysis_clock_invalid"):
        _pipeline(
            committed_factory,
            clock=lambda: datetime(2026, 9, 2, 9, 15, tzinfo=Indeterminate()),
        ).run(job_id)


def test_public_json_has_no_raw_artifacts_or_secret_material(committed_factory) -> None:
    job_id = _job(committed_factory)
    profile_id = _pipeline(committed_factory).run(job_id)
    with committed_factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile is not None
        rendered = str(
            {
                "facts": profile.current_facts,
                "analysis": profile.analysis,
                "brief": profile.brief,
                "status": profile.source_status,
                "models": profile.model_metadata,
                "prompts": profile.prompt_metadata,
            }
        ).casefold()
        assert "raw-secret-canary" not in rendered
        assert "acquisition/" not in rendered
        assert "authorization" not in rendered
        assert "private-video-canary" not in rendered
