"""Match request budgets are explicit and remain intact on provider failures."""

import json
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from app.analysis.contracts import Message
from app.integrations.deepseek import (
    MAX_REPAIR_CONTEXT_CHARACTERS,
    DeepSeekGateway,
    _schema_instruction,
    _schema_payload,
)
from app.integrations.errors import TransientIntegrationError
from app.matching import prompts
from app.schemas.ai_match import (
    FinalRankingOutput,
    PairwiseMatchBrief,
    ScreeningOutput,
)
from tests.helpers.match_capacity import (
    synthetic_pairwise_brief,
    synthetic_game_brief,
    synthetic_creator_brief,
)
from app.schemas.ai_creator import CreatorBrief


def _full_creator_brief():
    payload = synthetic_creator_brief().model_dump(mode="json")
    payload["positioning"]["value"] = "x" * 4000
    current = len(
        CreatorBrief.model_validate(payload).model_dump_json().encode("utf-8")
    )
    payload["style_and_pacing"]["value"] += "s" * (8000 - current)
    result = CreatorBrief.model_validate(payload)
    assert len(result.model_dump_json().encode("utf-8")) == 8000
    return result


@pytest.mark.parametrize("manual_text_size", [600, 2000])
def test_screening_hundred_full_briefs_and_manual_context_reach_gateway_or_reject_oversize(
    manual_text_size,
):
    creators = [(UUID(int=index), _full_creator_brief()) for index in range(1, 101)]
    manual = {
        "revision": 1,
        "provenance": "manual",
        "overrides": {
            "analysis.content_summary": "Editorial context. " * (manual_text_size // 19)
        },
    }
    kwargs = dict(
        game_manual_context={
            "revision": 1,
            "provenance": "manual",
            "overrides": {"facts.name": "Manual game"},
        },
        creator_manual_contexts={creator_id: manual for creator_id, _ in creators},
    )
    if manual_text_size == 2000:
        with pytest.raises(ValueError, match="total byte budget"):
            prompts.build_screening_prompt(synthetic_game_brief(), creators, **kwargs)
        return
    messages = prompts.build_screening_prompt(
        synthetic_game_brief(), creators, **kwargs
    )
    recheck = prompts.build_empty_screening_recheck(messages)
    payloads = [
        json.loads(message.content.split("```json\n", 1)[1].removesuffix("\n```"))
        for message in messages[1:]
    ]
    sent_creators = [
        item for payload in payloads for item in payload.get("creators", [])
    ]
    assert [item["creator_id"] for item in sent_creators] == [
        str(item[0]) for item in creators
    ]
    assert all(
        item["creator_brief"] == creators[0][1].model_dump(mode="json")
        for item in sent_creators
    )
    assert all(item["manual_context"] == manual for item in sent_creators)
    assert sum("game_manual_context" in payload for payload in payloads) == 1
    requests = []

    def handler(request):
        requests.append(json.loads(request.read()))
        content = "not-json" if len(requests) == 1 else _valid_output(ScreeningOutput)
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = DeepSeekGateway(
            api_key="test-key", http_client=client
        ).complete_structured("deepseek-flash", recheck, ScreeningOutput)
    assert result.selected == ()
    assert len(requests) == 2
    assert (
        requests[1]["messages"][: len(requests[0]["messages"])]
        == requests[0]["messages"]
    )


STAGES = [
    (ScreeningOutput, "deepseek-flash", 16_384),
    (PairwiseMatchBrief, "deepseek-flash", 16_384),
    (FinalRankingOutput, "deepseek-flash", 65_536),
]


def _valid_output(schema: type) -> str:
    if schema is ScreeningOutput:
        return '{"english_language_check":true,"selected":[]}'
    if schema is FinalRankingOutput:
        return '{"english_language_check":true,"items":[]}'
    dimension = {
        "analysis": "The supplied evidence supports this comparison.",
        "evidence": ["A supplied public video illustrates the format."],
    }
    return json.dumps(
        {
            "english_language_check": True,
            "creator_id": str(UUID(int=1)),
            **{
                field: dimension
                for field in (
                    "content_fit",
                    "audience_fit",
                    "performance_fit",
                    "promotion_fit",
                    "brand_safety",
                )
            },
            **{
                field: ["The supplied brief supports the qualitative assessment."]
                for field in ("strengths", "risks", "evidence", "match_reasons")
            },
        }
    )


@pytest.mark.parametrize(("schema", "model", "budget"), STAGES)
def test_match_output_budgets_are_metadata_not_new_checkpoint_fields(
    schema: type, model: str, budget: int
) -> None:
    assert getattr(schema, "deepseek_max_tokens", None) == budget
    assert "deepseek_max_tokens" not in schema.model_json_schema()["properties"]
    # Old persisted outputs still validate unchanged; no new model-owned field.
    output = schema.model_validate_json(_valid_output(schema))
    assert "deepseek_max_tokens" not in output.model_dump()


@pytest.mark.parametrize(("schema", "model", "budget"), STAGES)
def test_match_schema_repair_retains_explicit_output_budget_and_all_inputs(
    schema: type, model: str, budget: int
) -> None:
    sent: list[dict] = []
    original = [
        Message(role="system", content="Compare all supplied evidence."),
        Message(role="user", content="First complete input group."),
        Message(role="user", content="Last complete input group."),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.read()))
        content = "not-json" if len(sent) == 1 else _valid_output(schema)
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = DeepSeekGateway(
            api_key="test-key", http_client=client
        ).complete_structured(model, original, schema)

    assert isinstance(result, schema)
    assert len(sent) == 2
    assert all(request.get("max_tokens") == budget for request in sent)
    assert all(request["thinking"] == {"type": "disabled"} for request in sent)
    assert sent[1]["messages"][: len(sent[0]["messages"])] == sent[0]["messages"]
    assert len(original) == 3


