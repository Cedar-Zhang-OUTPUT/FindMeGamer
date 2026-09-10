# Single Creator Search recovery acceptance — 2026-09-10

## Scope and dispatch

Backend revision: `991a8efbc21a1203fe1ec4c131bdac6dc7bba862`.
Deployment verification is recorded separately in
`recovery-deployment-2026-09-10.md`; this document covers the subsequently
authorized **one** real recovery request, not another deployment.

- Search: `01b3b649-f5ad-40b1-a146-aac2d666e1ea`.
- Activity: `f41b27fd-e561-4505-8ad1-6b17ba88a75c`.
- Evaluation: `073a47d5-6049-4677-ab6e-29e676a2e3c6`.
- Idempotency key: `fmg-recovery-991a8ef-01b3b649-20260910-v1`.
- One POST to the existing Search retry endpoint, with
  `acknowledge_unknown=false`, returned HTTP 202. A private local ledger prevents
  accidental repetition. There was no POST retry loop.
- Baseline: 17:25:02 Shanghai. Natural terminal state: 17:29:48,
  `partial/complete`. Final database/worker observation: 17:32:39.

## Business result

| Measure | Before | After |
| --- | ---: | ---: |
| Discovery candidates | 50 | 50 |
| Usable Creator Profiles | 30 | 46 |
| Failed Profile units | 20 | 4 |
| Email available | 18 | 29 |
| Email missing | 12 | 17 |
| Email pending behind failed Profile | 20 | 4 |
| Successful deep evaluation steps | 16 | 16 |
| Failed deep evaluation steps | 9 | 19 |
| Successful screening steps | 2 | 3 |
| Successful ranking steps | 1 | 1 |

Sixteen of the twenty new checkpoint-recovery jobs succeeded. Four failed:
two `deepseek_model_output_invalid`, one `deepseek_model_evidence_invalid`,
and one `deepseek_model_contacts_invalid`. Those failures remain untouched.
Final Profile statuses are 31 ready, 15 reused, and 4 failed. No email-stage
failure was recorded; the four pending email statuses belong to failed Profiles.

The original nine failed deep steps reached attempt 2 and remained failed.
Ten newly selected candidates reached attempt 1 and failed. All nineteen carry
`evaluation_model_output_invalid`. No new successful Match result was produced;
the original sixteen successful deep results and ranking remain available.

## Preservation and idle-state checks

Repeatable-read, read-only queries compared the original successful records to
the pre-request baseline. All seven groups retained identical content hashes:

- 30 original successful Profiles, 27 contacts, and 851 works;
- 35 original AnalysisJobs and 363 original checkpoint nodes;
- 19 original successful evaluation steps;
- 50 DiscoveryCandidates.

All twenty recovery jobs retained exact copies of the source jobs' existing
checkpoint payloads and creation timestamps. Historical failed jobs were not
reopened or overwritten. These checks cover the named baseline groups, not a
claim that all database tables stayed unchanged during legitimate new work.

The worker reported zero active, reserved, and scheduled tasks at the final
observation. All four sending tables had zero rows: `send_batches`, `deliveries`,
`activity_send_batches`, and `activity_deliveries`. No SMTP send was initiated.

## Request and failure evidence, with limits

A fixed worker-log window, 17:25:02–17:32:40 Shanghai, contains **101 completed
DeepSeek HTTP 200 request records**, and no matching YouTube, Gemini, or thumbnail
HTTP request records. This is a log count, not a provider billing ledger or exact
per-job token/cost allocation. Successful HTTP records do not identify the model;
runtime map/reduction/Brief constants were verified as `deepseek-flash`.

All twelve structured validation-failure events in that window belong to Creator
analysis, not `EvaluationMatchBrief`. They identify these concrete categories:

- Invalid JSON, including both repair failures for two video-batch attempts.
- `primary_games` / `genres` **array item-count** limits (`too_long`), not narrative
  string-length limits.
- Evidence/reference validation errors.
- Missing `unavailable.provenance` in regional audience inference.

Some initial validation failures recovered after the gateway's bounded repair;
global events cannot all be attributed one-to-one to the four failed jobs.
No `string_too_long` or `deepseek_output_truncated` event was present.

**The exact nineteen deep-evaluation failure subtypes are not recoverable from
the retained evidence.** The current worker maps candidate-ID, work-ID,
supported-evidence and narrative validation failures to one public code; it does
not log their safe internal subcodes or retain failed output. The fixed log
window has no corresponding evaluation schema failure or internal-subcode event.
It would be incorrect to label all nineteen as an evidence, length, or model
truncation problem based on this evidence alone.

If another diagnostic iteration is authorized, retain a safe fixed reason code
before attempting reproduction. That is a follow-up, **not implemented here**.
No paid probe, additional Search retry, provider reacquisition, sending action,
or further service change was performed for this final read-only verification.

## Handoff boundary

The one authorized retry is consumed. New failures remain for a separate decision;
do not automatically retry or treat `retryable=true` as authorization. The
coordinator confirmed the deployment/recovery heartbeat is paused.
