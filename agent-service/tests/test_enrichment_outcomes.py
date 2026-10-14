import json

import pytest

from test_email_jobs import gateway, submit
from fmg_agent.email.enrichment import Enricher, EnrichmentError, run_job
from fmg_agent.email.gemini import parse_response
from fmg_agent.email.jobs import JobStore


def payload(records):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": json.dumps({"email_info": records})}]},
            }
        ],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
    }


@pytest.mark.parametrize("source", [None, "", "http://127.0.0.1/private"])
def test_valid_email_without_usable_source_is_found_and_unverified(source):
    result = parse_response(
        payload(
            [{"email": "Creator@Example.org", "usage": "Business", "source": source}]
        )
    )
    assert result["emails"][0]["email"] == "creator@example.org"
    assert result["emails"][0]["source_url"] is None
    assert result["emails"][0]["verification_status"] == "model_reported_unverified"


def test_optional_source_can_be_omitted():
    assert (
        parse_response(
            payload([{"email": "creator@example.org", "usage": "Business"}])
        )["emails"][0]["source_url"]
        is None
    )


@pytest.mark.parametrize(
    "records", [[], [{"email": "creator@example.org", "usage": "Business"}]]
)
@pytest.mark.parametrize(
    "metadata",
    [
        {"groundingMetadata": {"groundingChunks": [{"web": {"uri": 42}}]}},
        {
            "urlContextMetadata": {
                "urlMetadata": [
                    {
                        "retrievedUrl": 42,
                        "urlRetrievalStatus": "URL_RETRIEVAL_STATUS_SUCCESS",
                    }
                ]
            }
        },
    ],
)
def test_malformed_optional_url_diagnostics_do_not_discard_valid_results(
    records, metadata
):
    response = payload(records)
    response["candidates"][0].update(metadata)
    result = parse_response(response)
    assert len(result["emails"]) == len(records)
    assert result["coverage"]["search_completed"] is False


@pytest.mark.parametrize(
    "fault", ["missing_coverage", "failed_retrieval", "page_error"]
)
def test_normal_empty_response_completes_not_found_despite_missing_sources(
    gateway, fault
):
    app, client, token, _, _ = gateway
    job = submit(client, token, url="https://youtube.com/@creator").json()["data"]
    result = parse_response(payload([]))
    if fault == "failed_retrieval":
        result["coverage"]["retrieval_failed"] = True

    class Pages:
        def public_contacts(self, target):
            return {
                "emails": [],
                "platform_page_skipped": True,
                "page_error": (
                    "public_page_unavailable" if fault == "page_error" else None
                ),
            }

    class Gemini:
        def find(self, target):
            return result

    enricher = Enricher(None, Gemini())
    enricher.public_contacts = Pages().public_contacts
    store = JobStore(app.state.sessions)
    run_job(store, job["id"], enricher)
    saved = store.load(job["id"])
    assert saved["state"] == "completed"
    assert saved["outcome"] == "not_found"
    assert saved["emails"] == []


def test_historical_valid_empty_checkpoint_is_reused_without_model_spend(gateway):
    app, client, token, _, _ = gateway
    job = submit(client, token, url="https://youtube.com/@creator").json()["data"]
    store = JobStore(app.state.sessions)
    lease = store.claim(job["id"])
    old = {
        "emails": [],
        "coverage": {"search_completed": False},
        "usage": {"totalTokenCount": 42},
    }
    store.checkpoint(job["id"], lease, "enrichment", old)
    store.fail(job["id"], lease, "enrichment_search_incomplete", retryable=False)
    store.retry(job["id"], token.id)

    class Forbidden:
        def find(self, target):
            pytest.fail("Valid cached empty result must not repeat paid work")

    run_job(store, job["id"], Enricher(None, Forbidden()))
    result = store.load(job["id"])
    assert result["state"] == "completed" and result["outcome"] == "not_found"
    assert result["checkpoints"]["enrichment"] == old


@pytest.mark.parametrize(
    "code",
    [
        "upstream_rate_limited",
        "upstream_request_rejected",
        "upstream_connection_failed",
        "model_output_invalid",
    ],
)
def test_real_call_errors_remain_failed_not_not_found(gateway, code):
    app, client, token, _, _ = gateway
    job = submit(client, token, url="https://youtube.com/@creator").json()["data"]

    class Gemini:
        def find(self, target):
            raise EnrichmentError(code, retryable=True)

    store = JobStore(app.state.sessions)
    run_job(store, job["id"], Enricher(None, Gemini()))
    result = store.load(job["id"])
    assert result["state"] == "failed" and result["error"]["code"] == code
    assert result.get("outcome") is None


@pytest.mark.parametrize("marker", ["started", "failed"])
def test_failed_attempt_marker_is_not_reused_as_a_valid_empty_result(gateway, marker):
    app, client, token, _, _ = gateway
    job = submit(client, token, url="https://youtube.com/@creator").json()["data"]
    store = JobStore(app.state.sessions)
    lease = store.claim(job["id"])
    store.checkpoint(
        job["id"],
        lease,
        "enrichment",
        {
            "emails": [],
            "legacy_refresh_attempt": marker,
            "attempt_error": "upstream_request_rejected",
        },
    )
    store.fail(job["id"], lease, "upstream_request_rejected", retryable=False)
    calls = []

    class Gemini:
        def find(self, target):
            calls.append(target)
            raise EnrichmentError("upstream_rate_limited", retryable=True)

    for _ in range(2):
        store.retry(job["id"], token.id)
        run_job(store, job["id"], Enricher(None, Gemini()))
        result = store.load(job["id"])
        assert result["state"] == "failed" and result.get("outcome") is None
    assert len(calls) == 1
    assert result["error"]["code"] == "upstream_rate_limited"


@pytest.mark.parametrize("marker", ["started", "failed"])
def test_current_attempt_markers_cannot_charge_again_or_complete_empty(gateway, marker):
    app, client, token, _, _ = gateway
    job = submit(client, token, url="https://youtube.com/@creator").json()["data"]
    store = JobStore(app.state.sessions)
    lease = store.claim(job["id"])
    store.checkpoint(
        job["id"],
        lease,
        "enrichment",
        {
            "emails": [],
            "legacy_refresh_attempt": marker,
            "outcome_rule_version": 1,
        },
    )
    store.fail(job["id"], lease, "execution_interrupted", retryable=True)
    store.retry(job["id"], token.id)

    class Forbidden:
        def find(self, target):
            pytest.fail(
                "Current attempt marker must not repeat a potentially charged call"
            )

    run_job(store, job["id"], Enricher(None, Forbidden()))
    result = store.load(job["id"])
    assert result["state"] == "failed" and result["outcome"] is None
    assert result["error"]["code"] == "enrichment_attempt_incomplete"
