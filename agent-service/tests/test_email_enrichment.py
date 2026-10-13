import json
from time import monotonic

import httpx
import pytest

from test_email_jobs import gateway, submit


class Resolver:
    def __init__(self, address="93.184.216.34"):
        self.address = address

    def resolve(self, hostname, port, **kwargs):
        return (self.address,)


def test_public_request_target_preserves_query_separators_and_encodes_unicode():
    from fmg_agent.email.public_pages import _ascii_request_target

    assert _ascii_request_target("/creator", "a=1&b=2") == "/creator?a=1&b=2"
    assert (
        _ascii_request_target("/空间", "q=two words")
        == "/%E7%A9%BA%E9%97%B4?q=two%20words"
    )


def test_failed_page_is_retried_when_model_also_failed(gateway):
    from fmg_agent.email.public_pages import PublicPage
    from fmg_agent.email.enrichment import Enricher, run_job, EnrichmentError
    from fmg_agent.email.jobs import JobStore

    app, client, token, _, _ = gateway
    job_id = submit(client, token).json()["data"]["id"]

    class Pages:
        recovered = False

        def fetch_page(self, url):
            if not self.recovered:
                raise EnrichmentError("public_page_unavailable", retryable=True)
            return PublicPage(url, "Business contact: team@example.com", "text/plain")

    class Gemini:
        def find(self, target):
            raise EnrichmentError("upstream_rate_limited", retryable=True)

    pages = Pages()
    store = JobStore(app.state.sessions)
    run_job(store, job_id, Enricher(pages, Gemini()))
    assert store.load(job_id)["state"] == "failed"
    pages.recovered = True
    store.retry(job_id, token.id)
    run_job(store, job_id, Enricher(pages, Gemini()))
    assert store.load(job_id)["state"] == "completed"
    assert store.load(job_id)["emails"][0]["email"] == "team@example.com"


def test_public_fetch_pins_dns_and_rejects_private_redirect():
    from fmg_agent.email.public_pages import PublicPageGateway, RawPageResponse
    from fmg_agent.email.enrichment import EnrichmentError

    class Transport:
        def request(self, **kwargs):
            assert kwargs["connect_ip"] == "93.184.216.34"
            assert kwargs["server_hostname"] == "example.com"
            return RawPageResponse(
                302, "text/html", None, "http://127.0.0.1/secret", ()
            )

    fetcher = PublicPageGateway(resolver=Resolver(), transport=Transport())
    with pytest.raises(EnrichmentError):
        fetcher.fetch_page("https://example.com/contact")


def test_private_dns_is_rejected_before_transport():
    from fmg_agent.email.public_pages import PublicPageGateway
    from fmg_agent.email.enrichment import EnrichmentError

    class Transport:
        def request(self, **kwargs):
            pytest.fail("private DNS reached network transport")

    fetcher = PublicPageGateway(resolver=Resolver("10.0.0.1"), transport=Transport())
    with pytest.raises(EnrichmentError):
        fetcher.fetch_page("https://example.com/contact")


def test_direct_business_contact_skips_gemini(gateway):
    from fmg_agent.email.public_pages import PublicPage
    from fmg_agent.email.enrichment import Enricher, run_job
    from fmg_agent.email.jobs import JobStore

    app, client, token, _, _ = gateway
    job_id = submit(client, token).json()["data"]["id"]

    class Pages:
        def fetch_page(self, url):
            return PublicPage(
                url, "<p>Business inquiries: press@example.com</p>", "text/html"
            )

    class Gemini:
        def find(self, target):
            pytest.fail("direct contact should not spend model quota")

    store = JobStore(app.state.sessions)
    run_job(store, job_id, Enricher(Pages(), Gemini()))
    result = store.load(job_id)
    assert result["state"] == "completed"
    assert result["emails"] == [
        {
            "email": "press@example.com",
            "purpose": "Public business contact",
            "source_url": "https://example.com/creator",
            "discovery_method": "public_page",
            "verification_status": "publicly_listed_unverified_delivery",
        }
    ]


