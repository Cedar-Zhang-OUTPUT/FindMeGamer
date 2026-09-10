"""Reuse existing analysis and public-contact discovery, never send email."""

from contextlib import ExitStack

from sqlalchemy import select

from app.analysis.contracts import CreatorSource
from app.analysis.targets import canonicalize_target
from app.core.database import session_scope
from app.db.models.creator_search import CreatorSearchUnit
from app.db.models.enums import TargetType, JobStatus
from app.db.models.jobs import AnalysisJob, CreatorAnalysisNode, acquire_job_change_lock
from app.db.models.profiles import CreatorProfile, CreatorContact
from app.repositories.jobs import JobsRepository
from app.workers.creator_search_tasks import SearchFailure


def _profile(session, unit):
    profile = session.get(CreatorProfile, unit.creator_id)
    if not profile or (
        profile.platform,
        profile.platform_account_id or profile.youtube_channel_id,
        profile.identity_revision,
    ) != (unit.platform, unit.account_id, unit.identity_revision):
        raise SearchFailure("search_identity_changed")
    return profile


def _usable(profile):
    return bool(profile.last_analyzed_at and profile.analysis)


def enrich_profile(unit_id, *, session_factory=session_scope, executor=None):
    with session_factory() as session:
        acquire_job_change_lock(session)
        unit = session.get(CreatorSearchUnit, unit_id)
        profile = _profile(session, unit)
        if _usable(profile):
            return "ready" if unit.analysis_job_id else "reused"
        if unit.platform not in {"youtube", "x"}:
            raise SearchFailure("search_platform_unavailable")
        job = (
            session.get(AnalysisJob, unit.analysis_job_id)
            if unit.analysis_job_id
            else None
        )
        if job and job.status == JobStatus.SUCCEEDED:
            raise SearchFailure("search_profile_unusable")
        if job and job.status == JobStatus.RUNNING:
            # Another analysis may still be executing. Never replay its paid calls.
            raise SearchFailure("search_profile_busy")
        url = (
            f"https://x.com/i/user/{unit.account_id}"
            if unit.platform == "x"
            else f"https://www.youtube.com/channel/{unit.account_id}"
        )
        target = canonicalize_target(TargetType.CREATOR, url)
        if job is None or job.status == JobStatus.FAILED:
            result = JobsRepository(session).create_creator_seed_job(
                target, correlation_id=f"creator-search:{unit.search_id}"
            )
            job = result.job
            unit.analysis_job_id, unit.owns_analysis_job = job.id, result.created
        if not unit.owns_analysis_job:
            # Existing queued/running Library job owns execution; retry reconciles it.
            raise SearchFailure("search_profile_busy")
        job_id = job.id
    from app.workers.analysis_tasks import get_analysis_executor, _failure_for

    executor = executor or get_analysis_executor()
    try:
        executor.execute(job_id)
    except Exception as error:
        executor.fail(job_id, _failure_for(getattr(error, "code", None)))
        raise SearchFailure("search_profile_failed") from None
    with session_factory() as session:
        unit = session.get(CreatorSearchUnit, unit_id)
        profile = _profile(session, unit)
        job = session.get(AnalysisJob, job_id)
        if job.status != JobStatus.SUCCEEDED or not _usable(profile):
            raise SearchFailure("search_profile_failed")
    return "ready"


def _has_email(profile):
    return any(
        c.is_active
        and c.identity_revision == profile.identity_revision
        and c.validation_state
        in {"valid", "validated", "verified", "unverified", "unvalidated"}
        for c in profile.contacts
    )


def _source(profile):
    # Contact-only projection: no invented videos, counts, or analysis evidence.
    facts = profile.current_facts or {}
    return CreatorSource(
        channel_id=profile.platform_account_id or profile.youtube_channel_id,
        canonical_url=profile.canonical_url,
        title=profile.sort_name,
        description=str(facts.get("description") or facts.get("bio") or ""),
        uploads_playlist_id="",
        videos=(),
        raw_channel={},
        raw_playlist_pages=(),
        raw_video_responses=(),
    )


