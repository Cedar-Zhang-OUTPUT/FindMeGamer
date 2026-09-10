import json
import httpx
import pytest

from app.outreach.draft_ai import DraftAI
from app.integrations.deepseek import DeepSeekGateway
from app.integrations.errors import IntegrationError, InvalidModelOutput


def data():
    return {
        "public_name": "Alex",
        "channel_name": "Film Games",
        "reference": "Station review",
        "work": {
            "evidence_excerpt": "A quiet station is contrasted with a sudden reveal.",
            "verification_notes": "Editor recorded the scene.",
            "source_url": "https://example.com/watch",
        },
        "game": {"name": "LIMINAL", "description": "Interactive film"},
        "missing_fields": [],
        "selected_contact": {"email": "private@example.com"},
        "sender": {"username": "sender@example.com"},
    }


def output():
    return {
        "firstName": "Alex",
        "channelName": "Film Games",
        "reference": "Station review",
        "observation": "contrasted the quiet station with a sudden reveal.",
    }


def gateway(value):
    requests = []

    def handler(request):
        requests.append(json.loads(request.read()))
        if isinstance(value, Exception):
            raise value
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(value)}}]}
        )

    return (
        DraftAI(
            DeepSeekGateway(
                api_key="fixture",
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )
        ),
        requests,
    )


def test_four_slot_http_generation_is_bounded_and_has_no_contact_or_sender_payload():
    ai, requests = gateway(output())
    assert ai.generate(data()).model_dump() == output()
    assert (
        requests[0]["max_tokens"] == 2048
        and requests[0]["model"] == "deepseek-flash"
    )
    encoded = json.dumps(requests)
    assert "private@example.com" not in encoded and "sender@example.com" not in encoded
    assert "https://example.com/watch" not in encoded
    assert any(
        "untrusted" in message["content"]
        for message in requests[0]["messages"]
        if message["role"] == "system"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"firstName": "Invented"},
        {"channelName": "Other"},
        {"reference": "Other video"},
        {"source_url": "https://invented.invalid"},
        {"observation": ""},
        {"observation": "Missing period"},
    ],
)
def test_model_cannot_replace_bound_identities_or_expand_output(change):
    ai, _ = gateway(output() | change)
    with pytest.raises((InvalidModelOutput, IntegrationError)):
        ai.generate(data())


def test_missing_recorded_evidence_does_not_call_model():
    ai, requests = gateway(output())
    with pytest.raises(ValueError):
        ai.generate(data() | {"missing_fields": ["observation_evidence_missing"]})
    assert not requests


def test_model_timeout_is_propagated_for_per_member_failure():
    ai, _ = gateway(httpx.ReadTimeout("fixture timeout"))
    with pytest.raises(IntegrationError):
        ai.generate(data())
