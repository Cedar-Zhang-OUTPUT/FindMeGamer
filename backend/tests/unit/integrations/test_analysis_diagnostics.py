import json
import logging
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel

from app.analysis.contracts import Message
from app.core.analysis_diagnostics import diagnostic_context, traced_node
from app.integrations.deepseek import DeepSeekGateway
from app.integrations.errors import InvalidModelOutput


class DiagnosticResult(BaseModel):
    title: str


def events(caplog):
    return [
        json.loads(r.message)
        for r in caplog.records
        if r.name == "app.core.analysis_diagnostics"
    ]


def test_nonlength_failures_have_per_call_metadata_without_private_content(caplog):
    caplog.set_level(logging.INFO)
    logging.getLogger("app.core.analysis_diagnostics").disabled = False
    secret = "PRIVATE-CONTENT-person@example.com"
    body = json.dumps({"title": 42})
    gateway = DeepSeekGateway(
        api_key=secret,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {"finish_reason": "stop", "message": {"content": body}}
                        ],
                        "usage": {
                            "prompt_tokens": 12,
                            "completion_tokens": 8,
                            "total_tokens": 20,
                        },
                    },
                )
            )
        ),
    )
    job, search, creator = map(str, (uuid4(), uuid4(), uuid4()))
    with diagnostic_context(
        job_id=job, search_id=search, creator_id=creator, node_key="batch:v1:00"
    ):
        with pytest.raises(InvalidModelOutput):
            gateway.complete_structured(
                "deepseek-flash",
                [Message(role="user", content=secret)],
                DiagnosticResult,
                max_tokens=2048,
            )
    ends = [e for e in events(caplog) if e["event"] == "model_call_finished"]
    assert len(ends) == 2
    assert {e["attempt"] for e in ends} == {"initial", "repair"}
    assert len({e["call_id"] for e in ends}) == 2
    for e in ends:
        assert (e["job_id"], e["search_id"], e["creator_id"], e["node_key"]) == (
            job,
            search,
            creator,
            "batch:v1:00",
        )
        assert e["finish_reason"] == "stop"
        assert e["output_bytes"] == len(body.encode())
        assert e["max_tokens"] == 2048 and e["usage"]["total_tokens"] == 20
        assert e["category"] == "schema" and e["validation_error_count"] == 1
        assert e["duration_ms"] >= 0
    assert secret not in caplog.text


def test_thread_context_is_explicit_and_all_failures_are_logged(caplog):
    from contextvars import copy_context

    caplog.set_level(logging.INFO)
    logging.getLogger("app.core.analysis_diagnostics").disabled = False
    ids = [str(uuid4()), str(uuid4())]

    def fail():
        raise ValueError("SECRET-response@example.com")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        for job in ids:
            with diagnostic_context(job_id=job):
                futures.append(
                    pool.submit(copy_context().run, traced_node, "batch:v1:00", fail)
                )
        for future in futures:
            with pytest.raises(ValueError):
                future.result()
    failures = [e for e in events(caplog) if e["event"] == "analysis_node_finished"]
    assert {e["job_id"] for e in failures} == set(ids)
    assert all(e["status"] == "failed" for e in failures)
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize(
    "kind,expected,count", [("json", "json", 2), ("timeout", "network_timeout", 1)]
)
def test_response_failures_have_safe_categories(caplog, kind, expected, count):
    caplog.set_level(logging.INFO)
    logging.getLogger("app.core.analysis_diagnostics").disabled = False

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("SECRET-provider-content", request=request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "SECRET-invalid-json"},
                    }
                ]
            },
        )

    gateway = DeepSeekGateway(
        api_key="secret-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    from app.integrations.errors import TransientIntegrationError

    with pytest.raises((InvalidModelOutput, TransientIntegrationError)):
        gateway.complete_structured("deepseek-flash", [], DiagnosticResult)
    ends = [e for e in events(caplog) if e["event"] == "model_call_finished"]
    assert len(ends) == count and all(e["category"] == expected for e in ends)
    assert "SECRET" not in caplog.text and "secret-key" not in caplog.text


def test_counts_include_errors_beyond_eight_and_creator_ref_is_private(caplog):
    from pydantic import ConfigDict

    class ManyErrors(BaseModel):
        model_config = ConfigDict(extra="forbid")
        title: str

    caplog.set_level(logging.INFO)
    logging.getLogger("app.core.analysis_diagnostics").disabled = False
    content = json.dumps(
        {"title": 1, **{f"SECRET-{i}": "person@example.com" for i in range(12)}}
    )
    gateway = DeepSeekGateway(
        api_key="key",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"choices": [{"message": {"content": content}}]}
                )
            )
        ),
    )
    with diagnostic_context(creator_target="UC-PRIVATE-CREATOR"):
        with pytest.raises(InvalidModelOutput):
            gateway.complete_structured("deepseek-flash", [], ManyErrors)
    ends = [e for e in events(caplog) if e["event"] == "model_call_finished"]
    assert all(
        e["validation_error_count"] == 13
        and sum(e["validation_reason_counts"].values()) == 13
        and len(e["validation_errors"]) == 8
        for e in ends
    )
    assert len(ends[0]["creator_ref"]) == 64
    assert all(
        marker not in caplog.text
        for marker in ("SECRET", "person@example.com", "UC-PRIVATE-CREATOR")
    )


@pytest.mark.parametrize(
    "content,expected", [("private-invalid-json", "json"), ('{"wrong": []}', "schema")]
)
def test_gemini_attempts_are_correlated_and_categorized(caplog, content, expected):
    from app.analysis.contracts import CreatorSource
    from app.integrations.gemini_email import GeminiEmailResearchGateway
    from app.integrations.errors import PermanentIntegrationError

    caplog.set_level(logging.INFO)
    logging.getLogger("app.core.analysis_diagnostics").disabled = False

    def handler(_):
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": content}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 3,
                    "totalTokenCount": 15,
                },
            },
        )

    gateway = GeminiEmailResearchGateway(
        api_key="PRIVATE-GEMINI-KEY",
        sleep=lambda _: None,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(PermanentIntegrationError):
        gateway.find_public_emails(
            CreatorSource(
                channel_id="UC123456",
                canonical_url="https://www.youtube.com/channel/UC123456",
                title="Synthetic Creator",
                description="Public gaming",
                uploads_playlist_id="UU123456",
                videos=(),
                raw_channel={},
                raw_playlist_pages=(),
                raw_video_responses=(),
            )
        )
    ends = [e for e in events(caplog) if e["event"] == "model_call_finished"]
    assert len(ends) == 4
    assert [e["request_attempt"] for e in ends] == [1, 2, 3, 4]
    assert all(
        e["category"] == expected
        and e["finish_reason"] == "STOP"
        and e["usage"]["total_tokens"] == 15
        for e in ends
    )
    assert (
        "private-invalid-json" not in caplog.text
        and "PRIVATE-GEMINI-KEY" not in caplog.text
    )
