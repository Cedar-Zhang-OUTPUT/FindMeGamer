"""X account/post evidence rendered into the common Creator contract."""

from app.analysis.prompts.common import build_prompt_bundle, clip_text
from app.schemas.ai_game import EvidenceCatalog, EvidenceCatalogEntry

X_CREATOR_PROMPT_VERSION = "x-creator-v1"


def build_x_creator_bundle(source, *, contacts=None, metadata=None):
    curated = source.model_dump(mode="json", exclude={"raw_account", "raw_posts"})
    curated["description"] = clip_text(source.description, 4000)
    curated["posts"] = [
        dict(post.model_dump(mode="json"), text=clip_text(post.text, 1000))
        for post in source.posts[:50]
    ]
    catalog = EvidenceCatalog(
        entries=tuple(
            EvidenceCatalogEntry(
                reference=url,
                source_type="public_link",
                allowed_kinds=("source_fact", "ai_inference"),
            )
            for url in dict.fromkeys(
                [
                    source.canonical_url,
                    *(post.canonical_url for post in source.posts),
                    *((c.source_url for c in contacts.candidates) if contacts else ()),
                ]
            )
        )
    )
    return build_prompt_bundle(
        version=X_CREATOR_PROMPT_VERSION,
        stage_rules=(
            "Analyze this X creator using only supplied account facts and public posts. "
            "Return the common Creator analysis/Creator Brief schema. Cite exact public_link references from the catalog. "
            "No videos, thumbnails, audio or audience demographics were supplied. Mark representative_video_context, production_quality, livestream_tendency, long_form_tendency and short_form_tendency unavailable. "
            "Do not fabricate YouTube identity, video statistics, or visual observations. Audience statements must be cautious AI inference with confidence. "
            "Choose public contacts only by supplied candidate_id. Never invent addresses or evidence."
        ),
        label="X_SOURCE_UNTRUSTED_EVIDENCE",
        payload={
            "x_source": curated,
            "contact_evidence": contacts.model_dump(mode="json") if contacts else None,
            "metadata": metadata.model_dump(mode="json") if metadata else None,
            "evidence_catalog": catalog.model_dump(mode="json"),
        },
        evidence_catalog=catalog,
    )
