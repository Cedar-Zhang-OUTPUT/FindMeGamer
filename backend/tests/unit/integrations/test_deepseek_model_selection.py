import importlib

import httpx
import pytest
from pydantic import BaseModel

from app.integrations.deepseek import DeepSeekGateway


class Answer(BaseModel):
    value: str


@pytest.mark.parametrize(
    "model",
    [
        "deepseek-flash",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
        "deepseek-v4-pro",
    ],
)
def test_known_historical_aliases_and_repairs_send_current_model(model):
    requests = []

    def respond(request):
        import json

        requests.append(json.loads(request.content))
        content = '{"value":4}' if len(requests) == 1 else '{"value":"ok"}'
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}]
            },
        )

    gateway = DeepSeekGateway(
        api_key="test-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert gateway.complete_structured(model, [], Answer).value == "ok"
    assert [request["model"] for request in requests] == [
        "deepseek-flash",
        "deepseek-flash",
    ]
    assert all(request["thinking"] == {"type": "disabled"} for request in requests)


@pytest.mark.parametrize(
    "module,names",
    [
        (
            "app.analysis.game_pipeline",
            ["EXTRACTION_MODEL", "VISION_MODEL", "SYNTHESIS_MODEL"],
        ),
        (
            "app.analysis.creator_pipeline",
            ["METADATA_MODEL", "VISION_MODEL", "SYNTHESIS_MODEL"],
        ),
        (
            "app.analysis.creator_map_reduce_pipeline",
            ["MAP_MODEL", "REDUCTION_MODEL", "BRIEF_MODEL"],
        ),
        ("app.matching.screening", ["SCREENING_MODEL"]),
        ("app.matching.pairwise", ["PAIRWISE_MODEL"]),
        ("app.matching.ranking", ["RANKING_MODEL"]),
    ],
)
def test_all_stage_defaults_use_flash_including_vision_and_former_pro(module, names):
    loaded = importlib.import_module(module)
    assert {getattr(loaded, name) for name in names} == {"deepseek-flash"}
