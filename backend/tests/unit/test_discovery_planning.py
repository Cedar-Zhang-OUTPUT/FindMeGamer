import json

import httpx
import pytest
from pydantic import ValidationError

from app.discovery.planning import (
    PlanningInputError,
    generate_plan,
    provider_queries,
)
from app.integrations.deepseek import DeepSeekGateway
from app.integrations.errors import InvalidModelOutput, TransientIntegrationError
from app.schemas.discovery_plan_output import SearchPlanOutput


def _response(content: str, *, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": content},
                }
            ]
        },
    )


def _valid_output() -> dict:
    return {
        "summary": "Find English-speaking creators discussing the supplied game.",
        "rationale": "Use the game name and supplied content keyword.",
        "queries": [
            {"platform": "youtube", "terms": ["Café Quest", "gameplay"]},
            {"platform": "x", "terms": ["Café Quest", "creator reactions"]},
        ],
    }


def _gateway(handler) -> DeepSeekGateway:
    return DeepSeekGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_generate_plan_uses_real_gateway_and_compiles_provider_queries() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return _response(json.dumps(_valid_output()))

    output = generate_plan(
        {
            "game": {
                "name": "Café Quest",
                "description": "A cooperative puzzle adventure.",
                "tags": ["Puzzle"],
            }
        },
        {"platforms": ["youtube", "x"], "keywords": ["gameplay"]},
        gateway=_gateway(handler),
        model="deepseek-chat",
    )

    assert output == SearchPlanOutput.model_validate(_valid_output())
    assert requests[0]["model"] == "deepseek-chat"
    assert requests[0]["max_tokens"] == 2048
    assert provider_queries(output) == {
        "youtube": '"Café Quest" "gameplay"',
        "x": '"Café Quest" "creator reactions" -is:retweet',
    }


def test_generate_plan_prompt_includes_only_allowlisted_frozen_and_condition_fields() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read()))
        return _response(json.dumps(_valid_output()))

    generate_plan(
        {
            "game": {
                "name": "Café Quest",
                "description": "Puzzle game",
                "tags": ["Puzzle"],
                "developer": "Studio",
                "languages": ["English"],
                "release_date": "2026-01-01",
                "website_url": "https://secret.example/game",
                "manual_overrides": {"contact": "private@example.com"},
                "source_identity": {"canonical_url": "https://source.example"},
            },
            "references": [
                {
                    "name": "Portal",
                    "reason": "Shared puzzle audience",
                    "similarities": ["Co-op puzzles"],
                    "url": "https://reference.example",
                    "opaque": "source-canary",
                }
            ],
            "metadata": {"api_key": "snapshot-secret"},
        },
        {
            "platforms": ["youtube", "x"],
            "keywords": ["gameplay"],
            "filters": {"languages": ["en"], "contact": "available"},
            "total_request_budget": 120,
            "base_url": "https://condition-secret.example",
            "tool": "fetch_url",
        },
        gateway=_gateway(handler),
        model="deepseek-chat",
    )

    messages = captured[0]["messages"]
    assert messages[1]["role"] == "system"
    assert "English" in messages[1]["content"]
    prompt_data = json.loads(messages[2]["content"])
    assert prompt_data == {
        "game": {
            "name": "Café Quest",
            "description": "Puzzle game",
            "tags": ["Puzzle"],
            "developer": "Studio",
            "languages": ["English"],
            "release_date": "2026-01-01",
        },
        "references": [
            {
                "name": "Portal",
                "reason": "Shared puzzle audience",
                "similarities": ["Co-op puzzles"],
            }
        ],
        "conditions": {
            "platforms": ["youtube", "x"],
            "keywords": ["gameplay"],
            "filters": {"languages": ["en"], "contact": "available"},
        },
    }
    rendered = json.dumps(messages)
    for secret in (
        "secret.example",
        "private@example.com",
        "source-canary",
        "snapshot-secret",
        "condition-secret",
        "fetch_url",
    ):
        assert secret not in rendered


def test_name_only_game_is_valid_context() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(
            json.dumps(
                {
                    "summary": "Use only the supplied game name.",
                    "rationale": "No other game facts were supplied.",
                    "queries": [{"platform": "youtube", "terms": ["Night's Fall"]}],
                }
            )
        )

    output = generate_plan(
        {"game": {"name": "Night's Fall", "website_url": "https://ignored.test"}},
        {"platforms": ["youtube"]},
        gateway=_gateway(handler),
        model="deepseek-chat",
    )

    assert calls == 1
    assert output.queries[0].terms == ["Night's Fall"]


