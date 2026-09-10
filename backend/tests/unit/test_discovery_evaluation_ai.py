import json
from uuid import UUID, uuid4

import httpx
import pytest

from app.discovery.evaluation_ai import EvaluationAI
from app.integrations.deepseek import DeepSeekGateway
from app.integrations.errors import InvalidModelOutput, TransientIntegrationError


def _gateway(responses):
    requests = []
    values = iter(responses)

    def handler(request):
        requests.append(json.loads(request.read()))
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(value)}}]},
        )

    gateway = DeepSeekGateway(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return EvaluationAI(gateway), requests


def _candidate(*, evidence=True, analysis_available=True):
    candidate_id = str(uuid4())
    work_id = str(uuid4())
    return {
        "candidate_id": candidate_id,
        "creator_brief": {"name": "Careful creator", "positioning": "Strategy videos"},
        "creator_detail": {"languages": ["English"], "country": None},
        "analysis": {"formats": ["reviews"]} if analysis_available else {},
        "works": [
            {
                "id": work_id,
                "title": "Tactical review",
                "work_name": "Tactical review",
                "content_type": "video",
                "game_id": str(uuid4()),
                "evidence_excerpt": (
                    "The recorded transcript discusses tactics" if evidence else ""
                ),
                "verification_notes": (
                    "Transcript retained in the known record" if evidence else ""
                ),
                "timestamp_seconds": 31,
            }
        ],
        "analysis_available": analysis_available,
    }


def _brief(candidate, *, confidence="supported", summary="Strong tactical topic fit"):
    return {
        "candidate_id": candidate["candidate_id"],
        "summary": summary,
        "content_fit": "Recorded evidence supports relevant strategy coverage",
        "audience_fit": "The known audience interests align; countries are unknown",
        "limitations": ["Audience country is unknown"],
        "cited_work_ids": [candidate["works"][0]["id"]],
        "confidence": confidence,
    }


def test_successful_three_stage_flow_uses_bounded_models_and_prompts():
    candidate = _candidate()
    brief = _brief(candidate)
    ai, requests = _gateway(
        [
            {"selected_ids": [candidate["candidate_id"]]},
            brief,
            {"items": [{"candidate_id": candidate["candidate_id"], "score": 82}]},
        ]
    )

    screened = ai.screen({"name": "Tactics"}, [candidate])
    deep = ai.deep({"name": "Tactics"}, candidate)
    ranked = ai.rank({"name": "Tactics"}, [deep.model_dump(mode="json")])

    assert screened.selected_ids == [UUID(candidate["candidate_id"])]
    assert deep.candidate_id == UUID(candidate["candidate_id"])
    assert ranked.items[0].score == 82
    assert [request["model"] for request in requests] == [
        "deepseek-flash",
        "deepseek-flash",
        "deepseek-flash",
    ]
    assert [request["max_tokens"] for request in requests] == [2048, 4096, 2048]
    screen_input = json.loads(requests[0]["messages"][-1]["content"])
    assert set(screen_input["candidates"][0]) == {"candidate_id", "creator_brief"}
    deep_input = json.loads(requests[1]["messages"][-1]["content"])
    assert "creator_detail" in deep_input["candidate"]
    rank_input = json.loads(requests[2]["messages"][-1]["content"])
    assert set(rank_input["briefs"][0]) == set(brief)
    assert all(
        message["role"] == "system" or message["role"] == "user"
        for request in requests
        for message in request["messages"]
    )


def test_screening_zero_is_a_valid_result():
    ai, _ = _gateway([{"selected_ids": []}])
    assert ai.screen({"name": "Game"}, [_candidate()]).selected_ids == []


@pytest.mark.parametrize("selected", ["unknown", "duplicate"])
def test_screen_rejects_unknown_or_duplicate_ids(selected):
    candidate = _candidate()
    value = str(uuid4()) if selected == "unknown" else candidate["candidate_id"]
    payload = [value] if selected == "unknown" else [value, value]
    ai, _ = _gateway([{"selected_ids": payload}])
    with pytest.raises(InvalidModelOutput, match="evaluation_screen_ids_invalid"):
        ai.screen({"name": "Game"}, [candidate])


def test_screen_rejects_oversized_chunk_before_io():
    ai, requests = _gateway([])
    with pytest.raises(ValueError, match="evaluation_screen_chunk_too_large"):
        ai.screen({"name": "Game"}, [_candidate() for _ in range(21)])
    assert requests == []


def test_rank_rejects_oversized_chunk_before_io():
    ai, requests = _gateway([])
    with pytest.raises(ValueError, match="evaluation_rank_chunk_too_large"):
        ai.rank({"name": "Game"}, [_brief(_candidate()) for _ in range(21)])
    assert requests == []


def test_rank_rejects_non_match_brief_fields_before_io():
    candidate = _candidate()
    brief = _brief(candidate)
    brief["baseURL"] = "https://attacker.invalid"
    ai, requests = _gateway([])
    with pytest.raises(ValueError, match="evaluation_brief_invalid"):
        ai.rank({"name": "Game"}, [brief])
    assert requests == []


@pytest.mark.parametrize(
    "mutation", ["wrong_candidate", "unknown_work", "duplicate_work"]
)
def test_deep_rejects_wrong_or_invented_ids(mutation):
    candidate = _candidate()
    brief = _brief(candidate)
    if mutation == "wrong_candidate":
        brief["candidate_id"] = str(uuid4())
    elif mutation == "unknown_work":
        brief["cited_work_ids"] = [str(uuid4())]
    else:
        brief["cited_work_ids"] *= 2
    ai, _ = _gateway([brief])
    with pytest.raises(InvalidModelOutput):
        ai.deep({"name": "Game"}, candidate)


def test_supported_requires_cited_record_with_excerpt_and_verification():
    candidate = _candidate(evidence=False)
    ai, _ = _gateway([_brief(candidate)])
    with pytest.raises(InvalidModelOutput, match="evaluation_evidence_invalid"):
        ai.deep({"name": "Game"}, candidate)


def test_deep_prompt_defines_supported_as_cited_evidence_not_thematic_fit():
    # Real-model regression: correct IDs and no unsafe narrative, but supported
    # was returned for metadata-only works. Keep rejection, align the prompt.
    candidate = _candidate(evidence=False)
    ai, requests = _gateway([_brief(candidate, confidence="limited")])
    assert ai.deep({"name": "Game"}, candidate).confidence == "limited"
    system = "\n".join(
        message["content"]
        for message in requests[0]["messages"]
        if message["role"] == "system"
    )
    assert "confidence='limited'" in system
    assert "confidence='supported'" in system
    assert "evidence_excerpt" in system and "verification_notes" in system
    assert "not a measure of thematic fit" in system
    payload = json.loads(requests[0]["messages"][-1]["content"])
    assert payload["candidate"]["supported_evidence_work_ids"] == []


def test_deep_supported_evidence_ids_are_derived_only_from_both_source_fields():
    candidate = _candidate(evidence=True)
    ai, requests = _gateway([_brief(candidate)])
    ai.deep({"name": "Game"}, candidate)
    payload = json.loads(requests[0]["messages"][-1]["content"])
    assert payload["candidate"]["supported_evidence_work_ids"] == [
        candidate["works"][0]["id"]
    ]


def test_metadata_only_limited_confidence_is_accepted():
    candidate = _candidate(evidence=False, analysis_available=False)
    brief = _brief(candidate, confidence="limited")
    brief["cited_work_ids"] = []
    ai, _ = _gateway([brief])
    assert ai.deep({"name": "Game"}, candidate).confidence == "limited"


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "See https://example.com/source",
        "Contact person@example.com",
        "Evidence at 01:23",
        "The creator played the game",
        "The sender watched the upload",
        "Viewing confirmed the fit",
    ],
)
def test_deep_rejects_unsafe_narrative_claims(unsafe_text):
    candidate = _candidate()
    ai, _ = _gateway([_brief(candidate, summary=unsafe_text)])
    with pytest.raises(InvalidModelOutput, match="evaluation_narrative_invalid"):
        ai.deep({"name": "Game"}, candidate)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_rank_requires_exact_unique_brief_membership(mutation):
    first, second = _candidate(), _candidate()
    briefs = [_brief(first), _brief(second)]
    ids = [first["candidate_id"], second["candidate_id"]]
    if mutation == "missing":
        items = [{"candidate_id": ids[0], "score": 60}]
    elif mutation == "extra":
        items = [
            {"candidate_id": ids[0], "score": 60},
            {"candidate_id": ids[1], "score": 50},
            {"candidate_id": str(uuid4()), "score": 40},
        ]
    else:
        items = [
            {"candidate_id": ids[0], "score": 60},
            {"candidate_id": ids[0], "score": 50},
        ]
    ai, _ = _gateway([{"items": items}])
    with pytest.raises(InvalidModelOutput, match="evaluation_rank_ids_invalid"):
        ai.rank({"name": "Game"}, briefs)


def test_truncated_invalid_json_fails_after_gateway_bounded_repair():
    candidate = _candidate()
    ai, requests = _gateway(["{", "still not json"])
    with pytest.raises(InvalidModelOutput, match="deepseek_model_output_invalid"):
        ai.screen({"name": "Game"}, [candidate])
    assert len(requests) == 2


def test_timeout_is_preserved_as_transient_without_adapter_retry():
    ai, requests = _gateway([httpx.ReadTimeout("timeout")])
    with pytest.raises(TransientIntegrationError, match="deepseek_unavailable"):
        ai.screen({"name": "Game"}, [_candidate()])
    assert len(requests) == 1
