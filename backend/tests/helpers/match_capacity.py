"""Public, synthetic evidence sized like ordinary completed Match profiles.

No production output, personal contact details, or provider calls are used here.
"""

from uuid import UUID

from app.schemas.ai_creator import CreatorBrief
from app.schemas.ai_game import GameBrief
from app.schemas.ai_match import PairwiseMatchBrief


def _prose(length: int) -> str:
    sentence = (
        "The supplied footage presents cooperative play and deliberate decisions. "
        "The creator explains the mechanics clearly while discussing practical tactics. "
    )
    return (sentence * (length // len(sentence) + 1))[:length].rstrip() + "."


def synthetic_game_brief() -> GameBrief:
    missing = {"status": "unavailable", "reason": "No extra synthetic evidence."}
    return GameBrief.model_validate(
        {field: missing for field in GameBrief.model_fields}
    )


def synthetic_creator_brief() -> CreatorBrief:
    evidence = [
        {
            "kind": "source_fact",
            "source_type": "channel_field",
            "reference": "synthetic:cooperative-coverage",
        }
    ]
    text_claim = {
        "status": "available",
        "value": _prose(110),
        "evidence": evidence,
        "confidence": "medium",
    }
    list_claim = {
        "status": "available",
        "values": [
            "Cooperative campaigns with thoughtful tactical explanations",
            "Mechanics-focused coverage and practical demonstrations",
        ],
        "evidence": evidence,
        "confidence": "medium",
    }
    audience = {
        **text_claim,
        "provenance": "ai_inference",
        "evidence": [{**evidence[0], "kind": "ai_inference"}],
    }
    return CreatorBrief.model_validate(
        {
            "positioning": text_claim,
            "content_focus": list_claim,
            "formats": list_claim,
            "style_and_pacing": text_claim,
            "audience": audience,
            "performance_context": text_claim,
            "promotion_fit": text_claim,
            "brand_safety": text_claim,
            "suitable_game_types": list_claim,
            "collaboration_risks": list_claim,
        }
    )


def synthetic_pairwise_brief(creator_id: UUID) -> PairwiseMatchBrief:
    """Approximately 6.8 KB per brief, without relying on schema maximums."""
    dimension = {"analysis": _prose(950), "evidence": [_prose(200)]}
    return PairwiseMatchBrief.model_validate(
        {
            "english_language_check": True,
            "creator_id": creator_id,
            "content_fit": dimension,
            "audience_fit": dimension,
            "performance_fit": dimension,
            "promotion_fit": dimension,
            "brand_safety": dimension,
            "strengths": [_prose(150)],
            "risks": [_prose(150)],
            "evidence": [_prose(150)],
            "match_reasons": [_prose(150)],
        }
    )
