import httpx
from test_provider_calls import api, call


def test_provider_success_failure_and_token_isolation(api):
    client, headers, requests, responses = api
    headers["X-FMG-Run-ID"] = "research-1"
    responses.extend(
        [
            httpx.Response(200, json={"items": [{"id": "1"}]}),
            httpx.Response(429, json={}),
        ]
    )
    assert call(api, "youtube", "search.list", {"part": "snippet"}).status_code == 200
    assert call(api, "youtube", "search.list", {"part": "snippet"}).status_code == 429
    r = client.get("/v1/usage?run_id=research-1", headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["request_count"] == 2
    assert data["complete_cost_known"] is False
    assert data["actual_cost"] is None
    assert data["providers"]["youtube"]["statuses"] == {
        "succeeded": 1,
        "rate_limited": 1,
    }
    assert data["providers"]["youtube"]["resource_counts"]["returned_items"] == 1
    assert (
        data["providers"]["youtube"]["quota_estimate"]["successful_calls"][
            "search_calls"
        ]
        == 1
    )
    assert data["providers"]["youtube"]["quota_estimate"]["unresolved_calls"] == 1
    from fmg_agent.auth import issue_token

    with client.app.state.sessions() as session:
        other = issue_token(session, label="other", scopes=["read"])
    second = client.get(
        "/v1/usage?run_id=research-1",
        headers={"Authorization": f"Bearer {other.token}"},
    )
    assert second.json()["data"]["request_count"] == 0


def test_ledger_deduplicates_and_preserves_unknown(api):
    from fmg_agent.usage import Ledger

    client, headers, *_ = api
    token_id = client.get("/v1/auth/check", headers=headers).json()["data"]["token_id"]
    ledger = Ledger(client.app.state.sessions)
    assert ledger.start("r1", token_id, "run", "x", "search") is True
    assert ledger.start("r1", token_id, "run", "x", "search") is False
    ledger.finish("r1", "succeeded", usage={"promptTokenCount": 12, "secret": "no"})
    data = ledger.summary(token_id, "run")
    assert data["request_count"] == 1
    assert data["providers"]["x"]["usage"] == {"promptTokenCount": 12}
    assert data["actual_cost"] is None and data["estimated_cost"] is None


def test_non_list_response_does_not_invent_zero_items(api):
    api[3].append(
        httpx.Response(200, json={"570": {"success": True, "data": {"name": "Dota 2"}}})
    )
    assert call(api, "steam", "store.appdetails", {"appids": "570"}).status_code == 200
    data = api[0].get("/v1/usage?run_id=unassigned", headers=api[1]).json()["data"]
    assert data["providers"]["steam"]["resource_counts"] == {}


def test_bad_run_id_rejected_before_upstream(api):
    api[3].append(httpx.Response(200, json={"items": []}))
    api[1]["X-FMG-Run-ID"] = "space is not allowed"
    assert call(api, "youtube", "search.list", {"part": "snippet"}).status_code == 422
    assert not api[2]
