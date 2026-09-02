from copy import deepcopy
from math import inf, nan
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.ai_match import (
    FinalRankingOutput,
    PairwiseMatchBrief,
    RankingItem,
    ScreeningOutput,
)


CREATOR_A = UUID("00000000-0000-4000-8000-000000000001")
CREATOR_B = UUID("00000000-0000-4000-8000-000000000002")
CREATOR_C = UUID("00000000-0000-4000-8000-000000000003")


def screening_selection(creator_id: UUID = CREATOR_A) -> dict[str, object]:
    return {
        "creator_id": creator_id,
        "screening_reason": "The creator regularly covers this game genre.",
        "evidence": ["The compact brief identifies strategy coverage."],
    }


def assessment(topic: str) -> dict[str, object]:
    return {
        "analysis": f"The supplied profile supports a {topic} fit.",
        "evidence": [f"The supplied {topic} evidence is directly relevant."],
    }


def pairwise_payload(creator_id: UUID = CREATOR_A) -> dict[str, object]:
    return {
        "english_language_check": True,
        "creator_id": creator_id,
        "content_fit": assessment("content"),
        "audience_fit": assessment("audience"),
        "performance_fit": assessment("performance"),
        "promotion_fit": assessment("promotion"),
        "brand_safety": assessment("brand safety"),
        "strengths": ["The channel format supports an explainable campaign."],
        "risks": ["The supplied evidence leaves launch timing uncertain."],
        "evidence": ["The locked profile identifies long-form strategy videos."],
        "match_reasons": ["The creator and game share a strategy focus."],
    }


def ranking_item_payload(
    creator_id: UUID = CREATOR_A,
    *,
    backend_order: int = 0,
) -> dict[str, object]:
    return {
        "creator_id": creator_id,
        "total_score": 0.75,
        "dimension_scores": {
            "content_fit": 0.8,
            "audience_fit": 0.7,
            "performance_fit": 0.6,
            "promotion_fit": 0.9,
            "brand_safety": 0.85,
        },
        "backend_order": backend_order,
        "result_group": "recommended",
        "qualitative_label": "Strong Match",
        "dimension_outcomes": {
            "content_fit": "Strong alignment with the supplied content evidence.",
            "audience_fit": "Good inferred audience alignment.",
            "performance_fit": "Consistent performance context for this campaign.",
            "promotion_fit": "The format supports a natural promotion concept.",
            "brand_safety": "No material concern appears in supplied evidence.",
        },
        "match_reasons": ["Strong content and promotion alignment."],
    }


def ranking_payload(*items: dict[str, object]) -> dict[str, object]:
    return {
        "english_language_check": True,
        "items": list(items),
    }


def test_screening_accepts_zero_through_thirty_unique_creators() -> None:
    assert ScreeningOutput(english_language_check=True, selected=()).selected == ()

    selected = [
        screening_selection(UUID(f"00000000-0000-4000-8000-{index:012d}"))
        for index in range(1, 31)
    ]
    output = ScreeningOutput.model_validate(
        {"english_language_check": True, "selected": selected}
    )

    assert len(output.selected) == 30
    assert len({item.creator_id for item in output.selected}) == 30


def test_screening_rejects_more_than_thirty_or_duplicate_creator_ids() -> None:
    too_many = [
        screening_selection(UUID(f"00000000-0000-4000-8000-{index:012d}"))
        for index in range(1, 32)
    ]
    with pytest.raises(ValidationError):
        ScreeningOutput.model_validate(
            {"english_language_check": True, "selected": too_many}
        )

    with pytest.raises(ValidationError, match="creator IDs must be unique"):
        ScreeningOutput.model_validate(
            {
                "english_language_check": True,
                "selected": [screening_selection(), screening_selection()],
            }
        )


@pytest.mark.parametrize(
    "bad_id",
    ["not-a-uuid", 1, True, {"value": str(CREATOR_A)}],
)
def test_match_outputs_reject_malformed_or_coerced_creator_ids(bad_id: object) -> None:
    payload = screening_selection()
    payload["creator_id"] = bad_id

    with pytest.raises(ValidationError):
        ScreeningOutput.model_validate(
            {"english_language_check": True, "selected": [payload]}
        )


def test_pairwise_brief_requires_all_nine_evidence_backed_sections() -> None:
    output = PairwiseMatchBrief.model_validate(pairwise_payload())

    assert output.creator_id == CREATOR_A
    assert output.content_fit.evidence
    assert output.audience_fit.evidence
    assert output.performance_fit.evidence
    assert output.promotion_fit.evidence
    assert output.brand_safety.evidence
    assert output.strengths
    assert output.risks
    assert output.evidence
    assert output.match_reasons

    for field_name in (
        "content_fit",
        "audience_fit",
        "performance_fit",
        "promotion_fit",
        "brand_safety",
        "strengths",
        "risks",
        "evidence",
        "match_reasons",
    ):
        missing = pairwise_payload()
        del missing[field_name]
        with pytest.raises(ValidationError):
            PairwiseMatchBrief.model_validate(missing)


