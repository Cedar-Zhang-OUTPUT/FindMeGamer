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
