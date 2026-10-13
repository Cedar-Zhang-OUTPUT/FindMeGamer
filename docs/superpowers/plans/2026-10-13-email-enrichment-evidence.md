# API-evidence-first email enrichment implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the current session. Steps use checkbox syntax for tracking.

**Goal:** Deliver the approved enrichment fix in the backend, CLI and Skills,
publish it, and reprocess the affected failed enrichment jobs without sending mail.

**Architecture:** Extend the existing asynchronous enrichment request with bounded
public evidence. Reuse its durable job/lease/ledger architecture, introduce
platform-aware public lookup and provider coverage diagnostics, and migrate
failed legacy checkpoints lazily on explicit retry.

**Tech Stack:** Python 3.13/FastAPI/Pydantic/SQLAlchemy/Celery, Go CLI, PostgreSQL,
Redis, existing Docker production deployment and GitHub CLI release bundles.

**Spec:** `docs/superpowers/specs/2026-10-13-email-enrichment-evidence-design.md`

## Global constraints

- No email delivery, task approval/resume, sender-hold release or template edits.
- Preserve reply/bounce monitoring, existing leases/ownership, and concurrency two.
- Keep local Docker stopped; use isolated native PostgreSQL/Redis for full tests.
- Evidence: ten records maximum; 8,000 characters per text; 32,000 total text characters.
- CLI evidence file: maximum 256,000 bytes; public HTTP(S) source URLs only.
- Preserve existing page-fetch byte/time/redirect/DNS/SSRF limits and model ceilings.
- No implicit extra platform API calls or unbounded provider retries.
- Preserve job/run/idempotency identity and historical usage during recovery.

## Review focus

- Old clients omit evidence: same-key requests must still match jobs created before deployment.
- Hostname lookalikes and redirects: platform classification must not weaken SSRF protections.
- Valid empty model output with missing/failed retrieval metadata: remains unresolved on search-only paths.
- Repeated retry of a migrated empty checkpoint: must not repeatedly incur model cost.
- Recovery racing with normal processing: never duplicate active/completed jobs or touch another run.

---

### Task 1: Optional evidence contract in backend and CLI

**Files:** create `agent-service/src/fmg_agent/email/evidence.py`; modify
`agent-service/src/fmg_agent/email/routes.py`, `cli/internal/email.go`,
`cli/internal/command.go`; test `agent-service/tests/test_email_jobs.py`,
`cli/internal/email_test.go`.

**Interfaces:** `ContactEvidence` validates `source_url`, `text`, optional `kind`.
`EnrichRequest.evidence` is optional. CLI `--evidence FILE` consumes a JSON array
of these records and transmits it as `evidence` on the existing endpoint.

- [ ] Add backend tests for valid evidence; record/text/aggregate limits; unknown fields; unsafe URLs; evidence-sensitive idempotency; legacy same-key compatibility. Assert 202 for valid/repeated identical input, 409 for changed evidence, 422 for invalid evidence.
- [ ] Add Go tests for valid arrays, missing/malformed/oversized files, trailing JSON, invalid records, legacy invocation, and an old server rejecting evidence. Assert invalid files cause zero HTTP requests; server rejection causes one request and no stripped-evidence resubmission.
- [ ] Run new tests and record their failures against the current implementation.
- [ ] Implement bounded validation and `--evidence`; omit the optional field when absent so stored legacy input remains compatible. Preserve idempotency conflict behavior and reject malformed input before creating work.
- [ ] Run `python -m pytest tests/test_email_jobs.py -q` from agent-service and `go test ./internal -run TestEmail -count=1` from cli using the existing Python runtime.
- [ ] Commit the tested contract changes.

### Task 2: Evidence extraction and platform-aware public lookup

**Files:** modify `agent-service/src/fmg_agent/email/evidence.py`,
`agent-service/src/fmg_agent/email/enrichment.py`; test
`agent-service/tests/test_email_enrichment.py`.

**Interfaces:** evidence helpers return attributed contacts and at most two
distinct external contact URLs. `Enricher.public_contacts(target)` retains an
`emails` array and adds versioned inspection/skip/fetch diagnostics.

- [ ] Add tests asserting attributed evidence email extraction skips all page/model calls; platform targets skip generic HTML; missing evidence still permits fallback; ordinary websites retain extraction; contact links remain bounded and fetched through PublicPageGateway.
- [ ] Add hostname lookalike/subdomain, malicious evidence instructions, duplicate links and unsafe redirect/DNS regressions. Assert private targets never reach transport and labels cannot override actual hostname classification.
- [ ] Run new tests to demonstrate failures before implementation.
- [ ] Implement evidence-first extraction with existing email/context rules and exact platform host matching. Keep public-page gateway resource/safety limits unchanged; distinguish intentional platform skipping from fetch failure.
- [ ] Run `python -m pytest tests/test_email_enrichment.py tests/test_email_jobs.py -q` and commit.

### Task 3: Coverage-aware completion and checkpoint-safe retries

**Files:** modify `agent-service/src/fmg_agent/email/gemini.py`,
`agent-service/src/fmg_agent/email/enrichment.py`; tests in
`agent-service/tests/test_email_enrichment.py`, `agent-service/tests/test_email_worker.py`.

