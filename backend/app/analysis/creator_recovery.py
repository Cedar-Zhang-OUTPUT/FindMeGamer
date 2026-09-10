"""Pure checkpoint planning shared by explicit, bounded Creator recovery."""

from datetime import timedelta

from app.analysis.creator_map_reduce_pipeline import (
    BATCH_NODE_PREFIX,
    BRIEF_NODE_KEY,
    CONTACT_NODE_KEY,
    REDUCTION_NODE_KEYS,
    SOURCE_NODE_KEY,
    VISUAL_NODE_KEY,
    CreatorContactCheckpoint,
    CreatorSourceCheckpoint,
)
from app.analysis.prompts.creator_map_reduce import (
    creator_video_batch_count,
    build_creator_video_batch_bundle,
    build_creator_content_format_bundle,
    build_creator_presentation_bundle,
    build_creator_performance_audience_bundle,
    build_creator_commercial_safety_bundle,
    build_creator_brief_bundle,
)
from app.analysis.creator_map_reduce import merge_creator_synthesis
from app.schemas.ai_creator import CreatorVisualAnalysis, bind_creator_contacts
from app.schemas.ai_creator_map_reduce import (
    CreatorBriefSynthesis,
    CreatorCommercialSafetyReduction,
    CreatorContentFormatReduction,
    CreatorPerformanceAudienceReduction,
    CreatorPresentationReduction,
    CreatorVideoBatchDigest,
)
from app.schemas.ai_game import validate_stage_evidence

RECOVERY_CORRELATION_PREFIX = "creator-search-resume:"


class CreatorRecoveryError(RuntimeError):
    """Stable safe code; never include persisted/provider content."""


def node_schemas(batch_count):
    return {
        SOURCE_NODE_KEY: CreatorSourceCheckpoint,
        VISUAL_NODE_KEY: CreatorVisualAnalysis,
        CONTACT_NODE_KEY: CreatorContactCheckpoint,
        BRIEF_NODE_KEY: CreatorBriefSynthesis,
        REDUCTION_NODE_KEYS["content_format"]: CreatorContentFormatReduction,
        REDUCTION_NODE_KEYS["presentation"]: CreatorPresentationReduction,
        REDUCTION_NODE_KEYS[
            "performance_audience"
        ]: CreatorPerformanceAudienceReduction,
        REDUCTION_NODE_KEYS["commercial_safety"]: CreatorCommercialSafetyReduction,
        **{
            f"{BATCH_NODE_PREFIX}{index:02d}": CreatorVideoBatchDigest
            for index in range(batch_count)
        },
    }


def validate_failed_checkpoints(nodes, *, channel_id, canonical_url, now):
    """Keep every valid success; missing source/acquisition never means refetch.

    Uses the same versioned schemas and evidence catalogs as normal execution.
    Model alias changes do not invalidate successful historical checkpoints.
    """
    if not {SOURCE_NODE_KEY, VISUAL_NODE_KEY, CONTACT_NODE_KEY} <= nodes.keys():
        raise CreatorRecoveryError("search_resume_checkpoint_missing")
    if not now - timedelta(days=30) <= nodes[SOURCE_NODE_KEY].created_at <= now:
        raise CreatorRecoveryError("search_resume_source_expired")
    try:
        source = CreatorSourceCheckpoint.model_validate(
            nodes[SOURCE_NODE_KEY].output_payload
        ).to_source()
        if source.channel_id != channel_id or source.canonical_url.rstrip(
            "/"
        ) != canonical_url.rstrip("/"):
            raise CreatorRecoveryError("search_identity_changed")
        count = creator_video_batch_count(source)
        schemas = node_schemas(count)
        if nodes.keys() - schemas.keys():
            raise CreatorRecoveryError("search_resume_checkpoint_invalid")
        outputs = {
            key: schemas[key].model_validate(node.output_payload)
            for key, node in nodes.items()
        }
        batch_keys = [f"{BATCH_NODE_PREFIX}{index:02d}" for index in range(count)]
        for index, key in enumerate(batch_keys):
            if key in outputs:
                validate_stage_evidence(
                    outputs[key],
                    build_creator_video_batch_bundle(
                        source, batch_index=index
                    ).evidence_catalog,
                )
        reductions = {
            name: outputs[key]
            for name, key in REDUCTION_NODE_KEYS.items()
            if key in outputs
        }
        if reductions:
            if not set(batch_keys) <= outputs.keys():
                raise CreatorRecoveryError("search_resume_checkpoint_invalid")
            digests = tuple(outputs[key] for key in batch_keys)
            builders = {
                "content_format": lambda: build_creator_content_format_bundle(digests),
                "presentation": lambda: build_creator_presentation_bundle(
                    digests, visual=outputs[VISUAL_NODE_KEY]
                ),
                "performance_audience": lambda: build_creator_performance_audience_bundle(
                    digests
                ),
                "commercial_safety": lambda: build_creator_commercial_safety_bundle(
                    digests
                ),
            }
            for name, output in reductions.items():
                validate_stage_evidence(output, builders[name]().evidence_catalog)
        if BRIEF_NODE_KEY in outputs:
            if len(reductions) != 4:
                raise CreatorRecoveryError("search_resume_checkpoint_invalid")
            contact = outputs[CONTACT_NODE_KEY].evidence
            bundle = build_creator_brief_bundle(**reductions, contact_evidence=contact)
            validate_stage_evidence(outputs[BRIEF_NODE_KEY], bundle.evidence_catalog)
            bind_creator_contacts(
                merge_creator_synthesis(**reductions, brief=outputs[BRIEF_NODE_KEY]),
                contact,
            )
    except (ValueError, TypeError, KeyError):
        raise CreatorRecoveryError("search_resume_checkpoint_invalid") from None
    return tuple(sorted(nodes))