def test_saved_api_evidence_skips_platform_page_and_model(gateway):
    from fmg_agent.email.enrichment import Enricher, run_job
    from fmg_agent.email.jobs import JobStore
    from test_email_jobs import headers

    app, client, token, _, _ = gateway
    response = client.post(
        "/v1/email/enrich",
        headers=headers(token),
        json={
            "url": "https://www.youtube.com/@creator",
            "evidence": [
                {
                    "source_url": "https://www.youtube.com/@creator",
                    "text": "Business contact: press@example.com",
                    "kind": "channel_description",
                }
            ],
        },
    )

    class Forbidden:
        def fetch_page(self, url):
            pytest.fail("API evidence must avoid platform HTML")

        def find(self, target):
            pytest.fail("API evidence must avoid model cost")

    store = JobStore(app.state.sessions)
    job_id = response.json()["data"]["id"]
    run_job(store, job_id, Enricher(Forbidden(), Forbidden()))
    result = store.load(job_id)
    assert result["state"] == "completed"
    assert result["emails"][0]["email"] == "press@example.com"
    assert result["emails"][0]["discovery_method"] == "provided_evidence"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@a",
        "https://m.youtube.com/@a",
        "https://youtu.be/abc",
        "https://x.com/a",
        "https://twitter.com/a",
        "https://www.twitch.tv/a",
    ],
)
def test_platform_hosts_skip_generic_html(url):
    from fmg_agent.email.enrichment import Enricher

    class Pages:
        def fetch_page(self, url):
            pytest.fail("platform HTML must not be fetched")

    result = Enricher(Pages(), None).public_contacts({"url": url, "platform": "other"})
    assert result["emails"] == []
    assert result["page_error"] is None
    assert result["platform_page_skipped"] is True


def test_evidence_contact_links_are_bounded_attributed_and_not_platform_pages():
    from fmg_agent.email.enrichment import Enricher
    from fmg_agent.email.public_pages import PublicPage

    calls = []

    class Pages:
        def fetch_page(self, url):
            calls.append(url)
            return PublicPage(url, "No listed contact.", "text/plain")

    result = Enricher(Pages(), None).public_contacts(
        {
            "url": "https://youtube.com/@a",
            "evidence": [
                {
                    "source_url": "https://youtube.com/@a",
                    "text": "Contact https://example.com/contact https://example.com/contact https://example.org/business https://example.net/press https://x.com/contact",
                }
            ],
        }
    )
    assert calls == ["https://example.com/contact", "https://example.org/business"]
    assert result["platform_page_skipped"] is True


def test_platform_label_cannot_hide_ordinary_hostname():
    from fmg_agent.email.enrichment import Enricher
    from fmg_agent.email.public_pages import PublicPage

    calls = []

    class Pages:
        def fetch_page(self, url):
            calls.append(url)
            return PublicPage(url, "Business: press@example.com", "text/plain")

    result = Enricher(Pages(), None).public_contacts(
        {"url": "https://youtube.com.example.org/contact", "platform": "youtube"}
    )
    assert calls == ["https://youtube.com.example.org/contact"]
    assert result["emails"][0]["email"] == "press@example.com"