def discover_emails(source, *, session_factory=session_scope):
    from app.analysis.creator_pipeline import _discover_creator_contacts_with_research
    from app.analysis.runtime import ProductionSecretProvider
    from app.core.config import get_settings
    from app.core.crypto import SecretCipher
    from app.integrations.gemini_email import GeminiEmailResearchGateway
    from app.integrations.public_pages import PublicPageGateway

    settings = get_settings()
    secrets = ProductionSecretProvider(
        session_factory=session_factory,
        cipher_factory=lambda: SecretCipher.from_file(settings.master_key_file),
    )
    key = secrets.load_optional("google_ai")
    with ExitStack() as stack:
        research = (
            stack.enter_context(
                GeminiEmailResearchGateway(
                    api_key=key, base_url=settings.google_ai_api_base_url
                )
            )
            if key
            else None
        )
        evidence, status = _discover_creator_contacts_with_research(
            source, pages=PublicPageGateway(), email_research=research
        )
        if not any(c.kind == "email" for c in evidence.candidates) and not key:
            raise SearchFailure("search_email_configuration_missing")
        return tuple(c for c in evidence.candidates if c.kind == "email")


def enrich_email(unit_id, *, session_factory=session_scope, discover=None):
    contacts = None
    with session_factory() as session:
        unit = session.get(CreatorSearchUnit, unit_id)
        profile = _profile(session, unit)
        if _has_email(profile):
            return "available"
        # Fresh YouTube analysis has already performed the same public-web lookup.
        if unit.platform == "youtube" and unit.analysis_job_id:
            job = session.get(AnalysisJob, unit.analysis_job_id)
            checkpoint = session.get(
                CreatorAnalysisNode, (unit.analysis_job_id, "contact:v2")
            )
            if job and job.status == JobStatus.SUCCEEDED and checkpoint:
                from app.analysis.creator_map_reduce_pipeline import (
                    CreatorContactCheckpoint,
                )

                saved = CreatorContactCheckpoint.model_validate(
                    checkpoint.output_payload
                )
                contacts = tuple(
                    c for c in saved.evidence.candidates if c.kind == "email"
                )
                if not contacts:
                    # Without configured research, a direct-page miss is incomplete.
                    from app.repositories.settings import SettingsRepository

                    if SettingsRepository(session).get_connection("google_ai") is None:
                        raise SearchFailure("search_email_configuration_missing")
        source = _source(profile)
    discover = discover or (
        lambda value: discover_emails(value, session_factory=session_factory)
    )
    if contacts is None:
        contacts = discover(source)
    with session_factory() as session:
        acquire_job_change_lock(session)
        unit = session.get(CreatorSearchUnit, unit_id)
        profile = _profile(session, unit)
        # Include inactive records: a colleague's deletion is not undone by enrichment.
        existing = {
            c.email.casefold()
            for c in profile.contacts
            if c.identity_revision == profile.identity_revision
        }
        for contact in contacts:
            if contact.value.casefold() in existing:
                continue
            session.add(
                CreatorContact(
                    creator_id=profile.id,
                    email=contact.value,
                    identity_revision=profile.identity_revision,
                    purpose=contact.purpose,
                    source_type=(
                        "public_profile"
                        if unit.platform == "x"
                        and contact.source_type == "channel_description"
                        else contact.source_type
                    ),
                    source_url=contact.source_url,
                    validation_state=(
                        "valid"
                        if contact.validation_state == "validated"
                        else "unverified"
                    ),
                    source_fields={
                        "email": contact.value,
                        "purpose": contact.purpose,
                        "source_url": contact.source_url,
                        "is_active": True,
                        "validation_state": (
                            "valid"
                            if contact.validation_state == "validated"
                            else "unverified"
                        ),
                    },
                    is_manual=False,
                    is_active=True,
                )
            )
            existing.add(contact.value.casefold())
        session.flush()
        session.expire(profile, ["contacts"])
        return "available" if _has_email(profile) else "missing"
