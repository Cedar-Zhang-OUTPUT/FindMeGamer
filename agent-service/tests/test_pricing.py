from decimal import Decimal

import httpx
from test_provider_calls import api, call


def test_x_estimate_counts_primary_and_expanded_resources_once():
    from fmg_agent.pricing import estimate

    cost = estimate(
        "x",
        "searchPostsRecent",
        "succeeded",
        data={
            "data": [{"id": "1"}, {"id": "2"}],
            "includes": {"tweets": [{"id": "1"}], "users": [{"id": "u"}]},
        },
    )
    assert Decimal(cost["estimated_cost"]) == Decimal("0.020")
    assert cost["complete"] is True
    assert cost["actual_cost"] is None
    assert cost["currency"] == "USD"
    assert cost["basis"] == "list_price_before_discounts_and_daily_deduplication"


def test_missing_unknown_and_empty_are_distinct():
    from fmg_agent.pricing import estimate

    assert (
        estimate("x", "searchPostsRecent", "succeeded", data={})["estimated_cost"]
        is None
    )
    assert (
        estimate("x", "newOperation", "succeeded", data={"data": []})["complete"]
        is False
    )
    empty = estimate(
        "x", "searchPostsRecent", "succeeded", data={"meta": {"result_count": 0}}
    )
    assert Decimal(empty["estimated_cost"]) == 0
    assert estimate("x", "searchPostsRecent", "execution_unknown")["complete"] is False


def test_gemini_thinking_cache_and_search_are_costed_separately():
    from fmg_agent.pricing import estimate

    cost = estimate(
        "gemini",
        "generateContent",
        "succeeded",
        model="gemini-3.8-flash",
        usage={
            "promptTokenCount": 1000,
            "cachedContentTokenCount": 100,
            "candidatesTokenCount": 200,
            "thoughtsTokenCount": 300,
            "search_queries": 2,
        },
        price_date="2026-09-15",
    )
    assert Decimal(cost["estimated_cost"]) == Decimal("0.0305575")
    assert cost["complete"] is True
    missing = estimate(
        "gemini",
        "generateContent",
        "succeeded",
        model="gemini-3.8-flash",
        usage={
            "promptTokenCount": 1000,
            "candidatesTokenCount": 200,
        },
        price_date="2026-09-15",
    )
    assert missing["estimated_cost"] is not None
    assert missing["complete"] is False
    assert "grounding_usage_unavailable" in missing["unpriced_components"]


def test_response_and_ledger_preserve_pricing_snapshot(api):
    client, headers, _, responses = api
    headers["X-FMG-Run-ID"] = "cost-run"
    responses.append(
        httpx.Response(
            200, json={"data": [{"id": "1"}], "includes": {"users": [{"id": "u"}]}}
        )
    )
    response = call(api, "x", "searchPostsRecent", {"query": "game"})
    assert response.status_code == 200
    assert Decimal(response.json()["meta"]["cost"]["estimated_cost"]) == Decimal(
        "0.015"
    )
    responses.append(httpx.Response(200, json={"items": []}))
    assert call(api, "youtube", "search.list", {"part": "snippet"}).status_code == 200
    summary = client.get("/v1/usage?run_id=cost-run", headers=headers).json()["data"]
    assert Decimal(summary["estimated_cost"]) == Decimal("0.015")
    assert summary["complete_cost_known"] is True
    assert summary["actual_cost"] is None
    assert summary["providers"]["youtube"]["estimated_cost"] == "0"


def test_partial_total_does_not_hide_unknown_requests(api):
    from fmg_agent.usage import Ledger

    client, headers, _, responses = api
    headers["X-FMG-Run-ID"] = "partial"
    responses.append(httpx.Response(200, json={"data": {"id": "u"}}))
    assert call(api, "x", "getUsersById", {"id": "123"}).status_code == 200
    token_id = client.get("/v1/auth/check", headers=headers).json()["data"]["token_id"]
    ledger = Ledger(client.app.state.sessions)
    ledger.start("interrupted", token_id, "partial", "gemini", "generateContent")
    summary = ledger.summary(token_id, "partial")
    assert Decimal(summary["estimated_cost"]) == Decimal("0.01")
    assert summary["complete_cost_known"] is False
    assert summary["unpriced_request_count"] == 1


def test_gemini_parse_retains_grounding_usage():
    from fmg_agent.email.gemini import parse_response

    result = parse_response(
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"email_info": []}'}]},
                    "groundingMetadata": {"webSearchQueries": ["one", "two"]},
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
    )
    assert result["usage"]["search_queries"] == 2