def test_url_only_game_fails_before_model_io() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("model must not be called")

    with pytest.raises(PlanningInputError) as caught:
        generate_plan(
            {
                "game": {"website_url": "https://game.example"},
                "references": [{"name": "Known game"}],
            },
            {"platforms": ["youtube"]},
            gateway=_gateway(handler),
            model="deepseek-chat",
        )

    assert caught.value.code == "game_context_required"
    assert "https://game.example" not in str(caught.value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value | {"extra": "forbidden"},
        lambda value: value | {"summary": "x" * 1501},
        lambda value: value | {"queries": []},
        lambda value: value
        | {"queries": [{"platform": "youtube", "terms": ["one", "two", "three", "four"]}]},
        lambda value: value
        | {"queries": [{"platform": "youtube", "terms": ["site:evil.example"]}]},
        lambda value: value
        | {"queries": [{"platform": "youtube", "terms": ["line\nbreak"]}]},
        lambda value: value
        | {"queries": [{"platform": "youtube", "terms": ["tool_key"]}]},
    ],
)
def test_search_plan_schema_rejects_invalid_shape_and_unsafe_terms(mutate) -> None:
    with pytest.raises(ValidationError):
        SearchPlanOutput.model_validate(mutate(_valid_output()))


@pytest.mark.parametrize(
    "platforms,queries",
    [
        (["youtube", "x"], [{"platform": "youtube", "terms": ["Café Quest"]}]),
        (
            ["youtube", "x"],
            [
                {"platform": "youtube", "terms": ["Café Quest"]},
                {"platform": "youtube", "terms": ["gameplay"]},
            ],
        ),
        (["youtube"], [{"platform": "x", "terms": ["Café Quest"]}]),
    ],
)
def test_generate_plan_rejects_platform_mismatch_after_one_repair(platforms, queries) -> None:
    body = _valid_output() | {"queries": queries}
    calls = []
    def handler(request):
        calls.append(request)
        return _response(json.dumps(body))
    gateway = _gateway(handler)

    with pytest.raises(InvalidModelOutput, match="deepseek_model_output_invalid"):
        generate_plan(
            {"game": {"name": "Café Quest"}},
            {"platforms": platforms},
            gateway=gateway,
            model="deepseek-chat",
        )
    assert len(calls) == 2


@pytest.mark.parametrize("wrong_platforms", [["x"], ["youtube", "x"], ["youtube", "youtube"]])
def test_platform_mismatch_uses_existing_single_schema_repair(wrong_platforms):
    requests = []
    def handler(request):
        payload = json.loads(request.read())
        requests.append(payload)
        platforms = wrong_platforms if len(requests) == 1 else ["youtube"]
        body = _valid_output() | {"queries": [{"platform": p, "terms": ["LIMINAL Within"]} for p in platforms]}
        return _response(json.dumps(body))
    output = generate_plan(
        {"game": {"name": "LIMINAL: Within"}}, {"platforms": ["youtube"]},
        gateway=_gateway(handler), model="deepseek-chat",
    )
    assert [query.platform for query in output.queries] == ["youtube"]
    assert len(requests) == 2
    assert all(request["max_tokens"] == 2048 for request in requests)

def test_generate_plan_propagates_gateway_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(TransientIntegrationError, match="deepseek_unavailable"):
        generate_plan(
            {"game": {"name": "Café Quest"}},
            {"platforms": ["youtube"]},
            gateway=_gateway(handler),
            model="deepseek-chat",
        )


def test_generate_plan_propagates_truncated_output_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response('{"summary":"partial', finish_reason="length")

    with pytest.raises(TransientIntegrationError, match="deepseek_model_output_invalid"):
        generate_plan(
            {"game": {"name": "Café Quest"}},
            {"platforms": ["youtube"]},
            gateway=_gateway(handler),
            model="deepseek-chat",
        )

    assert calls == 1


def test_keyword_repair_explains_unsafe_title_punctuation_without_weakening_validation(caplog):
    requests = []
    invalid = {"summary": "Supplied puzzle game.", "rationale": "Search supplied title.",
               "queries": [{"platform": "youtube", "terms": ["LIMINAL: Within"]}]}
    valid = invalid | {"queries": [{"platform": "youtube", "terms": ["LIMINAL Within"]}]}

    def handler(request):
        payload = json.loads(request.read())
        requests.append(payload)
        if len(requests) == 1:
            return _response(json.dumps(invalid))
        repair = payload["messages"][-1]["content"]
        assert '"reason": "keyword_unsafe_query_syntax"' in repair
        assert "colons" in repair
        return _response(json.dumps(valid))

    output = generate_plan({"game": {"name": "LIMINAL: Within"}},
                           {"platforms": ["youtube"]}, gateway=_gateway(handler),
                           model="deepseek-v4-flash")
    assert len(requests) == 2
    assert output.queries[0].terms == ["LIMINAL Within"]
    assert "LIMINAL" not in caplog.text
    assert "keyword_unsafe_query_syntax" in caplog.text


@pytest.mark.parametrize("code,expected", [
    ("planning_platform_invalid", "planning_platform_invalid"),
    ("deepseek_response_invalid", "deepseek_response_invalid"),
    ("private-model-text", "unclassified"),
])
def test_planning_failure_log_keeps_allowlisted_cause_without_raw_exception(code, expected, caplog):
    from uuid import UUID
    from app.workers.planning_tasks import _log_failure

    _log_failure(UUID("00000000-0000-0000-0000-000000000001"), InvalidModelOutput(code),
                 "planning_model_output_invalid", 1)
    record = json.loads(caplog.records[-1].message)
    assert record["reason"] == expected
    assert record["attempt"] == 1
    assert "private-model-text" not in caplog.text
