from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.analysis.contracts import CreatorSource, VideoSource
from app.analysis.creator_pipeline import (
    METADATA_MODEL,
    SYNTHESIS_MODEL,
    VISION_MODEL,
    CreatorAnalysisPipeline,
    build_creator_contact_evidence,
)
from app.analysis.prompts.common import PromptBundle, render_vision_prompt
from app.analysis.prompts.creator import (
    build_creator_metadata_bundle,
    build_creator_synthesis_bundle,
    build_creator_visual_bundle,
)
from app.analysis.service import CreatorAnalysisPublication, CreatorJobLease
from app.integrations.errors import (
    InvalidModelOutput,
    PermanentIntegrationError,
    TransientIntegrationError,
)
from app.schemas.ai_creator import (
    BoundCreatorContacts,
    CreatorContactEvidence,
    CreatorMetadataAnalysis,
    CreatorSynthesis,
    CreatorVisualAnalysis,
)
from app.schemas.ai_game import EvidenceCatalog

from .test_ai_schemas import (
    creator_metadata_unavailable_payload,
    creator_synthesis_payload,
    creator_visual_unavailable_payload,
)
from .test_prompts import sample_creator_source


@dataclass(frozen=True)
class Page:
    url: str
    text: str
    content_type: str = "text/html"


@dataclass(frozen=True)
class EmailResearchRecord:
    email: str
    usage: str
    source: str