@pytest.mark.parametrize(("schema", "model", "budget"), STAGES)
def test_match_truncation_is_retryable_never_accepted_as_partial_success(
    schema: type, model: str, budget: int
) -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.read()))
        # Even parseable JSON is not complete when the provider reports length.
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": _valid_output(schema)},
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TransientIntegrationError) as error:
            DeepSeekGateway(api_key="test-key", http_client=client).complete_structured(
                model, [Message(role="user", content="All locked inputs.")], schema
            )

    assert error.value.code == "deepseek_model_output_invalid"
    assert len(sent) == 1  # Worker checkpoint retry, not repair of a partial response.
    assert sent[0].get("max_tokens") == budget


def test_ranking_groups_complete_briefs_once_with_one_shared_threshold() -> None:
    briefs = [synthetic_pairwise_brief(UUID(int=index)) for index in range(1, 31)]

    messages = prompts.build_ranking_prompt(briefs, threshold=Decimal("0.7000"))

    payloads = [
        json.loads(message.content.split("```json\n", 1)[1].removesuffix("\n```"))
        for message in messages[1:]
    ]
    assert len(messages) > 2
    assert "one global ranking" in messages[0].content
    assert "input order carry no preference" in messages[0].content
    assert [
        payload["recommended_match_threshold"]
        for payload in payloads
        if "recommended_match_threshold" in payload
    ] == ["0.7000"]
    assert [
        item for payload in payloads for item in payload.get("match_briefs", [])
    ] == [brief.model_dump(mode="json") for brief in briefs]


def test_ranking_total_budget_is_not_reset_for_each_message(monkeypatch) -> None:
    briefs = [synthetic_pairwise_brief(UUID(int=index)) for index in range(1, 31)]
    monkeypatch.setattr(prompts, "MAX_MATCH_TOTAL_MESSAGE_BYTES", 150_000)

    with pytest.raises(ValueError, match="total byte budget"):
        prompts.build_ranking_prompt(briefs, threshold=Decimal("0.7000"))


def test_match_context_budget_reserves_schema_repair_and_output_headroom() -> None:
    largest_schema_bytes = max(
        len(_schema_instruction(_schema_payload(schema))["content"].encode("utf-8"))
        for schema, _, _ in STAGES
    )
    # Schemas occur twice on repair. Reserve four UTF-8 bytes per repair-context
    # character, plus 10 KB for safe errors, role framing and repair instructions.
    # Bytes are a conservative sizing proxy, not a measured model token count.
    assert (
        prompts.MAX_MATCH_TOTAL_MESSAGE_BYTES
        + 2 * largest_schema_bytes
        + 4 * MAX_REPAIR_CONTEXT_CHARACTERS
        + 10_000
        + max(budget for _, _, budget in STAGES)
        < 1_000_000
    )


def test_screening_context_reserves_schema_repair_recheck_and_output_headroom():
    schema_bytes = len(
        _schema_instruction(_schema_payload(ScreeningOutput))["content"].encode("utf-8")
    )
    assert (
        prompts.MAX_SCREENING_TOTAL_MESSAGE_BYTES
        + 2 * schema_bytes
        + 4 * MAX_REPAIR_CONTEXT_CHARACTERS
        + 10_000
        + 16_384
        < 1_000_000
    )
