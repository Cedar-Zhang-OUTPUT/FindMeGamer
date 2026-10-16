"""Subprocess fixture: real Celery; only external page/model inputs simulated."""

import os

from fmg_agent.config import Settings
from fmg_agent.email.enrichment import Enricher, EnrichmentError
from fmg_agent.email.public_pages import PublicPage
from fmg_agent import worker as workers


def create_worker(*args, **kwargs):
    worker = original_create_worker(*args, **kwargs)
    worker.conf.broker_transport_options["global_keyprefix"] = os.environ[
        "FMG_FIXTURE_PREFIX"
    ]
    return worker


original_create_worker = workers.create_worker
workers.create_worker = create_worker


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
    import sys
    from fmg_agent.worker import worker_args
    from fmg_agent.db import database
    from fmg_agent.mail_runtime import check_readiness

    settings = Settings()
    engine, sessions = database(settings)
    check_readiness(settings, sessions)
    engine.dispose()
    role = sys.argv[1]
    if role == "dispatch":
        from fmg_agent.dispatch import main

        main()
        raise SystemExit()
    mailbox = "ontologyplay" if role == "mail" else None
    worker = create_worker(
        settings,
        role=role,
        mailbox_id=mailbox,
        enricher_factory=lambda: Enricher(Pages(), Gemini()),
    )
    worker.worker_main(
        [
            *worker_args(role, mailbox),
            "--pool=solo",
            "--loglevel=WARNING",
            "--without-gossip",
            "--without-mingle",
        ]
    )
