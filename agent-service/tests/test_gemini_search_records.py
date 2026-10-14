"""Regression for JSON responses omitting legacy grounding metadata."""

import json

import httpx
import pytest

from fmg_agent.email.gemini import GeminiGateway, parse_response


def traced_response(*, source=False, response_id="search-1"):
    candidate = {
        "finishReason": "STOP",
        "content": {
            "parts": [
                {
                    "toolCall": {
                        "toolType": "GOOGLE_SEARCH_WEB",
                        "id": "search-1",
                        "args": {
                            "queries": [
                                "Creator contact",
                                "",
                                "Creator contact",
                                "Creator email",
                            ]
                        },
                    }
                },
                {
                    "toolResponse": {
                        "toolType": "GOOGLE_SEARCH_WEB",
                        "id": response_id,
                        "response": {
                            "search_suggestions": '<a href="https://google.com/search?q=contact">Search</a>'
                        },
                    }
                },
                {
                    "text": json.dumps(
                        {
                            "email_info": [],
                            "lookup_summary": "Checked public creator sources; no email found.",
                            "checked_sources": ["https://example.org/creator"],
                        }
                    )
                },
            ]
        },
    }
    if source:
        candidate["groundingMetadata"] = {
            "groundingChunks": [{"web": {"uri": "https://example.org/creator"}}]
        }
    return {
        "candidates": [candidate],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
    }


def test_gateway_requests_tool_trace_and_cited_lookup_even_when_email_empty():
    def upstream(request):
        body = json.loads(request.content)
        assert body["toolConfig"]["includeServerSideToolInvocations"] is True
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        item = body["generationConfig"]["responseJsonSchema"]["properties"][
            "email_info"
        ]["items"]
        assert "source" not in item["required"]
        return httpx.Response(200, json=traced_response(source=True))

    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        result = GeminiGateway("test-key", "test-model", client=client).find(
            {"url": "https://youtube.com/@creator"}
        )
    assert result["emails"] == []
    assert result["coverage"]["search_completed"] is True


def test_sourced_report_with_one_final_json_block_keeps_provider_grounding():
    payload = traced_response(source=True)
    payload["candidates"][0]["content"]["parts"][-1]["text"] = (
        "Checked the creator profile: https://example.org/creator. No email found.\n\n"
        '```json\n{"email_info":[],"checked_sources":["https://example.org/creator"]}\n```'
    )
    result = parse_response(payload)
    assert result["emails"] == []
    assert result["coverage"]["search_completed"] is True
    assert result["lookup_summary"].startswith("Checked the creator profile")


@pytest.mark.parametrize(
    "text",
    [
        'Report ```json\n{"email_info":[]}\n``` extra text',
        '```json\n{"email_info":[]}\n```\nReport\n```json\n{"email_info":[]}\n```',
        "Report ```json\nnot JSON\n```",
    ],
)
def test_ambiguous_or_malformed_report_json_is_not_empty_success(text):
    from fmg_agent.email.enrichment import EnrichmentError

    payload = traced_response(source=True)
    payload["candidates"][0]["content"]["parts"][-1]["text"] = text
    with pytest.raises(EnrichmentError, match="model_output_invalid"):
        parse_response(payload)


@pytest.mark.parametrize("source,complete", [(False, False), (True, True)])
def test_paired_tool_search_records_count_queries_but_suggestions_are_not_sources(
    source, complete
):
    result = parse_response(traced_response(source=source))
    assert result["usage"]["search_queries"] == 2
    assert result["coverage"]["search_query_count"] == 2
    assert result["coverage"]["search_queries"] == ["Creator contact", "Creator email"]
    assert result["coverage"]["search_completed"] is complete
    assert result["coverage"]["source_urls"] == (
        ["https://example.org/creator"] if source else []
    )
    assert result["lookup_summary"] == "Checked public creator sources; no email found."
    assert result["reported_source_urls"] == ["https://example.org/creator"]


def test_unpaired_search_call_does_not_establish_execution_or_zero_cost():
    result = parse_response(traced_response(response_id="different-search"))
    assert "search_queries" not in result["usage"]
    assert result["coverage"]["search_query_count"] == 0
    assert result["coverage"]["search_completed"] is False


def test_legacy_and_tool_queries_are_not_double_counted():
    payload = traced_response(source=True)
    payload["candidates"][0]["groundingMetadata"]["webSearchQueries"] = [
        "Creator contact",
        "",
        "Creator email",
    ]
    result = parse_response(payload)
    assert result["usage"]["search_queries"] == 2
    assert result["coverage"]["search_query_count"] == 2


def test_tool_report_html_never_becomes_source_or_executable_content():
    payload = traced_response()
    payload["candidates"][0]["content"]["parts"][1]["toolResponse"]["response"][
        "search_suggestions"
    ] = '<script>steal()</script><a href="http://127.0.0.1">Creator</a>'
    result = parse_response(payload)
    assert result["coverage"]["source_urls"] == []
    assert "steal" not in json.dumps(result)


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        "malformed",
        {"id": "search-1", "toolType": "GOOGLE_SEARCH_WEB", "response": None},
    ],
)
def test_malformed_tool_records_do_not_complete_search(record):
    payload = traced_response()
    payload["candidates"][0]["content"]["parts"][1]["toolResponse"] = record
    result = parse_response(payload)
    assert result["coverage"]["search_completed"] is False
    assert "search_queries" not in result["usage"]


@pytest.mark.parametrize("fault", ["unpaired", "malformed_error"])
def test_mixed_search_records_do_not_hide_unknown_usage_or_failed_retrieval(fault):
    payload = traced_response(source=True)
    parts = payload["candidates"][0]["content"]["parts"]
    call = {
        "id": "search-2",
        "toolType": "GOOGLE_SEARCH_WEB",
        "args": {"queries": ["Other contact"]},
    }
    if fault == "malformed_error":
        call["args"] = {}
        parts.append(
            {
                "toolResponse": {
                    "id": "search-2",
                    "toolType": "GOOGLE_SEARCH_WEB",
                    "response": {"error": "timeout"},
                }
            }
        )
    parts.append({"toolCall": call})
    result = parse_response(payload)
    assert (
        "search_queries" not in result["usage"]
    ), "partial records cannot price total query usage"
    assert result["coverage"]["search_usage_known"] is False
    assert result["coverage"]["retrieval_failed"] is True
    assert result["coverage"]["search_completed"] is False
    assert result["coverage"]["search_calls"][-1]["status"] in {"incomplete", "failed"}
