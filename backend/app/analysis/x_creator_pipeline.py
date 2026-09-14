"""Checkpointed X analysis publishing through the common Creator transaction."""

from pydantic import BaseModel

from app.analysis.contracts import XCreatorSource
from app.analysis.creator_pipeline import (
    CreatorAnalysisPipeline,
    _discover_creator_contacts_with_research,
    unavailable_visual_analysis,
)
from app.analysis.creator_metrics import compute_creator_metrics
from app.analysis.prompts.x_creator import build_x_creator_bundle
from app.analysis.service import CreatorAnalysisPublication
from app.integrations.errors import PermanentIntegrationError
from app.schemas.ai_creator import (
    CreatorContactEvidence,
    CreatorMetadataAnalysis,
    CreatorSynthesis,
    bind_creator_contacts,
)
from app.schemas.ai_game import UnavailableClaim


class XContactsCheckpoint(BaseModel):
    evidence: CreatorContactEvidence
    status: str


class XCreatorAnalysisPipeline(CreatorAnalysisPipeline):
    def __init__(
        self,
        *,
        service,
        x,
        artifacts,
        public_pages,
        deepseek,
        email_research=None,
        checkpoints=None,
    ):
        self._service = service
        self._x = x
        self._artifacts = artifacts
        self._public_pages = public_pages
        self._deepseek = deepseek
        self._email_research = email_research
        self._checkpoints = checkpoints

    def _node(self, job_id, key, schema, produce):
        cached = (
            self._checkpoints.load(job_id, key, schema) if self._checkpoints else None
        )
        if cached is not None:
            return cached
        output = produce()
        return (
            self._checkpoints.save_success(job_id, key, output)
            if self._checkpoints
            else output
        )

    def run(self, job_id):
        lease = self._service.start(job_id)
        if lease.completed_profile_id is not None:
            return lease.completed_profile_id
        if not lease.channel_id.startswith("x:"):
            raise PermanentIntegrationError("x_target_invalid")

        def fetch():
            source = self._x.fetch_creator(lease.channel_id[2:])
            if (
                f"x:{source.platform_account_id}" != lease.channel_id
                or source.canonical_url != lease.canonical_url
            ):
                raise PermanentIntegrationError("x_source_identity_mismatch")
            self._artifacts.put_json(job_id, "x-account.json", source.raw_account)
            self._artifacts.put_json(job_id, "x-posts.json", source.raw_posts)
            return source

        source = self._node(job_id, "x:source:v1", XCreatorSource, fetch)
        self._service.advance(job_id, completed_units=2)
        bundle = build_x_creator_bundle(source)
        metadata = self._node(
            job_id,
            "x:metadata:v1",
            CreatorMetadataAnalysis,
            lambda: self._structured_with_semantic_retry(
                model="deepseek-flash",
                messages=list(bundle.messages),
                schema=CreatorMetadataAnalysis,
                catalog=bundle.evidence_catalog,
            ),
        )

        def discover():
            evidence, status = _discover_creator_contacts_with_research(
                source, pages=self._public_pages, email_research=self._email_research
            )
            return XContactsCheckpoint(evidence=evidence, status=status)

        contacts = self._node(job_id, "x:contacts:v1", XContactsCheckpoint, discover)
        bundle = build_x_creator_bundle(
            source, contacts=contacts.evidence, metadata=metadata
        )
        synthesis = self._node(
            job_id,
            "x:synthesis:v1",
            CreatorSynthesis,
            lambda: self._synthesis_with_binding_retry(
                messages=list(bundle.messages),
                catalog=bundle.evidence_catalog,
                evidence=contacts.evidence,
            )[0],
        )
        unavailable = UnavailableClaim(
            status="unavailable",
            reason="No video or visual evidence was supplied for this X account.",
        )
        synthesis = synthesis.model_copy(
            update={
                key: unavailable
                for key in (
                    "representative_video_context",
                    "production_quality",
                    "livestream_tendency",
                    "long_form_tendency",
                    "short_form_tendency",
                )
            }
        )
        self._service.advance(job_id, completed_units=4)
        return self._service.finalize(
            lease,
            CreatorAnalysisPublication(
                source=source,
                synthesis=synthesis,
                visual=unavailable_visual_analysis(unavailable.reason),
                contacts=bind_creator_contacts(synthesis, contacts.evidence),
                contact_evidence=contacts.evidence,
                contact_status=contacts.status,
                metrics=compute_creator_metrics(()),
                representative_videos=(),
            ),
        )
