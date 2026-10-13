# API-evidence-first email enrichment

Status: design and implementation plan approved on 2026-10-13. Backend/CLI/Skill
implementation tested and backend deployed; public release acceptance in progress.
Failed-job recovery stopped at canary because the upstream provider rejected work.

## Intent and approved scope

Reduce the YouTube-page-size failures in creator email enrichment, reuse the
public evidence already obtained during research, and retain honest distinctions
between an unavailable email and an incomplete lookup. Update the backend, CLI
and both distributed Skills together; test, deploy, publish an upgradeable bundle,
then reprocess the failed enrichment jobs from the affected research run.

This does not authorize email delivery. Do not approve/resume outreach tasks,
release sender holds, alter email templates, disable reply/bounce monitoring, or
change the existing worker concurrency of two. Keep local Docker stopped.

## Existing behavior and root cause

Creator research uses platform APIs. The separate enrichment endpoint currently
accepts only `url`, optional `name`, and optional `platform`. It downloads the
target page, optionally follows two contact links, then uses Gemini Google Search
and URL Context if no email was extracted. Public page fetches have a 256,000-byte
limit. YouTube channel HTML frequently exceeds it.

If that page failed and Gemini returned an empty list, the job becomes
`public_pages_incomplete`. Retrying currently fetches the same page and reuses the
old empty Gemini checkpoint, reproducing the failure. Neither that failure nor
an unverified model suggestion establishes email absence or deliverability.

## Interface and evidence reuse

Preserve existing `fmg email enrich --url ... --idempotency-key ...` invocations.
Add an optional `--evidence FILE` JSON file and an optional `evidence` array to the
existing backend request. Each record contains `source_url` and `text`, with
optional `kind` identifying channel description, video description, or another
public profile excerpt. Unknown fields are rejected.

Bound the array to ten records, each text to 8,000 characters, and all evidence
text combined to 32,000 characters; validate public HTTP(S) source URLs using the
existing URL rules. The CLI bounds file reads to 256,000 bytes and reports invalid
files before submission. Do not let evidence supply provider instructions,
credentials, guessed addresses, or hidden/private contact data.

Keep evidence in the job's existing JSON input; no schema migration is needed.
Evidence is part of the idempotent input: modifying it under an existing key must
still conflict. Old clients remain supported. New CLI help and error messages
explain an older server rejecting the optional field rather than silently
discarding evidence or generating another charged job.

The service does not silently issue extra YouTube API requests. Agents reuse
already-saved channel/video API responses and submit small, attributed excerpts.
The API has no dedicated business-email field; extraction works only when the
address is present in public descriptions or other supported sources.

## Enrichment stages

1. Inspect provided evidence deterministically for explicitly contextualized
   creator/team contact emails and relevant contact-page links. Preserve source,
   discovery method and unverified-delivery status. A found suitable contact ends
   enrichment without a Gemini call.
2. Classify the actual target hostname, not the caller-provided platform label.
   Do not download YouTube, X/Twitter, or Twitch platform HTML as a generic contact
   page. Use exact host/subdomain matching, never substring matching. Preserve
   SSRF checks, DNS pinning, redirect checks, timeouts and byte limits for fetched
   ordinary public pages. Do not bypass login, CAPTCHA, or platform controls.
3. For ordinary websites, retain the existing public-page extraction route. For
   platform targets, inspect up to two distinct attributed external contact links
   found in evidence. Do not recursively crawl or fetch arbitrary model-provided
   URLs through the backend transport.
4. If still unresolved, send the identity and bounded public evidence to the
   existing Gemini search/URL-context fallback. Keep its current call/token
   ceilings and usage accounting. Preserve returned search and URL-retrieval
   diagnostics so an empty model list is not the sole proof of a complete lookup.

Platform-page skipping is an intentional stage outcome, not
`public_page_too_large` and not proof that no email exists. A skipped page alone
does not fail a job whose independent fallback completed adequately.

## Completion, coverage and retries

