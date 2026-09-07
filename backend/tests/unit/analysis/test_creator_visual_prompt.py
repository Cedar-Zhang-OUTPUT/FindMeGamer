"""Creator visual prompts must agree with the unchanged strict output contract."""

from copy import deepcopy

from app.analysis.prompts.creator import (
    CREATOR_VISUAL_PROMPT_VERSION,
    build_creator_visual_bundle,
)
from app.schemas.ai_creator import CreatorVisualAnalysis
from app.schemas.ai_game import validate_stage_evidence

from .test_prompts import available_creator_visual, sample_creator_source


def test_every_advertised_creator_visual_evidence_kind_passes_its_schema() -> None:
    bundle = build_creator_visual_bundle(sample_creator_source())
    original = available_creator_visual().model_dump(mode="json")

    for entry in bundle.evidence_catalog.entries:
        for kind in entry.allowed_kinds:
            payload = deepcopy(original)
            payload["visual_style"]["evidence"] = [
                {
                    "kind": kind,
                    "source_type": entry.source_type,
                    "reference": entry.reference,
                    "observation": "Visible high-contrast thumbnail artwork.",
                }
            ]
            output = CreatorVisualAnalysis.model_validate(payload)
            validate_stage_evidence(output, bundle.evidence_catalog)


def test_creator_visual_rules_explain_cross_field_and_text_requirements() -> None:
    bundle = build_creator_visual_bundle(sample_creator_source())
    rules = bundle.messages[0].content

    assert CREATOR_VISUAL_PROMPT_VERSION == "creator-visual-v2"
    assert "Use kind=visual_observation and source_type=visual_asset" in rules
    assert "Never use ai_inference or source_fact in this visual-stage output." in rules
    assert (
        "If any visual claim is available, set status=available and unavailable_reason=null."
        in rules
    )
    assert "Individual unsupported claims must remain unavailable" in rules
    assert "If no claim can be supported, set status=unavailable" in rules
    assert "make every visual claim unavailable with a reason" in rules
    assert "Never force a claim to available." in rules
    assert (
        "Trim all generated text; do not return blank or whitespace-only values."
        in rules
    )


def test_creator_visual_catalog_matches_the_exact_images_and_contains_no_inference() -> (
    None
):
    bundle = build_creator_visual_bundle(sample_creator_source())

    assert len(bundle.assets) == len(bundle.image_urls) > 0
    assert [entry.reference for entry in bundle.evidence_catalog.entries] == [
        asset.asset_ref for asset in bundle.assets
    ]
    assert all(
        entry.allowed_kinds == ("visual_observation",)
        for entry in bundle.evidence_catalog.entries
    )
