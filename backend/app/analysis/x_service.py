"""Atomic X source/analysis publication into the existing shared Creator UUID."""

from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

from app.analysis.creator_library_sync import _apply_contact
from app.analysis.creator_pipeline import _ordered_contacts
from app.analysis.service import CreatorAnalysisService, _require_valid_job_state
from app.analysis.targets import creator_account_id, creator_platform
from app.core.content_languages import known_content_languages
from app.db.models.enums import JobStatus, AnalysisStage
from app.db.models.jobs import AnalysisJob, acquire_job_change_lock
from app.db.models.profiles import CreatorContact
from app.db.models.settings import SharedSettings
from app.discovery.library import import_discovered_account
from app.integrations.errors import PermanentIntegrationError
from app.repositories.settings import SHARED_SETTINGS_ID


class XCreatorAnalysisService(CreatorAnalysisService):
    def __init__(self, *, session_factory, clock=None):
        super().__init__(session_factory=session_factory, clock=clock, platform="x")

    @staticmethod
    def _require_creator_job(job):
        CreatorAnalysisService._require_creator_job(job)
        if creator_platform(job.canonical_target_id) != "x":
            raise PermanentIntegrationError("analysis_job_target_invalid")

    def finalize(self, lease, source, signals):
        with self._session_factory() as session, session.begin():
            acquire_job_change_lock(session)
            job = session.scalar(
                select(AnalysisJob)
                .where(AnalysisJob.id == lease.job_id)
                .with_for_update()
            )
            if job is None:
                raise PermanentIntegrationError("analysis_job_not_found")
            self._require_creator_job(job)
            if (
                job.canonical_target_id != lease.channel_id
                or job.canonical_url != lease.canonical_url
            ):
                raise PermanentIntegrationError("analysis_job_identity_changed")
            if job.status is JobStatus.SUCCEEDED:
                return self._valid_succeeded_profile_id(session, job)
            if (
                job.status is not JobStatus.RUNNING
                or job.stage is not AnalysisStage.FINALIZING
            ):
                raise PermanentIntegrationError("analysis_job_state_invalid")
            if (
                source.account.platform != "x"
                or source.account.account_id != creator_account_id(lease.channel_id)
                or source.account.profile_url != lease.canonical_url
            ):
                raise PermanentIntegrationError("x_source_identity_mismatch")
            settings = session.scalar(
                select(SharedSettings)
                .where(SharedSettings.id == SHARED_SETTINGS_ID)
                .with_for_update()
            )
            if settings is None:
                raise PermanentIntegrationError("shared_settings_missing")
            interval = self._read_creator_interval(settings)
            profile = import_discovered_account(
                session, source.account, source.contents
            )
            if profile is None:
                raise PermanentIntegrationError("analysis_job_identity_changed")
            now = self._aware_now()
            profile.current_facts = {
                **profile.current_facts,
                "languages": known_content_languages(
                    item.language for item in source.contents
                ),
                "language_evidence": [
                    {
                        "language": item.language,
                        "source_url": item.source_url,
                        "source_field": "lang",
                    }
                    for item in source.contents
                    if known_content_languages([item.language])
                ],
            }
            profile.analysis = signals.model_dump(
                mode="json", exclude={"english_language_check"}
            )
            profile.brief = {
                name: profile.analysis[name]
                for name in (
                    "content_summary",
                    "promotion_fit",
                    "audience_inference",
                    "brand_safety",
                )
            }
            profile.source_status = {
                **profile.source_status,
                "x": "available",
                "freshness": "current",
                "coverage": source.coverage,
                "post_limit": source.post_limit,
                "sample_size": len(source.contents),
                "more_available": source.more_available,
                "excluded_post_types": ["retweets", "replies"],
                "visual_analysis": "not_performed",
                "sender_viewing_verified": False,
            }
            profile.model_metadata = {"analysis": "deepseek-flash"}
            profile.prompt_metadata = {"analysis": "x-creator-analysis-v1"}
            profile.last_analyzed_at = now
            profile.next_analysis_at = now + timedelta(days=interval)
            self._contacts(profile, source)
            session.flush()
            job.status = JobStatus.SUCCEEDED
            job.completed_units = job.total_units
            job.profile_id = profile.id
            job.result_payload = {"profile_id": str(profile.id)}
            job.completed_at = now
            job.error_code = job.error_message = None
            job.retryable = False
            _require_valid_job_state(job)
            session.flush()
            return profile.id

    @staticmethod
    def _contacts(profile, source):
        existing = {
            str(c.source_fields.get("email") or c.email).casefold(): c
            for c in profile.contacts
            if not c.is_manual and c.identity_revision == profile.identity_revision
        }
        sources = [(source.account.description or "", source.account.profile_url)] + [
            (c.text or "", c.source_url) for c in source.contents
        ]
        seen = set()
        for text, url in sources:
            for kind, value in _ordered_contacts(text):
                if kind != "email" or len(seen) >= 20:
                    continue
                try:
                    email = validate_email(value, check_deliverability=False).normalized
                except EmailNotValidError:
                    continue
                key = email.casefold()
                if key in seen:
                    continue
                seen.add(key)
                contact = existing.get(key)
                if contact is None:
                    contact = CreatorContact(
                        identity_revision=profile.identity_revision,
                        is_manual=False,
                        manual_overrides={},
                        source_type="x_public_content",
                    )
                    profile.contacts.append(contact)
                _apply_contact(
                    contact,
                    {
                        "email": email,
                        "purpose": None,
                        "source_url": url,
                        "validation_state": "valid",
                        "is_active": True,
                    },
                )
        for key, contact in existing.items():
            if key not in seen:
                _apply_contact(contact, {**contact.source_fields, "is_active": False})