Keep the public job states `queued`, `running`, `completed`, and `failed`.
Add versioned stage diagnostics in checkpoints rather than changing the meaning
of those states. Record supplied-evidence inspection, platform-page skipping,
external fetch outcomes, and provider search/retrieval coverage.

A sourced contact can complete with its existing unverified label. An empty job
may complete only when the relevant public-page inspection or independently
observable search coverage completed, with no unresolved retrieval failures
being used as evidence of absence. Missing provider coverage, failed relevant
contact retrieval, quota blockage, malformed output and timeouts remain
failed/unresolved with stage-specific reasons. A completed empty job means no
contact found in the checked scope, never proof that no address exists anywhere.

For the search-only route, the minimum observable coverage is a successful model
response, at least one reported search query, and at least one grounding web
source with a valid public URL. Explicit unsuccessful URL Context retrievals
remain unresolved diagnostics. Missing grounding metadata cannot be treated as
zero searches or as a complete empty lookup. Tests must pin these conditions;
do not substitute the model's self-declared confidence for provider metadata.

Version checkpoints so valid successful work is reused. An old empty model
checkpoint associated with a failed lookup lacks the new completion evidence:
on an explicitly authorized retry, perform at most one fresh fallback call and
retain the historical ledger records. A valid new-version empty checkpoint is
reused; retries must not become an unbounded model-spending loop. Preserve job
ID, owner, run ID, idempotency key, leases, and historical usage attribution.

## CLI and Skill guidance

Update `cli/internal/email.go`, CLI help/tests, backend email request/enricher/
Gemini tests, and both distributed Skills' relevant contact references. Keep
command examples and evidence schema in one authoritative mechanics reference.

The research Skill must require the ordinary contact lookup first, then reuse
saved API descriptions/source URLs with `--evidence` when enrichment is needed.
An existing email avoids enrichment. Standalone contact requests may use only a
URL. One enrichment per selected creator remains the default ceiling; an
explicitly requested retry is distinct from silently submitting a duplicate.
Poll the same job, preserve unresolved contacts, display only the selected primary
email, and report metered usage including retry costs. No lookup grants send
permission. Preserve all follower/name/evidence and human-confirmation gates.

## Verification and release

Use regression-first tests for API-evidence email extraction without network/model
calls; platform targets without HTML fetch; contact-page extraction; URL/DNS/
redirect rejection; bounded/invalid evidence and idempotency conflicts; successful
versus incomplete empty fallbacks; metadata absence/retrieval errors; old and new
checkpoint retry behavior; CLI old/new command contracts; and usage attribution.

Run the full backend suite with isolated local PostgreSQL/Redis as previously
used (without Docker), Go tests/vet, Skill validators and behavioral scenarios,
bundle/installer tests, and public-upgrade checks. Mail sending, unknown delivery,
monitoring and bounce safety regressions must remain passing.

Publish a matching next CLI/Skill version (expected 0.7.6, verify availability)
and installation guide. Back up the production database, preserve the previous
image and release rollback targets, and deploy API/worker together with graceful
worker draining. Verify health and authenticated read-only calls before recovery.
Do not restart unrelated services or blindly replay in-flight jobs.

## Recovery of the affected jobs

Resolve the exact affected run from live data; the previous observation was
`liminal-narrative-500-20261013`. Save a private manifest of failed job IDs,
owners, error codes and original state at the recovery boundary. Do not select
all historical failures. Do not touch completed jobs or duplicate queued/running
jobs. Include retryable page-incomplete/model-output/transient failures in this
run, but inspect nonretryable upstream rejections/configuration errors first.

Reprocess one or two eligible existing jobs as a canary, then requeue the remaining
eligible manifest entries once through the established job-retry path. Old jobs
have no supplied API evidence; use the platform-aware search fallback and honest
coverage rules, not fabricated evidence. Retain concurrency two and do not raise
request limits. Stop recovery on provider quota/auth failures or a repeated
systemic error; retain outstanding IDs rather than loop indefinitely.

Record before/after state counts, found-email count, unresolved causes, additional
Gemini estimated cost and release/image versions. Distinguish job records from
unique creators and requeued work from work actually completed. No email-send
attempt belongs to this recovery.