**Interfaces:** `GeminiGateway.find(target)` retains `emails`, `usage` and
`model_version`, adding bounded provider coverage diagnostics. Versioned
checkpoints distinguish legacy empty results from newly inspected results.

- [ ] Add tests for search-only completed empty output with a reported query and valid grounding web source; missing query/source, malformed metadata and explicit URL Context retrieval failure must remain unresolved. A sourced found contact retains its unverified label.
- [ ] Add retry tests with an old page-too-large plus empty-model checkpoint: explicit retry performs one fresh fallback, preserves identity/ledger and does not refetch platform HTML. Repeating a new-version empty checkpoint must not spend again; valid successful checkpoints remain reused.
- [ ] Add lease/worker restart and attribution checks: no stale lease overwrites, no automatic paid replay, no missing historical cost when a checkpoint is replaced.
- [ ] Run tests and retain regression failures before changing implementation.
- [ ] Parse provider diagnostics defensively, pass bounded evidence as untrusted context, and implement completion/reuse decisions. Do not infer zero search cost from missing metadata or turn incomplete searches into Not Found.
- [ ] Run all email enrichment/job/worker/usage tests; commit.

### Task 4: Matching Skill instructions and complete regression validation

**Files:** modify `skills/fmg-api/SKILL.md`,
`skills/fmg-api/references/email.md`, `skills/fmg-research/SKILL.md`,
`skills/fmg-research/references/outreach.md`,
`skills/fmg-research/references/completion.md` where needed;
add behavioral tests in `agent-service/tests/test_enrichment_skill.py`.

**Interfaces:** email mechanics reference owns the evidence JSON example and CLI
syntax; research instructions route to it. Completion remains required and
unresolved contacts remain visibly incomplete.

- [ ] Exercise realistic saved-API-evidence, URL-only lookup, existing-email, incomplete-empty and large-batch cases against the old guidance and record gaps.
- [ ] Update guidance: reuse saved public evidence, submit one stable job, poll the same ID, require completed coverage before Not Found, preserve one primary email and report retry costs. Retain all follower/name/game-confirmation and send-approval requirements.
- [ ] Validate both Skills with skill-creator `scripts/quick_validate.py`; run behavioral cases and assert evidence reuse, no extra platform lookup, no guessed contacts, and no sending permission.
- [ ] Run the full backend suite with isolated native PostgreSQL/Redis; Go `go test ./...` and `go vet ./...`; Black checks and `git diff --check`. Confirm sending/unknown-delivery, inbox and bounce/pacing regressions still pass.
- [ ] Review the complete diff for scope, safety and backward compatibility; resolve findings and rerun affected checks before committing.

### Task 5: Production deployment and public CLI/Skill release

**Files:** create `docs/agent-services/release-0.7.6.md` if the tag is available;
update `docs/agent-services/AGENT-INSTALL.md` to the actual chosen version. Use
existing `cli/scripts/build-release.sh` and `deploy/agent-services/deploy.sh`.

**Interfaces:** matching four-platform CLI archives, Skill archive, installer,
checksums, production API/worker image and release notes.

- [ ] Inspect remote release tags, deployment configuration and live queue/leases; select the unused next version and record existing image/container and rollback references without exposing secrets.
- [ ] Build the release bundle; run `python -m pytest cli/tests/test_release_bundle.py -q` with its documented fixture setup and verify archive contents/checksums.
- [ ] Back up production DB and drain in-flight worker work gracefully. Deploy only the API/worker to the tested image; preserve queued work and run no send commands. Verify migrations are unnecessary, health is good, and authenticated reads work.
- [ ] Push origin/cli and publish matching release assets. Download the public assets independently and verify SHA256; use an isolated installation to execute `fmg upgrade --latest --skills`, then verify version, auth, update detection and installed Skill markers.
- [ ] Record deployment/release/test evidence and rollback instructions. Stop temporary local test services after validation.

### Task 6: Bounded recovery of affected failed jobs

**Files:** create a private `.local` recovery manifest/helper and append aggregate
recovery results to the release evidence; no private contact data in committed docs.

**Interfaces:** existing `JobStore.retry(job_id, token_id)` or authenticated retry
endpoint; no direct state rewrites or new enrichment submissions.

- [ ] Query live affected run `liminal-narrative-500-20261013`; save exact failed IDs/owners/error codes, current state counts, original model usage and estimated cost. Inspect nonretryable provider/configuration failures separately.
- [ ] Dry-run eligibility checks, including completed/active/other-run jobs and state changes since manifest creation; assert these are excluded.
- [ ] Retry one or two eligible existing jobs once and inspect completion/coverage/cost. On quota/auth or repeated systemic failures stop and preserve outstanding IDs.
- [ ] After canary success, requeue each remaining eligible manifest job once through the existing retry path. Keep concurrency two and leave queued/running/completed jobs untouched.
- [ ] Reconcile outcomes and report found/empty/unresolved counts plus incremental estimated cost, distinguishing job records from creators. Do not claim queued jobs are completed and do not send mail or resume outreach batches.

## Self-review

The six tasks cover the complete approved spec. Contract tests pin all numeric
limits and legacy input compatibility; enrichment tests pin hostname/SSRF safety;
coverage/retry tests pin truthful empties and bounded spend; recovery dry-run and
rechecks pin exact scope and race behavior. No product implementation or live
mutation is part of this planning commit.
