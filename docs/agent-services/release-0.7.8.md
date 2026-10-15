# FMG 0.7.8 — economy email enrichment

The user accepted the measured cost/retention tradeoff on 2026-10-15 and authorized
deployment and the coordinated CLI/Skill release. Batch recovery remains a
separate decision. Deployment acceptance is recorded below when verified.

- Gemini requests low thinking and a prompt-only search target: three initial
  query strings, up to three more only for a new concrete official contact lead.
  Stop on one suitable email or no new lead; avoid synonym loops and repeated
  unavailable platform-page fetches. URL Context target: two external pages.
- Retain the output ceiling to avoid truncating paid searches; request at most
  one suitable email in the existing JSON format. Optional sources stay optional.
- Persist `search_policy` with observed queries, unknown usage and overages.
  This is not a provider-enforced search cap. Valid empty results remain Not Found;
  overages do not cause another paid attempt. Actual errors remain failures.
- CLI surfaces the server-recorded policy on completed job reads; older records
  are not relabeled. Both Skills explain evidence/result reuse and soft budgets.
  Existing job reuse is not a new global 30-day negative cache.

## Pre-deployment validation plan

Use an isolated one-shot adapter and read-only historical sample selection, never
enqueue production jobs or change saved creator results. Freeze 20 historical
Found plus 10 Not Found, stratified by platform and historical search cost. Send
only the original inputs, never historical answers, to the new adapter. Maximum
one new call per sample; stop on provider errors, unknown search accounting, or
aggregate observed search usage exceeding the 180-query sample target. The last
in-flight call can exceed a soft target; it is not a hard cost guarantee.

Record successful calls, original-address recovery, alternate addresses requiring
review, empty results, actual query counts, thinking and tool-input tokens, and
pricing exclusions. Historical responses serve as baseline without rerunning the
old expensive policy. Targets: at least 18/20 original Found recovered and at least
60% reduction in comparable search cost. Thirty selected cases provide an initial
screen, not population-wide proof. Record actual results before release.

## Sample results — 2026-10-15, before deployment authorization

- Backend complete suite: **375 passed, 1 skipped** (Docker opt-in), one existing
  Starlette/AnyIO deprecation warning. Go complete suite and vet passed. Both Skill
  validators passed. Four local release/installer tests and every archive SHA256
  passed for the locally built 0.7.8 candidate. No public release was published.
- Exactly **30** isolated Gemini calls completed, with no provider failures and
  no automatic retries. Frozen cohort: 20 historical Found (14 YouTube/6 Twitch)
  and 10 historical Not Found (5 per platform), evenly spaced across historical
  query counts in each stratum. Original inputs only; no historical answers were
  supplied. Historical jobs/results were not replaced or requeued.
- Historical Found recovered: **11/20 (55%)**, all the same original addresses.
  Nine were empty. One of the ten historical Not Found cases returned an email;
  nine remained empty. Overall: 12 Found, 18 Not Found, all still unverified for
  delivery. The **18/20 retention target failed**.
- Queries: **568 historical vs 131 candidate**, down **76.94%**. Search-only
  list-price comparison at USD 0.014/query: **USD 7.952 vs USD 1.834**. These exclude
  shared free allowance/discounts and are not actual invoice debits. The known
  ledger subtotals including priced tokens are USD 8.019644375 vs USD 1.846624750;
  respectively 7 and 2 records have incomplete accounting. Existing tool/cache
  token accounting gaps remain, so those subtotals are not full comparable bills.
- Two candidate calls made **7 queries**, exceeding the requested soft total of
  six. Observed search counts were present for all 30; max was seven. New responses
  omit `thoughtsTokenCount` in all 30, so thinking usage is unknown, not zero.
- The source adapter SHA256 was
  `0d5ff36d3346cebb98fbf408fb71adcaace6788ceae40358c92906aac7649f49`.
  Private manifest, raw responses and results are retained in the protected
  `economy-sample-20261015` diagnostic directory; sanitized local aggregates are
  in `.local/enrichment-economy-report-20261015.json` (not distributed).
- Production API/worker remain on **fmg-agent:outcome-cc34b8f**, API healthy and
  worker running. No mail configuration, sending task, worker/image or service
  was changed. Local test PostgreSQL/Redis were stopped; local Docker stayed off.

Initial recommendation was to keep the candidate undeployed: savings target
passed, email-retention target failed. The user subsequently explicitly accepted
the 55% measured retention and requested release. This selected historical
comparison does not isolate prompt budget from thinking level or search variation.
The proposed additional experiment on nine missed cases has not been started.

## Public release and deployment acceptance — 2026-10-15

- The owner explicitly accepted the measured 55% historical-address retention
  and authorized release. Source `c414929190d3732652a735e879fbc646c6101007` was
  pushed to `origin/cli` and published as `fmg-v0.7.8` with all seven assets.
- Both production API and worker now run `fmg-agent:economy-c414929`; API health
  is healthy and worker is running. An offline, network-disabled image check
  verified low thinking, actual query overage reporting, normal empty completion
  without retry, and the exact adapter SHA256 used in the approved sample.
- A verified custom-format database backup is retained at
  `/var/backups/find-me-gamer-agent/economy-c414929-20261015/agent.dump`.
  The previous `fmg-agent:outcome-cc34b8f` image remains available for rollback.
- No sends, approved pending recipients, enrichment jobs or bounce retries were
  in flight at the switch. Before/after checks preserved job/send/retry counts,
  frozen task/draft digests, sender safety, migration `0011_bounce_retry` and
  five-second send pacing. Mailbox monitoring resumed successfully at
  `2026-10-15T07:33:14Z` without an error.
- Local public-release downloads and independent anonymous server downloads
  passed every asset SHA256 check. All four bundle/installer tests passed on the
  downloaded public assets. The focused backend suite passed 42 tests; complete
  Go tests and vet passed again before release. The earlier complete backend
  result above applies to the unchanged implementation.
- An isolated real 0.7.7 installation successfully upgraded using
  `fmg upgrade --latest --skills`. CLI and both Skill markers report 0.7.8,
  refreshed update status is current, existing authentication remains valid,
  and both installed Skills plus email/completion references were re-read.
- Deployment acceptance used no additional paid provider queries and sent no
  mail. Bulk enrichment was not resumed; the paused recovery monitor remains
  paused. Local Docker was not started.