def test_failed_gemini_retry_reuses_pages_and_returns_multiple_contacts(gateway):
    from fmg_agent.email.public_pages import PublicPage
    from fmg_agent.email.enrichment import Enricher, run_job, EnrichmentError
    from fmg_agent.email.jobs import JobStore

    app, client, token, _, _ = gateway
    job_id = submit(client, token).json()["data"]["id"]
    page_calls = []

    class Pages:
        def fetch_page(self, url):
            page_calls.append(url)
            return PublicPage(url, "<p>Gaming creator.</p>", "text/html")

    class FailedGemini:
        def find(self, target):
            raise EnrichmentError("upstream_rate_limited", retryable=True)

    class GoodGemini:
        def find(self, target):
            return {
                "emails": [
                    {
                        "email": "press@example.com",
                        "purpose": "Press",
                        "source_url": "https://example.com/press",
                        "discovery_method": "gemini",
                        "verification_status": "model_reported_unverified",
                    },
                    {
                        "email": "agency@example.com",
                        "purpose": "Management",
                        "source_url": "https://example.com/agency",
                        "discovery_method": "gemini",
                        "verification_status": "model_reported_unverified",
                    },
                ],
                "usage": {"totalTokenCount": 100},
            }

    store = JobStore(app.state.sessions)
    run_job(store, job_id, Enricher(Pages(), FailedGemini()))
    assert store.load(job_id)["state"] == "failed"
    assert store.load(job_id)["emails"] is None
    store.retry(job_id, token.id)
    run_job(store, job_id, Enricher(Pages(), GoodGemini()))
    result = store.load(job_id)
    assert result["state"] == "completed"
    assert [email["email"] for email in result["emails"]] == [
        "press@example.com",
        "agency@example.com",
    ]
    assert len(page_calls) == 1
    assert result["checkpoints"]["enrichment"]["usage"]["totalTokenCount"] == 100
    from fmg_agent.usage import Ledger

    summary = Ledger(app.state.sessions).summary(token.id, "unassigned")
    assert summary["providers"]["gemini"]["request_count"] == 2
    assert summary["providers"]["gemini"]["usage"] == {"totalTokenCount": 100}
    assert summary["providers"]["gemini"]["statuses"] == {
        "upstream_rate_limited": 1,
        "succeeded": 1,
    }


def test_gemini_response_retains_usage_and_rejects_invalid_or_truncated_output():
    from fmg_agent.email.gemini import parse_response
    from fmg_agent.email.enrichment import EnrichmentError

    payload = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "email_info": [
                                        {
                                            "email": "team@example.com",
                                            "usage": "Management",
                                            "source": "https://example.com/contact",
                                        }
                                    ]
                                }
                            )
                        }
                    ]
                },
            }
        ],
        "usageMetadata": {"totalTokenCount": 123},
    }
    result = parse_response(payload)
    assert result["emails"][0]["source_url"] == "https://example.com/contact"
    assert result["emails"][0]["verification_status"] == "model_reported_unverified"
    assert result["usage"]["totalTokenCount"] == 123
    payload["candidates"][0]["finishReason"] = "MAX_TOKENS"
    with pytest.raises(EnrichmentError, match="model_output_truncated"):
        parse_response(payload)
    payload["candidates"][0]["finishReason"] = "STOP"
    payload["candidates"][0]["content"]["parts"][0][
        "text"
    ] = '{"email_info":[{"email":"a@example.com","usage":"Business","source":"http://127.0.0.1"}]}'
    with pytest.raises(EnrichmentError, match="model_output_invalid"):
        parse_response(payload)


def test_gemini_request_is_bounded_and_auth_redacted():
    from fmg_agent.email.gemini import GeminiGateway
    from fmg_agent.email.enrichment import EnrichmentError

    def upstream(request):
        assert request.headers["x-goog-api-key"] == "test-key"
        assert "test-key" not in str(request.url)
        data = json.loads(request.content)
        assert data["tools"] == [{"googleSearch": {}}, {"urlContext": {}}]
        assert "public business" in data["systemInstruction"]["parts"][0]["text"]
        return httpx.Response(429, json={"error": {"message": "test-key"}})

    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        gateway = GeminiGateway("test-key", "test-model", client=client)
        with pytest.raises(EnrichmentError) as error:
            gateway.find({"url": "https://example.com/creator", "name": "Creator"})
        assert error.value.code == "upstream_rate_limited"
        assert "test-key" not in str(error.value)