def test_pairwise_brief_rejects_ranking_and_outreach_fields() -> None:
    forbidden_fields = {
        "rank": 1,
        "total_score": 0.9,
        "result_group": "recommended",
        "contact_email": "secret@example.com",
        "favorite": True,
        "prior_outreach": "accepted",
    }

    for field_name, value in forbidden_fields.items():
        payload = pairwise_payload()
        payload[field_name] = value
        with pytest.raises(ValidationError):
            PairwiseMatchBrief.model_validate(payload)


@pytest.mark.parametrize("score", [-0.01, 1.01, inf, -inf, nan, "0.75", True])
def test_ranking_rejects_non_finite_out_of_range_or_coerced_scores(
    score: object,
) -> None:
    payload = ranking_item_payload()
    payload["total_score"] = score

    with pytest.raises(ValidationError):
        RankingItem.model_validate(payload)

    payload = ranking_item_payload()
    payload["dimension_scores"]["content_fit"] = score  # type: ignore[index]
    with pytest.raises(ValidationError):
        RankingItem.model_validate(payload)


@pytest.mark.parametrize("backend_order", [-1, 0.0, "0", True])
def test_ranking_requires_a_strict_non_negative_backend_order(
    backend_order: object,
) -> None:
    payload = ranking_item_payload()
    payload["backend_order"] = backend_order

    with pytest.raises(ValidationError):
        RankingItem.model_validate(payload)


def test_final_ranking_rejects_duplicate_creator_ids_and_backend_orders() -> None:
    with pytest.raises(ValidationError, match="creator IDs must be unique"):
        FinalRankingOutput.model_validate(
            ranking_payload(
                ranking_item_payload(CREATOR_A, backend_order=0),
                ranking_item_payload(CREATOR_A, backend_order=1),
            )
        )

    with pytest.raises(ValidationError, match="backend orders must be unique"):
        FinalRankingOutput.model_validate(
            ranking_payload(
                ranking_item_payload(CREATOR_A, backend_order=0),
                ranking_item_payload(CREATOR_B, backend_order=0),
            )
        )


def test_final_ranking_validates_the_exact_expected_creator_id_set() -> None:
    output = FinalRankingOutput.model_validate(
        ranking_payload(
            ranking_item_payload(CREATOR_A, backend_order=0),
            ranking_item_payload(CREATOR_B, backend_order=1),
        )
    )

    assert output.validate_expected_creator_ids([CREATOR_B, CREATOR_A]) is output
    with pytest.raises(ValueError, match="exactly match expected creator IDs"):
        output.validate_expected_creator_ids([CREATOR_A])
    with pytest.raises(ValueError, match="exactly match expected creator IDs"):
        output.validate_expected_creator_ids([CREATOR_A, CREATOR_B, CREATOR_C])
    with pytest.raises(ValueError, match="expected creator IDs must be unique"):
        output.validate_expected_creator_ids([CREATOR_A, CREATOR_A])
    with pytest.raises(TypeError, match="expected creator IDs must be UUID values"):
        output.validate_expected_creator_ids([str(CREATOR_A), CREATOR_B])  # type: ignore[list-item]


def test_output_models_are_closed_frozen_validate_defaults_and_attest_english() -> None:
    outputs = (
        ScreeningOutput(english_language_check=True, selected=()),
        PairwiseMatchBrief.model_validate(pairwise_payload()),
        FinalRankingOutput.model_validate(ranking_payload(ranking_item_payload())),
    )

    for output in outputs:
        with pytest.raises(ValidationError):
            output.model_validate({**output.model_dump(), "unknown": "rejected"})
        with pytest.raises(ValidationError):
            output.english_language_check = False

        invalid_attestation = deepcopy(output.model_dump(mode="json"))
        invalid_attestation["english_language_check"] = 1
        with pytest.raises(ValidationError):
            type(output).model_validate(invalid_attestation)

    with pytest.raises(ValidationError):
        ScreeningOutput(selected=())  # type: ignore[call-arg]


def test_match_outputs_have_a_strict_json_round_trip() -> None:
    outputs = (
        ScreeningOutput.model_validate(
            {
                "english_language_check": True,
                "selected": [screening_selection()],
            }
        ),
        PairwiseMatchBrief.model_validate(pairwise_payload()),
        FinalRankingOutput.model_validate(ranking_payload(ranking_item_payload())),
    )

    for output in outputs:
        assert type(output).model_validate_json(output.model_dump_json()) == output