class FakeEmailResearch:
    def __init__(
        self,
        result: tuple[EmailResearchRecord, ...] | BaseException = (),
    ) -> None:
        self.result = result
        self.calls: list[tuple[CreatorSource, tuple[str, ...]]] = []

    def find_public_emails(
        self,
        source: CreatorSource,
        *,
        existing_contacts: tuple[str, ...] = (),
    ) -> tuple[EmailResearchRecord, ...]:
        self.calls.append((source, existing_contacts))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class FakePages:
    def __init__(self, pages: dict[str, Page | BaseException] | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[str] = []

    def fetch_page(self, url: str) -> Page:
        self.calls.append(url)
        value = self.pages[url]
        if isinstance(value, BaseException):
            raise value
        return value


class FakeService:
    def __init__(self, completed_profile_id: UUID | None = None) -> None:
        self.job_id = uuid4()
        self.profile_id = completed_profile_id or uuid4()
        self.completed_profile_id = completed_profile_id
        self.active = False
        self.events: list[tuple[object, ...]] = []
        self.publication: CreatorAnalysisPublication | None = None

    def start(self, job_id: UUID) -> CreatorJobLease:
        self.active = True
        try:
            self.events.append(("start", job_id))
            return CreatorJobLease(
                job_id=job_id,
                channel_id="UCcreator123",
                canonical_url="https://www.youtube.com/channel/UCcreator123",
                completed_profile_id=self.completed_profile_id,
            )
        finally:
            self.active = False

    def advance(self, job_id: UUID, *, completed_units: int) -> None:
        self.active = True
        try:
            self.events.append(("advance", job_id, completed_units))
        finally:
            self.active = False

    def finalize(
        self, lease: CreatorJobLease, publication: CreatorAnalysisPublication
    ) -> UUID:
        self.active = True
        try:
            self.events.append(("finalize", lease.job_id))
            self.publication = publication
            return self.profile_id
        finally:
            self.active = False


class FakeYouTube:
    def __init__(self, source: CreatorSource, service: FakeService) -> None:
        self.source = source
        self.service = service
        self.calls: list[tuple[str, int]] = []

    def fetch_creator(self, channel_id: str, video_limit: int = 50) -> CreatorSource:
        assert not self.service.active
        self.calls.append((channel_id, video_limit))
        return self.source


class FakeArtifacts:
    def __init__(self, service: FakeService) -> None:
        self.service = service
        self.calls: list[tuple[UUID, str, object]] = []

    def put_json(self, job_id: UUID, name: str, payload: object) -> str:
        assert not self.service.active
        self.calls.append((job_id, name, payload))
        return f"acquisition/{job_id}/{name}"


class FakeAI:
    def __init__(
        self,
        service: FakeService,
        *,
        structured: list[object],
        vision: list[object] | None = None,
    ) -> None:
        self.service = service
        self.structured = list(structured)
        self.vision = list(vision or [])
        self.structured_calls: list[tuple[str, list, type]] = []
        self.vision_calls: list[tuple[str, str, list[str], type]] = []

    def complete_structured(self, model: str, messages: list, schema: type):
        assert not self.service.active
        self.structured_calls.append((model, messages, schema))
        value = self.structured.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def complete_vision(self, model: str, prompt: str, image_urls: list, schema: type):
        assert not self.service.active
        self.vision_calls.append((model, prompt, image_urls, schema))
        value = self.vision.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def _metadata() -> CreatorMetadataAnalysis:
    return CreatorMetadataAnalysis.model_validate(
        creator_metadata_unavailable_payload()
    )


def _visual() -> CreatorVisualAnalysis:
    return CreatorVisualAnalysis.model_validate(creator_visual_unavailable_payload())


def _synthesis(*, contacts: bool = True) -> CreatorSynthesis:
    payload = creator_synthesis_payload()
    if not contacts:
        payload["public_email"] = {"status": "unavailable", "reason": "Not found."}
        payload["linked_site"] = {"status": "unavailable", "reason": "Not found."}
        payload["social_links"] = {"status": "unavailable", "reason": "Not found."}
    return CreatorSynthesis.model_validate(payload)


def _source() -> CreatorSource:
    base = sample_creator_source()
    return base.model_copy(
        update={
            "channel_id": "UCcreator123",
            "canonical_url": "https://www.youtube.com/channel/UCcreator123",
            "description": (
                "Business: press@example.com. Website: "
                "https://creator.example/about and https://social.example/creator"
            ),
            "videos": (
                base.videos[0].model_copy(
                    update={
                        "channel_id": "UCcreator123",
                        "thumbnail_urls": ("https://cdn.example/video-1.jpg",),
                    }
                ),
            ),
        }
    )


def _pipeline(
    *,
    source: CreatorSource | None = None,
    structured: list[object] | None = None,
    vision: list[object] | None = None,
    pages: FakePages | None = None,
    email_research: FakeEmailResearch | None = None,
    completed_profile_id: UUID | None = None,
):
    service = FakeService(completed_profile_id)
    source = source or _source()
    youtube = FakeYouTube(source, service)
    artifacts = FakeArtifacts(service)
    page_gateway = pages or FakePages(
        {
            "https://creator.example/about": Page(
                "https://creator.example/about",
                "Email partnerships@example.com and https://social.example/creator",
            )
        }
    )
    ai = FakeAI(
        service,
        structured=structured or [_metadata(), _synthesis()],
        vision=vision or [_visual()],
    )
    pipeline = CreatorAnalysisPipeline(
        service=service,
        youtube=youtube,
        artifacts=artifacts,
        public_pages=page_gateway,
        deepseek=ai,
        email_research=email_research,
    )
    return pipeline, service, youtube, artifacts, page_gateway, ai


def test_existing_email_never_calls_public_web_research() -> None:
    research = FakeEmailResearch(AssertionError("research must not be called"))
    pipeline, service, _, _, _, _ = _pipeline(email_research=research)

    pipeline.run(service.job_id)

    assert research.calls == []


def test_site_only_contact_calls_research_and_binds_first_enhanced_email() -> None:
    source = _source().model_copy(
        update={"description": "Website: https://creator.example/about"}
    )
    pages = FakePages(
        {
            "https://creator.example/about": Page(
                "https://creator.example/about", "No email is listed here."
            )
        }
    )
    research = FakeEmailResearch(
        (
            EmailResearchRecord(
                email="Agency@Example.com",
                usage="Business inquiries",
                source="https://agency.example/creator/contact",
            ),
        )
    )
    pipeline, service, _, _, _, ai = _pipeline(
        source=source,
        pages=pages,
        email_research=research,
        structured=[_metadata(), _synthesis(contacts=False)],
    )

    pipeline.run(service.job_id)

    assert len(research.calls) == 1
    assert research.calls[0][0] == source
    assert research.calls[0][1] == ("https://creator.example/about",)
    assert service.publication is not None
    candidates = service.publication.contact_evidence.candidates
    assert candidates[0].model_dump(mode="json") == {
        "candidate_id": "contact.email.0",
        "kind": "email",
        "value": "Agency@Example.com",
        "purpose": "Business inquiries",
        "source_type": "public_web_research",
        "source_url": "https://agency.example/creator/contact",
        "validation_state": "unvalidated",
    }
    assert service.publication.contacts.public_email == candidates[0]
    assert service.publication.contact_status == "available"
    assert "contact.email.0" in ai.structured_calls[-1][1][-1].content


def test_research_rejects_invalid_source_url_and_keeps_unavailable() -> None:
    source = _source().model_copy(update={"description": "No public contacts."})
    research = FakeEmailResearch(
        (
            EmailResearchRecord(
                email="creator@example.com",
                usage="Business inquiries",
                source="http://127.0.0.1/private",
            ),
        )
    )
    pipeline, service, _, _, _, _ = _pipeline(
        source=source,
        pages=FakePages({}),
        email_research=research,
        structured=[_metadata(), _synthesis(contacts=False)],
    )

    pipeline.run(service.job_id)

    assert service.publication is not None
    assert service.publication.contact_evidence.candidates == ()
    assert service.publication.contact_status == "unavailable"
    assert service.publication.contacts.public_email is None


def test_successful_empty_research_result_is_a_normal_unavailable_contact() -> None:
    source = _source().model_copy(update={"description": "No public contacts."})
    research = FakeEmailResearch(())
    pipeline, service, _, _, _, _ = _pipeline(
        source=source,
        pages=FakePages({}),
        email_research=research,
        structured=[_metadata(), _synthesis(contacts=False)],
    )

    pipeline.run(service.job_id)

    assert len(research.calls) == 1
    assert service.publication is not None
    assert service.publication.contact_evidence.candidates == ()
    assert service.publication.contact_status == "unavailable"


def test_research_emails_are_prioritized_deduplicated_and_bounded() -> None:
    urls = tuple(f"https://site{index}.example/about" for index in range(10))
    source = _source().model_copy(update={"description": " ".join(urls)})
    pages = FakePages({url: Page(url, "No email listed.") for url in urls[:5]})
    research = FakeEmailResearch(
        (
            EmailResearchRecord(
                email="First@Example.com",
                usage="Business",
                source="https://directory.example/first",
            ),
            EmailResearchRecord(
                email="first@example.com",
                usage="Duplicate",
                source="https://directory.example/duplicate",
            ),
            EmailResearchRecord(
                email="second@example.com",
                usage="Agency",
                source="https://directory.example/second",
            ),
        )
    )
    pipeline, service, _, _, _, _ = _pipeline(
        source=source,
        pages=pages,
        email_research=research,
        structured=[_metadata(), _synthesis(contacts=False)],
    )

    pipeline.run(service.job_id)

    assert service.publication is not None
    candidates = service.publication.contact_evidence.candidates
    assert len(candidates) == 10
    assert [candidate.kind for candidate in candidates[:2]] == ["email", "email"]
    assert [candidate.value for candidate in candidates[:2]] == [
        "First@Example.com",
        "second@example.com",
    ]
    assert [candidate.purpose for candidate in candidates[:2]] == [
        "Business",
        "Agency",
    ]


def test_pipeline_uses_exact_bundles_selected_thumbnails_and_raw_before_ai() -> None:
    pipeline, service, youtube, artifacts, pages, ai = _pipeline()

    assert pipeline.run(service.job_id) == service.profile_id

    source = _source()
    metadata = _metadata()
    visual = _visual()
    evidence = build_creator_contact_evidence(
        source,
        pages=FakePages(
            {
                "https://creator.example/about": Page(
                    "https://creator.example/about",
                    "Email partnerships@example.com and https://social.example/creator",
                )
            }
        ),
    )
    metadata_bundle = build_creator_metadata_bundle(source)
    visual_bundle = build_creator_visual_bundle(
        source, selected_asset_refs=("video:video-1:thumbnail:0",)
    )
    synthesis_bundle = build_creator_synthesis_bundle(
        source, metadata, visual, evidence
    )
    assert youtube.calls == [("UCcreator123", 50)]
    assert [call[1] for call in artifacts.calls] == [
        "youtube-channel.json",
        "youtube-playlist-pages.json",
        "youtube-video-responses.json",
    ]
    assert artifacts.calls[0][2] == source.raw_channel
    assert artifacts.calls[1][2] == {"pages": list(source.raw_playlist_pages)}
    assert artifacts.calls[2][2] == {"responses": list(source.raw_video_responses)}
    assert ai.structured_calls == [
        (METADATA_MODEL, list(metadata_bundle.messages), CreatorMetadataAnalysis),
        (SYNTHESIS_MODEL, list(synthesis_bundle.messages), CreatorSynthesis),
    ]
    assert ai.vision_calls == [
        (
            VISION_MODEL,
            render_vision_prompt(visual_bundle.messages),
            list(visual_bundle.image_urls),
            CreatorVisualAnalysis,
        )
    ]
    assert service.publication is not None
    assert service.publication.contact_evidence == evidence


def test_contact_evidence_is_deterministic_bounded_and_never_uses_video_descriptions() -> (
    None
):
    source = _source().model_copy(
        update={
            "description": (
                "MAIL Press@Example.com, press@example.com; "
                "https://creator.example/about https://social.example/Creator"
            ),
            "videos": (
                _source()
                .videos[0]
                .model_copy(update={"description": "private-video-canary@example.net"}),
            ),
        }
    )
    pages = FakePages(
        {
            "https://creator.example/about": Page(
                "https://creator.example/about",
                "partnerships@example.org https://social.example/Creator",
            )
        }
    )

    evidence = build_creator_contact_evidence(source, pages=pages)

    assert len(evidence.candidates) <= 10
    assert [candidate.candidate_id for candidate in evidence.candidates] == [
        "contact.email.0",
        "contact.site.0",
        "contact.social.0",
        "contact.email.1",
    ]
    rendered = evidence.model_dump_json()
    assert "private-video-canary" not in rendered
    assert pages.calls == ["https://creator.example/about"]


def test_contact_urls_are_canonically_deduplicated_before_page_fetch() -> None:
    source = _source().model_copy(
        update={
            "description": (
                "https://CREATOR.example:443/%7Eabout " "https://creator.example/~about"
            )
        }
    )
    pages = FakePages(
        {
            "https://CREATOR.example:443/%7Eabout": Page(
                "https://CREATOR.example:443/%7Eabout", "No contact."
            )
        }
    )

    evidence = build_creator_contact_evidence(source, pages=pages)

    sites = [
        candidate
        for candidate in evidence.candidates
        if candidate.kind == "linked_site"
    ]
    assert len(sites) == 1
    assert pages.calls == ["https://CREATOR.example:443/%7Eabout"]


@pytest.mark.parametrize(
    ("first", "wire_equivalent"),
    [
        (
            "https://creator.example/currency€",
            "https://creator.example/currency%E2%82%AC",
        ),
        (
            "https://creator.example/rates?currency=€",
            "https://creator.example/rates?currency=%E2%82%AC",
        ),
        (
            "https://creator.example/currency%E2%82%AC",
            "https://creator.example/currency€",
        ),
    ],
)
def test_raw_and_utf8_encoded_urls_share_one_first_seen_contact_candidate(
    first: str, wire_equivalent: str
) -> None:
    source = _source().model_copy(update={"description": f"{first} {wire_equivalent}"})
    pages = FakePages({first: Page(first, "No contact.")})

    evidence = build_creator_contact_evidence(source, pages=pages)

    sites = [
        candidate.value
        for candidate in evidence.candidates
        if candidate.kind == "linked_site"
    ]
    assert sites == [first]
    assert pages.calls == [first]


def test_percent_encoded_linked_urls_are_preserved_and_fetched_end_to_end() -> None:
    urls = (
        "https://creator.example/team%20contact",
        "https://creator.example/discount%25",
        "https://creator.example/currency%E2%82%AC",
        "https://creator.example/octet%FF",
    )
    source = _source().model_copy(update={"description": " ".join(urls)})
    pages = FakePages({url: Page(url, "No contact.") for url in urls})

    evidence = build_creator_contact_evidence(source, pages=pages)

    assert pages.calls == list(urls)
    assert [
        candidate.value
        for candidate in evidence.candidates
        if candidate.kind == "linked_site"
    ] == list(urls)


def test_idna_normalized_social_host_is_never_fetched_as_linked_page() -> None:
    source = _source().model_copy(
        update={"description": "https://ｙｏｕｔｕｂｅ.com/@creator"}
    )
    pages = FakePages({})

    evidence = build_creator_contact_evidence(source, pages=pages)

    assert pages.calls == []
    assert [candidate.kind for candidate in evidence.candidates] == ["social_link"]


def test_contact_page_integration_failure_is_nonfatal_and_bounded() -> None:
    links = " ".join(f"https://site{index}.example/about" for index in range(8))
    source = _source().model_copy(update={"description": links})
    pages = FakePages(
        {
            f"https://site{index}.example/about": TransientIntegrationError(
                "public_page_unavailable"
            )
            for index in range(5)
        }
    )

    evidence = build_creator_contact_evidence(source, pages=pages)

    assert len(pages.calls) == 5
    assert evidence.candidates


def test_no_contact_path_is_explicit_unavailable_and_never_calls_pages() -> None:
    source = _source().model_copy(update={"description": "A channel with no links."})
    pages = FakePages({})
    synthesis = _synthesis(contacts=False)
    pipeline, service, _, _, _, ai = _pipeline(
        source=source,
        pages=pages,
        structured=[_metadata(), synthesis],
    )

    pipeline.run(service.job_id)

    assert pages.calls == []
    assert service.publication is not None
    assert service.publication.contact_evidence.candidates == ()
    assert service.publication.contact_status == "unavailable"
    assert service.publication.contacts.public_email is None
    assert ai.structured_calls[-1][2] is CreatorSynthesis


def test_contact_failure_status_is_partial_without_exposing_error_detail() -> None:
    source = _source().model_copy(
        update={"description": ("press@example.com https://creator.example/about")}
    )
    pages = FakePages(
        {
            "https://creator.example/about": TransientIntegrationError(
                "private-upstream-detail"
            )
        }
    )

    payload = creator_synthesis_payload()
    payload["linked_site"] = {"status": "unavailable", "reason": "Not found."}
    payload["social_links"] = {"status": "unavailable", "reason": "Not found."}
    pipeline, service, _, _, _, _ = _pipeline(
        source=source,
        pages=pages,
        structured=[_metadata(), CreatorSynthesis.model_validate(payload)],
    )

    pipeline.run(service.job_id)

    assert service.publication is not None
    assert service.publication.contact_status == "partial"
    assert (
        "private-upstream-detail"
        not in service.publication.contact_evidence.model_dump_json()
    )


def test_metadata_and_synthesis_semantic_failures_get_one_clean_retry() -> None:
    bad_metadata_payload = creator_metadata_unavailable_payload()
    bad_metadata_payload["pacing"] = {
        "status": "available",
        "value": "Fast",
        "evidence": [
            {
                "kind": "source_fact",
                "source_type": "channel_field",
                "reference": "channel:not-present",
                "observation": "Invalid",
            }
        ],
        "confidence": "low",
    }
    bad_metadata = CreatorMetadataAnalysis.model_validate(bad_metadata_payload)
    pipeline, service, _, _, _, ai = _pipeline(
        structured=[bad_metadata, _metadata(), _synthesis()]
    )
    pipeline.run(service.job_id)
    assert ai.structured_calls[0][1] == ai.structured_calls[1][1]

    bad_synthesis_payload = deepcopy(creator_synthesis_payload())
    bad_synthesis_payload["content_summary"]["evidence"][0][
        "reference"
    ] = "channel:not-present"
    bad_synthesis = CreatorSynthesis.model_validate(bad_synthesis_payload)
    pipeline, service, _, _, _, ai = _pipeline(
        structured=[_metadata(), bad_synthesis, bad_synthesis]
    )
    with pytest.raises(InvalidModelOutput, match="deepseek_model_evidence_invalid"):
        pipeline.run(service.job_id)
    assert ai.structured_calls[-2][1] == ai.structured_calls[-1][1]
    assert service.publication is None


def test_contact_binding_failure_gets_one_clean_retry_then_safe_error() -> None:
    bad_payload = creator_synthesis_payload()
    bad_payload["public_email"] = {
        "status": "available",
        "candidate_id": "contact.email.fabricated",
    }
    bad = CreatorSynthesis.model_validate(bad_payload)
    pipeline, service, _, _, _, ai = _pipeline(structured=[_metadata(), bad, bad])

    with pytest.raises(InvalidModelOutput, match="deepseek_model_contacts_invalid"):
        pipeline.run(service.job_id)

    assert ai.structured_calls[-2][1] == ai.structured_calls[-1][1]
    assert service.publication is None


@pytest.mark.parametrize(
    "failure",
    [
        TransientIntegrationError("vision_unavailable"),
        PermanentIntegrationError("vision_rejected"),
        InvalidModelOutput("vision_invalid"),
    ],
)
def test_vision_typed_failures_retry_once_then_fall_back(
    failure: BaseException,
) -> None:
    pipeline, service, _, _, _, ai = _pipeline(vision=[failure, failure])
    pipeline.run(service.job_id)
    assert len(ai.vision_calls) == 2
    assert service.publication is not None
    assert service.publication.visual.status == "unavailable"


def test_invalid_or_empty_images_skip_vision_with_typed_unavailable() -> None:
    source = _source().model_copy(
        update={
            "videos": (
                _source()
                .videos[0]
                .model_copy(
                    update={"thumbnail_urls": ("https://cdn.example/dynamic",)}
                ),
            )
        }
    )
    pipeline, service, _, _, _, ai = _pipeline(source=source, vision=[])
    pipeline.run(service.job_id)
    assert ai.vision_calls == []
    assert service.publication is not None
    assert service.publication.visual.status == "unavailable"


@pytest.mark.parametrize("failure", [ValueError("programmer"), KeyboardInterrupt()])
def test_vision_programmer_and_process_failures_propagate(
    failure: BaseException,
) -> None:
    pipeline, service, _, _, _, ai = _pipeline(vision=[failure])
    with pytest.raises(type(failure)):
        pipeline.run(service.job_id)
    assert len(ai.vision_calls) == 1
    assert service.publication is None


def test_visual_bundle_unrelated_validation_error_propagates(monkeypatch) -> None:
    pipeline, service, _, _, _, ai = _pipeline()
    with pytest.raises(ValidationError) as captured:
        PromptBundle(messages=(), evidence_catalog=EvidenceCatalog(entries=()))

    def fail(source, *, selected_asset_refs):
        raise captured.value

    monkeypatch.setattr(
        "app.analysis.creator_pipeline.build_creator_visual_bundle", fail
    )
    with pytest.raises(ValidationError) as raised:
        pipeline.run(service.job_id)
    assert raised.value is captured.value
    assert ai.vision_calls == []


def test_identity_mismatch_and_succeeded_job_make_no_external_calls() -> None:
    mismatched = _source().model_copy(update={"channel_id": "UCdifferent123"})
    pipeline, service, _, artifacts, _, ai = _pipeline(source=mismatched)
    with pytest.raises(
        PermanentIntegrationError, match="youtube_source_identity_mismatch"
    ):
        pipeline.run(service.job_id)
    assert artifacts.calls == []
    assert ai.structured_calls == []

    completed = uuid4()
    pipeline, service, youtube, artifacts, pages, ai = _pipeline(
        completed_profile_id=completed
    )
    assert pipeline.run(service.job_id) == completed
    assert youtube.calls == []
    assert artifacts.calls == []
    assert pages.calls == []
    assert ai.structured_calls == []