def empty_grounded_payload():
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": '{"email_info":[]}'}]},
                "groundingMetadata": {
                    "webSearchQueries": ["creator contact"],
                    "groundingChunks": [
                        {"web": {"uri": "https://example.org/creator"}}
                    ],
                },
            }
        ],
        "usageMetadata": {"totalTokenCount": 25},
    }


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "no_queries",
        "no_sources",
        "failed_url",
        "missing_metadata",
        "malformed_metadata",
    ],
)
def test_empty_platform_fallback_requires_observable_search_coverage(gateway, fault):
    from fmg_agent.email.gemini import parse_response
    from fmg_agent.email.enrichment import Enricher, run_job
    from fmg_agent.email.jobs import JobStore

    app, client, token, _, _ = gateway
    job_id = submit(client, token, url="https://youtube.com/@creator").json()["data"][
        "id"
    ]
    payload = empty_grounded_payload()
    candidate = payload["candidates"][0]
    if fault == "no_queries":
        candidate["groundingMetadata"]["webSearchQueries"] = []
    if fault == "no_sources":
        candidate["groundingMetadata"]["groundingChunks"] = []
    if fault == "failed_url":
        candidate["urlContextMetadata"] = {
            "urlMetadata": [
                {
                    "retrievedUrl": "https://example.org/contact",
                    "urlRetrievalStatus": "URL_RETRIEVAL_STATUS_ERROR",
                }
            ]
        }
    if fault == "missing_metadata":
        candidate.pop("groundingMetadata")
    if fault == "malformed_metadata":
        candidate["groundingMetadata"] = {
            "webSearchQueries": 1,
            "groundingChunks": "bad",
        }
    calls = []

    class Pages:
        def fetch_page(self, url):
            pytest.fail("platform page not required")

    class Gemini:
        def find(self, target):
            calls.append(target)
            return parse_response(payload)

    store = JobStore(app.state.sessions)
    run_job(store, job_id, Enricher(Pages(), Gemini()))
    result = store.load(job_id)
    assert result["state"] == ("completed" if fault is None else "failed")
    if fault:
        assert result["error"]["code"] == "enrichment_search_incomplete"
        store.retry(job_id, token.id)
        run_job(store, job_id, Enricher(Pages(), Gemini()))
        assert len(calls) == 1, "retry must reuse the new-version unresolved checkpoint"


def test_legacy_empty_checkpoint_gets_one_fresh_search_and_keeps_historical_usage(
    gateway,
):
    from fmg_agent.email.gemini import parse_response
    from fmg_agent.email.enrichment import Enricher, run_job
    from fmg_agent.email.jobs import JobStore
    from fmg_agent.usage import Ledger

    app, client, token, _, _ = gateway
    job_id = submit(client, token, url="https://youtube.com/@creator").json()["data"][
        "id"
    ]
    store = JobStore(app.state.sessions)
    lease = store.claim(job_id)
    store.checkpoint(
        job_id,
        lease,
        "public_pages",
        {"emails": [], "page_error": "public_page_too_large"},
    )
    store.checkpoint(
        job_id, lease, "enrichment", {"emails": [], "usage": {"totalTokenCount": 100}}
    )
    ledger = Ledger(app.state.sessions)
    ledger.start("old-search", token.id, "unassigned", "gemini", "generateContent")
    ledger.finish("old-search", "succeeded", usage={"totalTokenCount": 100})
    store.fail(job_id, lease, "public_pages_incomplete", retryable=True)
    store.retry(job_id, token.id)
    calls = []

    class Pages:
        def fetch_page(self, url):
            pytest.fail("legacy platform HTML should not repeat")

    class Gemini:
        def find(self, target):
            calls.append(target)
            return parse_response(empty_grounded_payload())

    run_job(store, job_id, Enricher(Pages(), Gemini()))
    result = store.load(job_id)
    assert result["state"] == "completed"
    assert len(calls) == 1
    assert result["id"] == job_id
    usage = ledger.summary(token.id, "unassigned")["providers"]["gemini"]
    assert usage["request_count"] == 2
    assert usage["usage"]["totalTokenCount"] == 125


