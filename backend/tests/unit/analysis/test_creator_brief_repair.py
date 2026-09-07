import json
import logging
from copy import deepcopy

import httpx
import pytest

from app.integrations.deepseek import DeepSeekGateway
from app.integrations.errors import InvalidModelOutput
from app.schemas.ai_creator_map_reduce import CreatorBriefSynthesis
from app.analysis.creator_pipeline import unavailable_visual_analysis
from app.schemas.ai_creator import CreatorVisualAnalysis

from .test_creator_map_reduce import _brief_payload


def _gateway(responses):
    requests = []
    values = iter(responses)

    def handler(request):
        requests.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(next(values))}}]},
        )

    return (
        DeepSeekGateway(
            api_key="test-key",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
        requests,
    )


def test_brief_repairs_only_overlong_text_without_rewriting_other_fields():
    original = _brief_payload()
    original["creator_brief"]["positioning"]["value"] = (
        "Comedy-focused horror gaming commentary, with edited reactions and occasional "
        "story-driven playthroughs; not a competitive esports analysis or tutorial channel."
    )
    replacement = "Comedy horror reactions and story playthroughs, not esports analysis or tutorials."
    gateway, requests = _gateway([original, {"text_0": replacement}])

    result = gateway.complete_structured("deepseek-v4-pro", [], CreatorBriefSynthesis)

    expected = deepcopy(original)
    expected["creator_brief"]["positioning"]["value"] = replacement
    assert result.model_dump(mode="json") == expected
    assert len(requests) == 2
    repair = requests[1]
    assert repair["max_tokens"] <= 3072
    instruction = repair["messages"][0]["content"]
    assert '"maxLength":144' in instruction
    assert '"text_0"' in instruction
    prompt = repair["messages"][1]["content"]
    assert "negation" in prompt
    assert original["creator_brief"]["positioning"]["value"] in prompt
    assert "candidate_id" not in prompt


def test_brief_stubborn_overlong_repair_fails_without_truncating_or_dropping_claim():
    original = _brief_payload()
    original["creator_brief"]["positioning"]["value"] = "Long context. " * 30
    gateway, requests = _gateway(
        [original, {"text_0": "Still long. " * 30}, {"text_0": "Still long. " * 30}]
    )
    with pytest.raises(InvalidModelOutput, match="deepseek_model_output_invalid"):
        gateway.complete_structured("deepseek-v4-pro", [], CreatorBriefSynthesis)
    assert len(requests) == 3


def test_brief_valid_output_needs_no_repair():
    original = _brief_payload()
    gateway, requests = _gateway([original])
    assert (
        gateway.complete_structured(
            "deepseek-v4-pro", [], CreatorBriefSynthesis
        ).model_dump(mode="json")
        == original
    )
    assert len(requests) == 1


def test_brief_non_length_error_uses_existing_full_schema_repair():
    original = _brief_payload()
    original["creator_brief"]["positioning"]["confidence"] = "invalid"
    gateway, requests = _gateway([original, _brief_payload()])
    gateway.complete_structured("deepseek-v4-pro", [], CreatorBriefSynthesis)
    assert len(requests) == 2
    assert "CreatorBriefSynthesis" in requests[1]["messages"][0]["content"]


def test_brief_compaction_does_not_hide_other_invalid_claim_fields():
    original = _brief_payload()
    original["creator_brief"]["positioning"]["value"] = "Long context. " * 30
    original["creator_brief"]["positioning"]["confidence"] = "invalid"
    gateway, requests = _gateway([original, original])
    with pytest.raises(InvalidModelOutput):
        gateway.complete_structured("deepseek-v4-pro", [], CreatorBriefSynthesis)
    assert len(requests) == 2


def test_brief_repairs_multiple_lengths_in_one_call_with_original_evidence():
    original = _brief_payload()
    original["creator_brief"]["positioning"]["value"] = "Positioning context. " * 20
    original["creator_brief"]["formats"]["values"] = ["Extended format name. " * 10]
    original["creator_brief"]["brand_safety"] = {
        "status": "unavailable",
        "reason": "Insufficient public context. " * 20,
    }
    gateway, requests = _gateway(
        [
            original,
            {
                "text_0": "No esports analysis.",
                "text_1": "Long-form reactions",
                "text_2": "Insufficient public context.",
            },
        ]
    )
    result = gateway.complete_structured("deepseek-v4-pro", [], CreatorBriefSynthesis)
    assert len(requests) == 2
    expected = deepcopy(original)
    expected["creator_brief"]["positioning"]["value"] = "No esports analysis."
    expected["creator_brief"]["formats"]["values"] = ["Long-form reactions"]
    expected["creator_brief"]["brand_safety"]["reason"] = "Insufficient public context."
    assert result.model_dump(mode="json") == expected


def test_brief_repairs_length_remaining_after_general_repair_with_bounded_calls():
    overlong = _brief_payload()
    overlong["creator_brief"]["positioning"]["value"] = "Context. " * 30
    malformed = deepcopy(overlong)
    malformed["english_language_check"] = False
    gateway, requests = _gateway(
        [malformed, overlong, {"text_0": "Compact positioning."}]
    )
    result = gateway.complete_structured("deepseek-v4-pro", [], CreatorBriefSynthesis)
    assert result.creator_brief.positioning.value == "Compact positioning."
    assert len(requests) == 3


def test_brief_repaired_list_must_still_obey_uniqueness():
    original = _brief_payload()
    original["creator_brief"]["formats"]["values"] = [
        "Long reactions. " * 10,
        "Reactions",
    ]
    gateway, requests = _gateway([original, {"text_0": "Reactions"}])
    with pytest.raises(InvalidModelOutput):
        gateway.complete_structured("deepseek-v4-pro", [], CreatorBriefSynthesis)
    assert len(requests) == 2


def test_brief_length_repair_does_not_hide_an_actually_empty_list():
    original = _brief_payload()
    original["creator_brief"]["positioning"]["value"] = "Long context. " * 30
    original["creator_brief"]["formats"]["values"] = []
    gateway, requests = _gateway([original, original])
    with pytest.raises(InvalidModelOutput):
        gateway.complete_structured("deepseek-v4-pro", [], CreatorBriefSynthesis)
    assert len(requests) == 2


def test_visual_root_failure_logs_only_code_owned_reason(caplog, monkeypatch):
    # Alembic's fileConfig can disable existing loggers in the full suite.
    monkeypatch.setattr(
        logging.getLogger("app.integrations.deepseek"), "disabled", False
    )
    original = unavailable_visual_analysis("PRIVATE-MODEL-TEXT").model_dump(mode="json")
    original["status"] = "available"
    gateway, _ = _gateway([original, original])
    with pytest.raises(InvalidModelOutput):
        gateway.complete_structured(
            "deepseek-v4-flash-vision-exp", [], CreatorVisualAnalysis
        )
    assert "visual_available_reason_invalid" in caplog.text
    assert "PRIVATE-MODEL-TEXT" not in caplog.text
