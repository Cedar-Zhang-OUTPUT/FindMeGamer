"""Resumable public business contact extraction; never claim deliverability."""

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}", re.I)
BUSINESS = re.compile(
    r"business|inquir|contact|press|booking|sponsor|management|商务|合作|联系", re.I
)


class EnrichmentError(Exception):
    def __init__(self, code, *, retryable=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class PermanentIntegrationError(EnrichmentError):
    pass


class TransientIntegrationError(EnrichmentError):
    def __init__(self, code):
        super().__init__(code, retryable=True)


class ContactHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.links = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skipping += 1
        if tag == "a" and not self.skipping:
            href = dict(attrs).get("href", "")
            if href.startswith("mailto:"):
                self.text.append(href[7:].split("?")[0])
            elif BUSINESS.search(href):
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skipping = max(0, self.skipping - 1)

    def handle_data(self, data):
        if not self.skipping:
            self.text.append(data)


def extract(page):
    parser = ContactHTML()
    parser.feed(page.text)
    text = unescape(" ".join(parser.text))
    found = []
    seen = set()
    for match in EMAIL.finditer(text):
        address = match.group().lower()
        context = text[max(0, match.start() - 150) : match.end() + 150]
        if address not in seen and BUSINESS.search(context):
            seen.add(address)
            found.append(
                {
                    "email": address,
                    "purpose": "Public business contact",
                    "source_url": page.url,
                    "discovery_method": "public_page",
                    "verification_status": "publicly_listed_unverified_delivery",
                }
            )
    return found, parser.links


class Enricher:
    def __init__(self, pages, gemini):
        self.pages = pages
        self.gemini = gemini

    def public_contacts(self, target):
        try:
            page = self.pages.fetch_page(target["url"])
        except EnrichmentError as error:
            if error.code in {
                "public_page_url_invalid",
                "public_page_address_rejected",
                "public_page_redirect_invalid",
            }:
                raise
            # Unreadable public page may use search fallback; preserve diagnostic.
            return {"emails": [], "page_error": error.code}
        emails, links = extract(page)
        failures = []
        for link in list(dict.fromkeys(links))[:2] if not emails else []:
            try:
                linked = self.pages.fetch_page(urljoin(page.url, link))
                extra, _ = extract(linked)
                emails.extend(extra)
            except (EnrichmentError, ValueError) as error:
                failures.append(getattr(error, "code", "public_page_url_invalid"))
                continue
            if emails:
                break
        return {
            "emails": list({e["email"]: e for e in emails}.values()),
            "source_url": page.url,
            "page_error": failures[0] if failures and not emails else None,
        }


def run_job(store, job_id, enricher):
    lease = store.claim(job_id)
    if lease is None:
        return
    try:
        state = store.load(job_id)
        checkpoints = state["checkpoints"]
        public = checkpoints.get("public_pages")
        if public is None or public.get("page_error"):
            public = enricher.public_contacts(state["input"])
            if not store.checkpoint(job_id, lease, "public_pages", public):
                return
        emails = public["emails"]
        if not emails:
            enriched = checkpoints.get("enrichment")
            if enriched is None:
                from ..usage import Ledger

                ledger = Ledger(store.sessions)
                usage_id = "gemini:" + lease
                ledger.start(
                    usage_id,
                    state["token_id"],
                    state.get("run_id") or "unassigned",
                    "gemini",
                    "generateContent",
                )
                try:
                    enriched = enricher.gemini.find(state["input"])
                except Exception as error:
                    ledger.finish(
                        usage_id,
                        getattr(error, "code", "execution_unknown"),
                        usage=getattr(error, "usage", None),
                        model=getattr(enricher.gemini, "model", None),
                    )
                    raise
                enriched["cost"] = ledger.finish(
                    usage_id,
                    "succeeded",
                    usage=enriched.get("usage"),
                    model=getattr(enricher.gemini, "model", None),
                    resource_counts={"emails": len(enriched["emails"])},
                )
                if not store.checkpoint(job_id, lease, "enrichment", enriched):
                    return
            emails = enriched["emails"]
            if not emails and public.get("page_error"):
                raise EnrichmentError("public_pages_incomplete", retryable=True)
        store.complete(job_id, lease, emails)
    except EnrichmentError as error:
        store.fail(job_id, lease, error.code, retryable=error.retryable)
    except Exception:
        # Never persist third-party exception strings containing request secrets.
        store.fail(job_id, lease, "execution_failed", retryable=True)
