# FMG 0.7.7 — best-effort email enrichment outcomes

- Valid Gemini emails complete as Found even without a source URL; retain
  `model_reported_unverified`. Normal valid empty responses complete as Not Found.
  Optional grounding/retrieval diagnostics no longer block completion or a batch.
- Real quota/credit, HTTP, transport and invalid/truncated-output errors remain
  failures. Failed-attempt markers cannot be mistaken for successful empty results.
- Reuse saved valid checkpoints, including old source-only empty failures, without
  another paid call. Preserve original jobs, run attribution and historical usage.
- CLI job output includes `outcome=found|not_found` for completed results. Both
  Skills and the research validator accept unsourced model results with saved
  completed service-response provenance; no invented URLs or verified-delivery claim.
- Evidence-first extraction and bounded contact-page/Gemini fallback remain.
  Mail templates, sending approvals, pacing, replies and bounce safety are unchanged.

Upgrade with `fmg upgrade --latest --skills`, then read both installed Skills and
their email/completion references. Upgrading does not authorize replay or sending.

## Verification

- Full backend suite with isolated native PostgreSQL/Redis: 369 passed, one Docker
  opt-in check skipped, one existing Starlette/AnyIO deprecation warning. Local
  Docker remains stopped. Go tests/vet and both Skill validators passed.
- Four local release-bundle/installer tests and all archive SHA256 checks passed.
- Independent Skill application changed the old unresolved interpretation into
  Found/Not Found for normal completed responses while preserving real 429 errors
  and no-send authority. Existing public evidence still avoids enrichment entirely.
- Independent review found malformed optional nested URL metadata could invalidate
  valid emails. Four regressions reproduced it before the fix. Failed/interrupted
  old/current attempt markers are also tested; the final full suite includes them.
- Research validation accepts source-null model contacts with a completed saved
  response artifact; removing that provenance still fails validation.

Public bundle and deployment acceptance will be recorded after the checks actually
run. Recovery is separate from release acceptance; queued jobs are not claimed
completed, and estimates are not actual charges.

## Public bundle and deployment acceptance — 2026-10-14

- Source `cc34b8f4711ab54e30abec562ba7049fa423ab70` pushed to `origin/cli` and
  published as `fmg-v0.7.7` with all seven assets. Independent local downloads and
  anonymous server downloads verified every SHA256; four bundle/installer tests
  passed again on the downloaded public assets.
- An isolated real 0.7.6 installation upgraded using `fmg upgrade --latest --skills`.
  CLI and both installed Skill markers report 0.7.7; refreshed update status is
  current, saved authentication still succeeds, and installed instructions were
  re-read. No provider query or email-send attempt was used for upgrade acceptance.
- Both API and worker deployed to `fmg-agent:outcome-cc34b8f`. The image's offline
  checks verified source-null/empty parsing and public-evidence extraction without
  network/model calls. The former `fmg-agent:search-b26cda4` remains for rollback.
- Verified custom-format database backup:
  `/var/backups/find-me-gamer-agent/outcome-cc34b8f-20261014/agent.dump`.
  Deployment preserved send counts, frozen task/draft digests, sender safety,
  five-second pacing and migration `0011_bounce_retry`. API is healthy, worker is
  running, and mailbox monitoring resumed with a fresh success timestamp.
- The new recovery snapshot contains exactly 510 untouched original failures and
  five saved normal empty responses. The original 111 completed jobs plus 21
  previously recovered completed jobs are protected by a stable content digest.
  Recovery was launched once, through existing job retry/lease mechanics; its
  completion and final yield are not implied by this deployment acceptance.
- The existing read-only heartbeat was updated/resumed for this recovery. It stays
  quiet during ordinary progress and reports completion or an investigated stop;
  it cannot restart work, spend additional API quota or send mail. Native temporary
  test PostgreSQL/Redis were stopped; local Docker was never started.
