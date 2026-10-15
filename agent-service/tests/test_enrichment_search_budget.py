"""Gateway budget is advisory; observed overages must not cause paid retries."""

import json

import httpx
import pytest

from fmg_agent.email.enrichment import EnrichmentError
from fmg_agent.email.gemini import GeminiGateway


@pytest.mark.parametrize("queries,expected", [(2, False), (8, True), (None, None)])
def test_low_thinking_keeps_empty_success_and_reports_real_search_overage(
    queries, expected
):
    calls = []
    target = {
        "url": "https://youtube.com/@creator",
        "evidence": [
            {
                "source_url": "https://youtube.com/@creator",
                "text": "Contact via example.org",
            }
        ],
    }

    def upstream(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
        assert json.loads(body["contents"][0]["parts"][0]["text"]) == target
        candidate = {
            "finishReason": "STOP",
            "content": {"parts": [{"text": '{"email_info":[]}'}]},
        }
        if queries is not None:
            candidate["groundingMetadata"] = {
                "webSearchQueries": [f"query {i}" for i in range(queries)]
            }
        return httpx.Response(200, json={"candidates": [candidate]})

    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        result = GeminiGateway("test-key", "gemini-3.8-flash", client=client).find(
            target
        )
    assert len(calls) == 1
    assert result["emails"] == []
    assert result["search_policy"] == {
        "version": "economy-v1",
        "enforcement": "prompt_only",
        "thinking_level": "low",
        "initial_query_target": 3,
        "total_query_target": 6,
        "observed_queries": queries,
        "target_exceeded": expected,
    }


@pytest.mark.parametrize(
    "status,code",
    [
        (402, "upstream_request_rejected"),
        (429, "upstream_rate_limited"),
        (503, "upstream_unavailable"),
    ],
)
def test_budget_does_not_convert_provider_error_into_not_found_or_retry(status, code):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "Unavailable"}})

    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        with pytest.raises(EnrichmentError, match=code):
            GeminiGateway("test-key", "gemini-3.8-flash", client=client).find(
                {"url": "https://youtube.com/@creator"}
            )
    assert len(calls) == 1
