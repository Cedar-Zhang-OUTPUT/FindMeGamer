"""Subprocess fixture: real Celery; only external page/model inputs simulated."""

import os

from fmg_agent.config import Settings
from fmg_agent.email.enrichment import Enricher, EnrichmentError
from fmg_agent.email.public_pages import PublicPage
from fmg_agent.worker import create_worker


class Pages:
    def fetch_page(self, url):
        if os.environ["FMG_FIXTURE_PHASE"] == "resume":
            raise AssertionError("successful public page checkpoint was not reused")
        return PublicPage(url, "<p>Gaming creator</p>", "text/html")


class Gemini:
    def find(self, target):
        if os.environ["FMG_FIXTURE_PHASE"] == "fail":
            raise EnrichmentError("upstream_rate_limited", retryable=True)
        return {
            "emails": [
                {
                    "email": "press@example.com",
                    "purpose": "Press",
                    "source_url": "https://example.com/contact",
                    "discovery_method": "gemini",
                    "verification_status": "model_reported_unverified",
                }
            ],
            "usage": {"totalTokenCount": 123},
        }


if __name__ == "__main__":
    worker = create_worker(
        Settings(), enricher_factory=lambda: Enricher(Pages(), Gemini())
    )
    worker.worker_main(
        [
            "worker",
            "--queues=fmg_agent",
            "--pool=solo",
            "--concurrency=1",
            "--loglevel=WARNING",
            "--without-gossip",
            "--without-mingle",
        ]
    )