def test_contact_redirect_to_platform_is_skipped_before_platform_transport():
    from fmg_agent.email.enrichment import Enricher
    from fmg_agent.email.public_pages import PublicPageGateway, RawPageResponse

    calls = []

    class Transport:
        def request(self, **kwargs):
            calls.append(kwargs["server_hostname"])
            if len(calls) == 1:
                return RawPageResponse(
                    302, "text/html", None, "https://youtube.com/@creator", ()
                )
            return RawPageResponse(200, "text/html", 300000, None, ())

    pages = PublicPageGateway(resolver=Resolver(), transport=Transport())
    result = Enricher(pages, None).public_contacts(
        {"url": "https://example.org/contact"}
    )
    assert calls == ["example.org"]
    assert result["page_error"] is None
    assert result["platform_page_skipped"] is True


@pytest.mark.parametrize("code", ["model_output_invalid", "execution_interrupted"])
def test_legacy_refresh_failure_cannot_repeat_model_spending(gateway, code):
    from fmg_agent.email.enrichment import Enricher, EnrichmentError, run_job
    from fmg_agent.email.jobs import JobStore
    from fmg_agent.usage import Ledger

    app, client, token, _, _ = gateway
    job_id = submit(client, token, url="https://youtube.com/@creator").json()["data"][
        "id"
    ]
    store = JobStore(app.state.sessions)
    lease = store.claim(job_id)
    store.checkpoint(
        job_id,
        lease,
        "public_pages",
        {"emails": [], "page_error": "public_page_too_large"},
    )
    store.checkpoint(job_id, lease, "enrichment", {"emails": []})
    store.fail(job_id, lease, "public_pages_incomplete", retryable=True)
    calls = []

    class Pages:
        def fetch_page(self, url):
            pytest.fail("platform page not required")

    class Gemini:
        def find(self, target):
            calls.append(target)
            raise EnrichmentError(code, retryable=True)

    for _ in range(2):
        store.retry(job_id, token.id)
        run_job(store, job_id, Enricher(Pages(), Gemini()))
        assert store.load(job_id)["state"] == "failed"
    assert len(calls) == 1
    assert (
        Ledger(app.state.sessions).summary(token.id, "unassigned")["providers"][
            "gemini"
        ]["request_count"]
        == 1
    )


def test_malformed_embedded_link_does_not_discard_known_email():
    from fmg_agent.email.enrichment import Enricher

    result = Enricher(None, None).public_contacts(
        {
            "url": "https://youtube.com/@creator",
            "evidence": [
                {
                    "source_url": "https://youtube.com/@creator",
                    "text": "Business email team@example.com; contact https://[broken/contact",
                }
            ],
        }
    )
    assert result["emails"][0]["email"] == "team@example.com"


def test_failed_legacy_refresh_is_not_empty_completion_on_ordinary_site(gateway):
    from fmg_agent.email.enrichment import Enricher, run_job
    from fmg_agent.email.jobs import JobStore

    app, client, token, _, _ = gateway
    job_id = submit(client, token).json()["data"]["id"]
    store = JobStore(app.state.sessions)
    lease = store.claim(job_id)
    store.checkpoint(
        job_id,
        lease,
        "public_pages",
        {"emails": [], "source_url": "https://example.com/creator"},
    )
    store.checkpoint(
        job_id,
        lease,
        "enrichment",
        {
            "emails": [],
            "checkpoint_version": 2,
            "legacy_refresh_attempt": "failed",
            "attempt_error": "model_output_invalid",
            "coverage": {"search_completed": False},
        },
    )
    store.fail(job_id, lease, "model_output_invalid", retryable=True)
    store.retry(job_id, token.id)
    run_job(store, job_id, Enricher(None, None))
    assert store.load(job_id)["state"] == "failed"
