from sqlalchemy import select
from app.core.idempotency import utc_now
from app.db.models.creator_search import CreatorSearch, CreatorSearchUnit
from app.db.models.discovery import DiscoveryCandidate
from app.db.models.profiles import CreatorProfile, CreatorContact
from app.schemas.ai_creator import EmailContactCandidate
from tests.integration.test_creator_search_worker import seeded_search
from tests.integration.test_discovery_evaluation import sessions_for


def seed_unit(client, session, monkeypatch):
    identity = seeded_search(client, session, monkeypatch, count=1)
    task = session.get(CreatorSearch, identity)
    candidate = session.scalar(
        select(DiscoveryCandidate).where(DiscoveryCandidate.query_id == task.query_id)
    )
    unit = CreatorSearchUnit(
        search_id=identity,
        candidate_id=candidate.id,
        creator_id=candidate.creator_id,
        platform=candidate.platform,
        account_id=candidate.account_id,
        identity_revision=candidate.identity_revision,
        ordinal=0,
    )
    session.add(unit)
    session.commit()
    return unit, session.get(CreatorProfile, unit.creator_id)


def test_existing_real_profile_reused_without_analysis_job(
    auth_client, session, monkeypatch
):
    from app.workers.creator_search_enrichment import enrich_profile

    unit, profile = seed_unit(auth_client, session, monkeypatch)
    profile.analysis = {"summary": "Real prior analysis"}
    profile.last_analyzed_at = utc_now()
    session.commit()
    assert enrich_profile(unit.id, session_factory=sessions_for(session)) == "reused"
    assert unit.analysis_job_id is None


def test_email_enrichment_keeps_multiple_purposes_and_respects_deleted_address(
    auth_client, session, monkeypatch
):
    from app.workers.creator_search_enrichment import enrich_email

    unit, profile = seed_unit(auth_client, session, monkeypatch)
    deleted = CreatorContact(
        creator_id=profile.id,
        email="removed@example.org",
        source_type="manual",
        is_manual=True,
        is_active=False,
        identity_revision=profile.identity_revision,
    )
    session.add(deleted)
    session.commit()
    calls = []

    def discover(source):
        calls.append(source)
        return tuple(
            EmailContactCandidate(
                candidate_id=f"contact.email.{i}",
                kind="email",
                value=email,
                purpose=purpose,
                source_type="public_web_research",
                source_url="https://example.org/contact",
                validation_state="unvalidated",
            )
            for i, (email, purpose) in enumerate(
                [
                    ("removed@example.org", "Deleted"),
                    ("business@example.org", "Business"),
                    ("press@example.org", "Press"),
                ]
            )
        )

    kwargs = dict(session_factory=sessions_for(session), discover=discover)
    assert enrich_email(unit.id, **kwargs) == "available"
    assert enrich_email(unit.id, **kwargs) == "available"
    assert len(calls) == 1
    session.refresh(deleted)
    assert not deleted.is_active
    active = list(
        session.scalars(
            select(CreatorContact).where(
                CreatorContact.creator_id == profile.id,
                CreatorContact.is_active.is_(True),
            )
        )
    )
    assert {(c.email, c.purpose) for c in active} == {
        ("business@example.org", "Business"),
        ("press@example.org", "Press"),
    }


def test_x_contact_projection_prompt_does_not_claim_youtube(
    auth_client, session, monkeypatch
):
    from app.workers.creator_search_enrichment import _source
    from app.integrations.gemini_email import _request_payload
    import json

    unit, profile = seed_unit(auth_client, session, monkeypatch)
    payload = json.dumps(_request_payload(_source(profile), existing_contacts=()))
    assert "Platform: X" in payload
    assert "Platform: YouTube" not in payload


def test_metadata_seed_runs_real_analysis_pipeline_and_reuses_its_public_email(
    auth_client, session, monkeypatch
):
    from contextlib import contextmanager
    import httpx
    from sqlalchemy.orm import sessionmaker
    from app.integrations.x_creator import XCreatorGateway
    from app.workers.analysis_tasks import AnalysisJobExecutor
    from app.workers.creator_search_enrichment import enrich_profile, enrich_email
    from tests.integration.test_x_analysis_pipeline import make_pipeline, SourceAI
    from tests.unit.integrations.test_x_creator import user_payload, posts_payload

    unit, profile = seed_unit(auth_client, session, monkeypatch)
    unit_id, account_id = unit.id, unit.account_id
    session.commit()
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

    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/tweets"):
            payload = posts_payload()
            payload["data"][0]["author_id"] = account_id
        else:
            payload = user_payload()
            payload["data"]["id"] = account_id
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with XCreatorGateway(
            bearer_token="fixture-only", http_client=client
        ) as gateway:
            pipeline = make_pipeline(sessions, gateway, SourceAI())

            @contextmanager
            def x_factory():
                yield pipeline

            executor = AnalysisJobExecutor(
                session_factory=sessions,
                pipeline_factory=lambda target: None,
                x_pipeline_factory=x_factory,
            )
            assert (
                enrich_profile(unit_id, session_factory=sessions, executor=executor)
                == "ready"
            )
            assert (
                enrich_profile(unit_id, session_factory=sessions, executor=executor)
                == "ready"
            )

    def no_research(source):
        raise AssertionError(
            "A valid existing public email must not trigger paid research"
        )

    assert (
        enrich_email(unit_id, session_factory=sessions, discover=no_research)
        == "available"
    )
    assert len(calls) == 2
