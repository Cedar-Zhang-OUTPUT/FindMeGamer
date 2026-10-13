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
