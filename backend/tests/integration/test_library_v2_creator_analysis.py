from copy import deepcopy

import pytest
from sqlalchemy import select

from app.db.models.profiles import CreatorContact, CreatorProfile, CreatorWork
from tests.integration.test_creator_analysis_commit import (
    committed_factory,
    _job,
    _pipeline,
    _profile,
    YouTube,
)
from app.integrations.errors import TransientIntegrationError
from tests.unit.analysis.test_creator_pipeline import _source


def test_refresh_preserves_manual_creator_and_stable_source_records(committed_factory):
    factory = committed_factory
    profile_id = _profile(factory)
    with factory.begin() as session:
        profile = session.get(CreatorProfile, profile_id)
        profile.manual_overrides = {
            "name": "Human name",
            "internal_notes": "Private note",
        }
        profile.manual_revision = 4
    assert _pipeline(factory).run(_job(factory)) == profile_id
    with factory.begin() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile.sort_name == "Human name"
        assert profile.platform_account_id == "UCcreator123"
        works = session.scalars(select(CreatorWork)).all()
        assert len(works) == len(_source().videos)
        ids = {work.source_content_id: work.id for work in works}
        work = works[0]
        work.manual_overrides = {"verification_notes": "Human verified excerpt"}
        work.revision = 2
        edited_work_id = work.id
        for work in works:
            assert work.source_fields["content_type"] == "unverified"
            assert work.source_fields["game_id"] is None
            assert work.source_fields["evidence_excerpt"] is None
            assert (
                work.source_fields["outreach_observation"]["evidence_kind"]
                == "metadata"
            )
            assert (
                work.source_fields["outreach_observation"]["source_url"]
                == work.source_fields["source_url"]
            )
        contact = session.scalar(
            select(CreatorContact).where(
                CreatorContact.email == "partnerships@example.org"
            )
        )
        contact_id = contact.id
        contact.manual_overrides = {
            "email": "custom@example.org",
            "purpose": "My purpose",
            "validation_state": "unverified",
            "is_active": False,
        }
        contact.email = "custom@example.org"
    assert _pipeline(factory).run(_job(factory)) == profile_id
    with factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile.manual_revision == 4
        assert profile.manual_overrides["internal_notes"] == "Private note"
        assert profile.sort_name == "Human name"
        works = session.scalars(select(CreatorWork)).all()
        assert {work.source_content_id: work.id for work in works} == ids
        work = session.get(CreatorWork, edited_work_id)
        assert work.manual_overrides == {"verification_notes": "Human verified excerpt"}
        assert work.revision == 2
        contact = session.get(CreatorContact, contact_id)
        assert contact.email == "custom@example.org"
        assert contact.purpose == "My purpose"
        assert contact.validation_state == "unverified"
        assert contact.is_active is False
        assert contact.source_fields["email"] == "partnerships@example.org"
        old = session.scalar(
            select(CreatorContact).where(CreatorContact.email == "old@example.net")
        )
        assert old is not None and old.is_active is False
        manual = session.scalar(
            select(CreatorContact).where(CreatorContact.email == "team@example.com")
        )
        assert manual.is_active is True and manual.is_manual is True


def test_refresh_does_not_reactivate_old_identity_contacts_or_replace_old_works(
    committed_factory,
):
    factory = committed_factory
    profile_id = _pipeline(factory).run(_job(factory))
    with factory.begin() as session:
        old_works = session.scalars(select(CreatorWork)).all()
        old_work_ids = {work.id for work in old_works}
        old_contacts = session.scalars(select(CreatorContact)).all()
        old_contact_ids = {contact.id for contact in old_contacts}
        for contact in old_contacts:
            contact.is_active = False
        profile = session.get(CreatorProfile, profile_id)
        profile.identity_revision = 1
    _pipeline(factory).run(_job(factory))
    with factory() as session:
        for contact_id in old_contact_ids:
            assert session.get(CreatorContact, contact_id).is_active is False
        contacts = session.scalars(
            select(CreatorContact).where(CreatorContact.identity_revision == 1)
        ).all()
        assert contacts and all(contact.is_active for contact in contacts)
        new_works = session.scalars(
            select(CreatorWork).where(CreatorWork.identity_revision == 1)
        ).all()
        assert new_works
        assert not old_work_ids.intersection(work.id for work in new_works)


