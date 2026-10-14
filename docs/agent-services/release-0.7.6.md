# FMG 0.7.6 — API-evidence-first email enrichment

## Changes

- Optional `fmg email enrich --evidence FILE` accepts a bounded JSON array of
  attributed public API/profile excerpts. Existing URL-only clients remain
  supported; absent evidence preserves legacy idempotent input.
- Contextualized emails in supplied evidence finish without a model call.
  YouTube/X/Twitch targets skip generic platform HTML and inspect at most two
  relevant external contact links before Gemini search fallback. Existing fetch
  byte/time/redirect/DNS safety limits remain unchanged.
- Search-only empty completion requires observable provider search and grounding
  sources, with unsuccessful URL retrievals remaining unresolved. Failed legacy
  empty checkpoints may receive one new fallback under explicit retry; new-version
  empty checkpoints are reused. Historical run usage is retained.
- Both Skills teach source reuse, scoped Not Found versus incomplete lookup,
  stable jobs/idempotency, bounded authorized recovery and retry cost reporting.
  Email templates, mail delivery approvals, reply monitoring and bounce pauses
  are unchanged.

## Verification so far

- Evidence contract, platform fetch avoidance, grounding coverage and legacy
  checkpoint regressions were observed failing, then passing.
- Full backend suite after review fixes with isolated native PostgreSQL/Redis: 332 passed, one
  Docker opt-in check skipped (local Docker stays stopped), one existing
  Starlette/AnyIO deprecation warning. First native DB run failed because the
  temporary DB used SQL_ASCII; recreating only that isolated empty test DB as UTF8
  fixed the environment. No production DB change was involved.
- Go tests/vet, both Skill validators, and independent before/after Skill
  application scenarios passed. Baseline could only submit URL-only jobs;
  updated guidance correctly supplies literal evidence without repeated research,
  preserves failures as unresolved and does not authorize sending.
- Independent code review found redirect-to-platform fetching, repeated spending
  after failed legacy refresh, and malformed embedded links discarding a known
  contact. Four new regressions reproduced these before fixes. Redirect handling
  now skips platform transport after URL/DNS admission; legacy refresh is marked
  durably before calling the provider; malformed links do not discard contacts.
  Focused tests and the complete 332-test suite passed after the single fix pass,
  including the failed-refresh marker on an ordinary (non-platform) website.

## Upgrade

`fmg upgrade --latest --skills`, then verify version/auth and re-read both
installed Skills and the email reference. Upgrading is not permission to replay
completed jobs or send mail. Production deployment and bounded recovery evidence
will be appended after actual verification, not inferred from local tests.

## Production acceptance — 2026-10-13

- API/worker deployed to `fmg-agent:enrich-156004b`, preserving the original sender,
  five-second pacing, all frozen draft/task digests, safety state and migration
  revision `0011_bounce_retry`. No migrations, template changes or send approvals
  were performed. The former image `fmg-agent:invalid-5f71692` is retained.
- Database custom-format backup was verified before the switch. Backup:
  `/var/backups/find-me-gamer-agent/enrich-156004b-20261013/agent.dump`.
- The built image passed API-evidence extraction without any network/model call.
  Existing authenticated clients remain supported. Worker monitoring resumes
  after the brief deployment/canary maintenance window.
- A private recovery manifest froze the requested run's 536 failed jobs and
  preserved its 111 completed jobs. One original failed job was retried as a
  canary; the new pipeline correctly skipped YouTube HTML without a page-size
  error. An upstream provider admission failure stopped recovery before any
  bulk requeue; exact diagnostics are retained in the private operator record.
  This release does not claim those failed jobs recovered. Provider availability
  must be restored and recovery revalidated before continuing.

## Public bundle acceptance

- Published `fmg-v0.7.6` from `ca3c46dfe418a817a408bf03a77e13e33c0d924e`;
  source pushed to `origin/cli`. All seven public assets were downloaded again,
  SHA256 verification passed, and all four installer/bundle tests passed on those
  downloaded assets. Independent anonymous server-side downloads also verified
  every binary archive, the Skill archive and installer.
