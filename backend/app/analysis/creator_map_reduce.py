"""Deterministic assembly for Creator Map-Reduce outputs."""

from app.schemas.ai_creator import CreatorSynthesis
from app.schemas.ai_creator_map_reduce import (
    CreatorBriefSynthesis,
    CreatorCommercialSafetyReduction,
    CreatorContentFormatReduction,
    CreatorPerformanceAudienceReduction,
    CreatorPresentationReduction,
)


def merge_creator_synthesis(
    *,
    content_format: CreatorContentFormatReduction,
    presentation: CreatorPresentationReduction,
    performance_audience: CreatorPerformanceAudienceReduction,
    commercial_safety: CreatorCommercialSafetyReduction,
    brief: CreatorBriefSynthesis,
) -> CreatorSynthesis:
    """Assemble the existing publication contract without a large model call."""

    values: tuple[tuple[object, type[object]], ...] = (
        (content_format, CreatorContentFormatReduction),
        (presentation, CreatorPresentationReduction),
        (performance_audience, CreatorPerformanceAudienceReduction),
        (commercial_safety, CreatorCommercialSafetyReduction),
        (brief, CreatorBriefSynthesis),
    )
    if any(not isinstance(value, expected) for value, expected in values):
        raise TypeError("Creator synthesis merge requires validated stage outputs")

    payload: dict[str, object] = {"english_language_check": True}
    for reduction in (
        content_format,
        presentation,
        performance_audience,
        commercial_safety,
    ):
        payload.update(
            reduction.model_dump(
                mode="json",
                exclude={"english_language_check"},
            )
        )
    payload.update(
        {
            "public_email": brief.public_email.model_dump(mode="json"),
            "linked_site": brief.linked_site.model_dump(mode="json"),
            "social_links": brief.social_links.model_dump(mode="json"),
        }
    )
    payload["creator_brief"] = brief.creator_brief.model_dump(mode="json")
    return CreatorSynthesis.model_validate(payload)


__all__ = ["merge_creator_synthesis"]