def test_failed_refresh_keeps_existing_library_layers(committed_factory):
    factory = committed_factory
    profile_id = _pipeline(factory).run(_job(factory))
    with factory.begin() as session:
        profile = session.get(CreatorProfile, profile_id)
        profile.manual_overrides = {"name": "Human title"}
        old_facts = deepcopy(profile.current_facts)
        work = session.scalar(select(CreatorWork))
        work.manual_overrides = {"verification_notes": "My notes"}
        work_id = work.id
        old_work_source = deepcopy(work.source_fields)
        contact_ids = set(session.scalars(select(CreatorContact.id)).all())
    with pytest.raises(TransientIntegrationError):
        _pipeline(
            factory,
            youtube=YouTube(failure=TransientIntegrationError("youtube_unavailable")),
        ).run(_job(factory))
    with factory() as session:
        profile = session.get(CreatorProfile, profile_id)
        assert profile.current_facts == old_facts
        assert profile.manual_overrides == {"name": "Human title"}
        work = session.get(CreatorWork, work_id)
        assert work.source_fields == old_work_source
        assert work.manual_overrides == {"verification_notes": "My notes"}
        assert set(session.scalars(select(CreatorContact.id)).all()) == contact_ids


def test_refresh_keeps_known_unseen_and_manual_works(committed_factory):
    factory = committed_factory
    profile_id = _pipeline(factory).run(_job(factory))
    with factory.begin() as session:
        old_work = session.scalar(select(CreatorWork))
        old_work.source_content_id = "older-unseen-video"
        old_work_id = old_work.id
        old_fields = deepcopy(old_work.source_fields)
        manual = CreatorWork(
            creator_id=profile_id,
            platform="youtube",
            origin="manual",
            source_fields={},
            manual_overrides={
                "content_title": "Human record",
                "verification_notes": "Not independently collected",
            },
        )
        session.add(manual)
        session.flush()
        manual_id = manual.id
    _pipeline(factory).run(_job(factory))
    with factory() as session:
        assert session.get(CreatorWork, old_work_id).source_fields == old_fields
        manual = session.get(CreatorWork, manual_id)
        assert manual.origin == "manual"
        assert manual.source_fields == {}
        assert manual.source_collected_at is None
        assert manual.manual_overrides["content_title"] == "Human record"
        assert len(session.scalars(select(CreatorWork)).all()) == 3


def test_backfill_stored_work_facts_is_idempotent_and_preserves_human_layers(
    committed_factory,
):
    from app.outreach.prefill_backfill import backfill_prefill

    factory = committed_factory
    identity = _pipeline(factory).run(_job(factory))
    with factory.begin() as session:
        creator = session.get(CreatorProfile, identity)
        before = deepcopy(creator.current_facts)
        works = session.scalars(select(CreatorWork)).all()
        for work in works:
            work.source_fields = {
                key: value
                for key, value in work.source_fields.items()
                if key != "outreach_observation"
            }
            work.manual_overrides = {
                "content_title": "Human work title",
                "verification_notes": "Editor note",
            }
        count = len(works)
        assert backfill_prefill(session, apply=False)["works_to_update"] == count
        assert all("outreach_observation" not in work.source_fields for work in works)
        assert backfill_prefill(session, apply=True)["works_updated"] == count
        assert backfill_prefill(session, apply=True)["works_updated"] == 0
        assert creator.current_facts == before
        for work in works:
            assert work.manual_overrides == {
                "content_title": "Human work title",
                "verification_notes": "Editor note",
            }
            assert (
                work.source_fields["outreach_observation"]["evidence_kind"]
                == "metadata"
            )
            assert work.source_fields["evidence_excerpt"] is None


def test_backfill_uses_only_matching_successful_publication_checkpoint(
    committed_factory,
):
    from app.outreach.prefill_backfill import backfill_prefill
    from app.analysis.creator_map_reduce_pipeline import CreatorSourceCheckpoint
    from app.db.models.jobs import CreatorAnalysisNode

    factory = committed_factory
    job_id = _job(factory)
    profile_id = _pipeline(factory).run(job_id)
    source = _source()
    first = source.videos[0].model_copy(
        update={"description": "A public description of a quiet station"}
    )
    source = source.model_copy(update={"videos": (first, *source.videos[1:])})
    with factory.begin() as session:
        session.add(
            CreatorAnalysisNode(
                job_id=job_id,
                node_key="source:v1",
                output_payload=CreatorSourceCheckpoint.from_source(source).model_dump(
                    mode="json"
                ),
            )
        )
        work = session.scalar(
            select(CreatorWork).where(
                CreatorWork.creator_id == profile_id,
                CreatorWork.source_content_id == first.id,
            )
        )
        work.source_fields = {
            key: value
            for key, value in work.source_fields.items()
            if key != "outreach_observation"
        }
        report = backfill_prefill(session, apply=True)
        assert report["checkpoint_descriptions_used"] == 1
        assert (
            work.source_fields["outreach_observation"]["source_field"] == "description"
        )
        assert first.description in work.source_fields["outreach_observation"]["text"]
        assert work.source_fields["evidence_excerpt"] is None