- An isolated real 0.7.5 installation ran `fmg upgrade --latest --skills` against
  the public release. CLI and both Skill markers now report 0.7.6; existing
  authentication remains valid; a refreshed update check reports `current`.
- Post-deployment snapshots show unchanged send counts, frozen task/draft digests,
  sender safety, migration and pacing; mailbox monitoring is active with a fresh
  success timestamp. No email was sent or approved by release/recovery actions.
- Native temporary PostgreSQL/Redis test services were stopped. Local Docker was
  never started. The private recovery ledger remains available because upstream
  availability still blocks the requested bulk recovery; do not blindly rerun
  the canary or mark those failures as Not Found.

## Recorded execution decisions

- Skill behavior was tested by independent consuming agents rather than source
  wording assertions; tradeoff: no automated wording-change detector, covered by
  executable CLI/backend tests and before/after realistic scenarios.
- Live provider behavior was verified separately from local tests; tradeoff:
  passing local tests does not establish production recovery yield, so recovery
  stays incomplete when the canary fails.
- The worker was gracefully drained for the bounded canary before restarting the
  new image; tradeoff: a short mailbox-monitor maintenance window, avoiding a
  dispatcher/manual-claim race. Monitoring was checked again after restart.

## Search-record compatibility hotfix — 2026-10-14

- Live JSON-only empty results omitted provider grounding metadata. Explicit
  server-side tool records exposed searches but suggestion HTML did not establish
  checked sources. A single sourced report followed by one strictly parsed final
  JSON block restored real grounding sources in the bounded verification.
- The adapter now retains bounded executed-search diagnostics and a research
  summary. Model-reported URLs and search suggestions never substitute for
  provider grounding sources. Missing/mixed incomplete tool records keep total
  search pricing unknown and empty lookups unresolved.
- Explicit retry can refresh an old incomplete search checkpoint once; the old
  checkpoint and historical usage remain preserved. A durable search-version
  marker prevents repeated paid refreshes on subsequent retries.
- Final full native PostgreSQL/Redis suite: 349 passed, one Docker opt-in skip,
  one existing Starlette warning. Two independent-review findings concerning
  mixed incomplete tool records were reproduced and fixed with regression tests.
  Changed files pass Black; the repository-wide check still reports eleven
  pre-existing unrelated formatting differences, left untouched.
- Existing 0.7.6 CLI/Skill commands remain compatible. This is a backend adapter
  hotfix, not a new CLI command or a permission to send mail. Deployment and
  failed-job recovery are not implied by these local verification results.

### Hotfix production acceptance

- Source commit `b26cda4` pushed to `origin/cli`; both API and worker deployed to
  `fmg-agent:search-b26cda4`. The previous `fmg-agent:enrich-156004b` image remains
  available for rollback. Verified custom-format database backup:
  `/var/backups/find-me-gamer-agent/search-b26cda4-20261014/agent.dump`.
- Existing 0.7.6 CLI authentication succeeds. Deployment snapshots preserve
  frozen task/draft digests, sender, safety state, five-second pacing, sends and
  migration revision. Inbox monitoring resumed and reported a fresh success.
- The original YouTube and Twitch canaries completed through the deployed worker.
  One-shot recovery then began for the original 536-job manifest, checking
  ownership/run/state/timestamp and preserving the original 111 completed jobs.
  It does not submit duplicate jobs, send mail or remove incomplete-search gates.
  Only two recovery jobs may be in flight; provider blockers or two consecutive
  same-code failures stop the recovery. Started/queued work is not claimed complete.
- Five explicitly authorized diagnostic/verification calls have a recorded
  priced subtotal of USD 0.693227775, with incomplete pricing in two early calls;
  this is not a full cost or actual debit. Batch recovery costs are recorded
  separately in the original run ledger. Native temporary test services are
  stopped; local Docker was not started.
